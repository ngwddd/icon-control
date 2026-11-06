"""v1.4.0 headless policy: the MCP connection is the authority.

These tests pin the *new* default. The retained human-approval flow keeps its
own coverage through ``authority_fixture`` (which sets ICON_CONTROL_POLICY=human).
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from computer_mcp import agent_session, capabilities, policy, security, workspace


class LocalPolicyCase(unittest.TestCase):
    """Runs with a throwaway home and the local policy enabled."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name) / 'state'
        self.state.mkdir()
        self.env = patch.dict(os.environ, ICON_CONTROL_HOME=self.temp.name,
                              ICON_CONTROL_POLICY='local')
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.temp.cleanup)
        security.provision_token()
        agent_session.register('headless test')

    def stop_file(self, payload=None):
        path = self.state / 'emergency-stop.json'
        body = dict(payload or dict(stopped_at=__import__('time').time()))
        body['signature'] = security.signature(body, security.load_token())
        path.write_text(json.dumps(body), encoding='utf-8')
        return path


class ModeTests(LocalPolicyCase):
    def test_default_is_local(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('ICON_CONTROL_POLICY', None)
            self.assertEqual(policy.mode(), 'local')
            self.assertTrue(policy.is_local())

    def test_human_mode_can_be_selected(self):
        with patch.dict(os.environ, ICON_CONTROL_POLICY='human'):
            self.assertFalse(policy.is_local())


class AuthorityTests(LocalPolicyCase):
    def test_status_grants_without_any_bridge_or_trust(self):
        state = policy.state()
        self.assertTrue(state['granted'])
        self.assertEqual(state['source'], 'local')

    def test_authorization_covers_every_scope_and_target(self):
        auth = policy.authorization()
        self.assertEqual(set(auth['scopes']), set(capabilities.SCOPES))
        self.assertEqual(auth['applications'], ['*'])
        self.assertEqual(auth['launches'], ['*'])
        self.assertEqual(auth['read_files'], ['*'])
        self.assertEqual(len(auth['agent_session']), 48)

    def test_scope_check_passes_for_every_tool(self):
        from computer_mcp import permission, tool_registry
        denial = permission.check_tool('click', {'x': 1, 'y': 2})
        self.assertIsNone(denial, 'local policy must not block an input tool')

    def test_request_consent_is_a_no_op_headless(self):
        from computer_mcp import permission
        with patch('computer_mcp.consent_ipc.request') as request:
            self.assertIsNone(permission._request_consent({'x': 1, 'y': 2}, {'input'}))
        request.assert_not_called()

    def test_launch_is_allowed_by_wildcard(self):
        from computer_mcp import permission
        with patch.object(permission, 'require'), patch.object(capabilities, 'has_scope', return_value=True):
            record = capabilities.require_launch('C:\\Windows\\System32\\notepad.exe', '')
        self.assertEqual(record['arguments'], '')

    def test_external_file_read_is_allowed_and_still_size_capped(self):
        target = Path(self.temp.name) / 'outside.txt'
        target.write_text('hello', encoding='utf-8')
        with patch.object(capabilities, 'has_scope', return_value=True):
            resolved = workspace.readable_path(str(target))
        self.assertEqual(resolved, target.absolute())
        self.assertEqual(workspace.read_text(str(target)), 'hello')

    def test_size_cap_is_still_enforced(self):
        target = Path(self.temp.name) / 'big.txt'
        target.write_text('x' * (1024 * 1024 + 1), encoding='utf-8')
        with patch.object(capabilities, 'has_scope', return_value=True):
            with self.assertRaises(ValueError):
                workspace.read_text(str(target))


class StopTests(LocalPolicyCase):
    def test_emergency_stop_denies_until_resume(self):
        import time
        policy.resume()
        time.sleep(0.02)
        self.stop_file(dict(stopped_at=time.time()))
        state = policy.state()
        self.assertFalse(state['granted'])
        self.assertEqual(state['code'], 'permission_revoked')
        self.assertEqual(policy.runtime_state(), 'stopped')

    def test_resume_clears_the_stop(self):
        import time
        policy.resume()
        time.sleep(0.02)
        self.stop_file(dict(stopped_at=time.time()))
        self.assertFalse(policy.state()['granted'])
        time.sleep(0.02)
        policy.resume()
        self.assertTrue(policy.state()['granted'])

    def test_unauthentic_stop_fails_closed(self):
        (self.state / 'emergency-stop.json').write_text('{"stopped_at": 1}', encoding='utf-8')
        self.assertFalse(policy.state()['granted'])


class RuntimeStateTests(LocalPolicyCase):
    def test_ready_when_nothing_is_in_the_way(self):
        with patch('computer_mcp.control.status', return_value=dict(owner='idle', enabled=True)):
            self.assertEqual(policy.runtime_state(), 'ready')

    def test_takeover_is_reported(self):
        with patch('computer_mcp.control.status', return_value=dict(owner='user', enabled=True)):
            self.assertEqual(policy.runtime_state(), 'user_takeover')


if __name__ == '__main__':
    unittest.main()
