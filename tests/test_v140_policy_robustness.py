"""Robustness of the v1.4.0 local policy: bad state, bad home, concurrent resume."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from computer_mcp import policy


class PolicyRobustnessCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        (self.home / 'state').mkdir()
        self.env = patch.dict(os.environ, ICON_CONTROL_HOME=str(self.home),
                              ICON_CONTROL_POLICY='local')
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.temp.cleanup)


class CorruptStateTests(PolicyRobustnessCase):
    def test_garbage_record_falls_back_to_a_fresh_authorisation(self):
        (self.home / 'state' / 'local-policy.json').write_text('{not json', encoding='utf-8')
        self.assertTrue(policy.state()['granted'])
        self.assertGreater(policy.authorized_at(), 0)

    def test_record_with_wrong_types_is_tolerated(self):
        (self.home / 'state' / 'local-policy.json').write_text(
            json.dumps({'authorized_at': 'yesterday', 'mode': 7}), encoding='utf-8')
        self.assertTrue(policy.state()['granted'])

    def test_unreadable_stop_file_fails_closed(self):
        (self.home / 'state' / 'emergency-stop.json').write_text('garbage', encoding='utf-8')
        self.assertFalse(policy.state()['granted'])

    def test_missing_state_directory_is_created(self):
        import shutil
        shutil.rmtree(self.home / 'state')
        self.assertTrue(policy.state()['granted'])
        self.assertTrue((self.home / 'state' / 'local-policy.json').exists())


class ResumeTests(PolicyRobustnessCase):
    def test_resume_is_idempotent_and_monotonic(self):
        first = policy.resume()['authorized_at']
        second = policy.resume()['authorized_at']
        self.assertGreaterEqual(second, first)
        self.assertTrue(policy.state()['granted'])

    def test_concurrent_resume_keeps_one_record(self):
        import threading
        results = []

        def worker():
            results.append(policy.resume()['authorized_at'])

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(results), 8)
        record = json.loads((self.home / 'state' / 'local-policy.json').read_text(encoding='utf-8'))
        self.assertIn('authorized_at', record)
        self.assertTrue(policy.state()['granted'])


class HeadlessIsolationTests(PolicyRobustnessCase):
    def test_status_never_imports_the_consent_stack(self):
        """The headless path must not even load the approval machinery."""
        import subprocess
        import sys
        code = (
            'import json,sys\n'
            'from computer_mcp import agent_session, permission\n'
            'agent_session.register("isolation")\n'
            'st = permission.status()\n'
            "names = ['computer_mcp.consent', 'computer_mcp.consent_ipc',\n"
            "         'computer_mcp.permission_bridge', 'computer_mcp.native_consent',\n"
            "         'computer_mcp.native_dialog', 'computer_mcp.native_tray']\n"
            'loaded = [n for n in names if n in sys.modules]\n'
            'print(json.dumps({"granted": st.get("granted"), "loaded": loaded}))\n'
        )
        import os
        env = dict(os.environ, ICON_CONTROL_HOME=str(self.home),
                   ICON_CONTROL_POLICY='local', PYTHONIOENCODING='utf-8')
        result = subprocess.run([sys.executable, '-c', code], capture_output=True,
                                text=True, env=env, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr[-400:])
        report = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertTrue(report['granted'])
        self.assertEqual(report['loaded'], [], 'headless mode loaded approval modules')

    def test_runtime_state_does_not_install_input_hooks(self):
        with patch('computer_mcp.control.status', return_value=dict(owner='idle', enabled=True)), \
                patch('computer_mcp.control.ensure_watcher') as watcher:
            self.assertEqual(policy.runtime_state(), 'ready')
        watcher.assert_not_called()

    def test_runtime_state_reports_user_ownership(self):
        with patch('computer_mcp.control.status', return_value=dict(owner='user', enabled=True)):
            self.assertEqual(policy.runtime_state(), 'user_takeover')


class CacheTests(PolicyRobustnessCase):
    def test_cached_state_is_invalidated_by_a_new_stop_file(self):
        import time
        from computer_mcp import security
        policy.resume()
        self.assertTrue(policy.state()['granted'])
        time.sleep(0.02)
        security.provision_token()
        body = dict(stopped_at=time.time())
        body['signature'] = security.signature(body, security.load_token())
        (self.home / 'state' / 'emergency-stop.json').write_text(json.dumps(body), encoding='utf-8')
        time.sleep(0.02)
        self.assertFalse(policy.state()['granted'], 'cache hid a new emergency stop')

    def test_cached_state_is_invalidated_by_resume(self):
        import time
        from computer_mcp import security
        security.provision_token()
        policy.resume()          # authority must predate the stop
        time.sleep(0.02)
        body = dict(stopped_at=time.time())
        body['signature'] = security.signature(body, security.load_token())
        (self.home / 'state' / 'emergency-stop.json').write_text(json.dumps(body), encoding='utf-8')
        self.assertFalse(policy.state()['granted'])
        time.sleep(0.02)
        policy.resume()
        self.assertTrue(policy.state()['granted'], 'resume did not clear the cached stop')


class ControlStatusTests(PolicyRobustnessCase):
    def test_control_status_exposes_policy_block(self):
        from computer_mcp.input_guard import KeyboardController, MouseController
        from computer_mcp.zones.dispatch import ComputerState, dispatch
        from computer_mcp import control

        original = control.status

        def idle():
            data = dict(original())
            data['owner'] = 'idle'
            return data

        with patch('computer_mcp.control.blocking_reason', return_value=None), \
                patch('computer_mcp.control.status', side_effect=idle):
            out = dispatch('control_status', {}, computer_state=ComputerState(),
                           mouse_controller=MouseController(),
                           keyboard_controller=KeyboardController())
        result = out.get('result') or {}
        self.assertEqual(result['policy'], dict(mode='local', runtime='ready'))
        self.assertIn('runtime_contract', result)

    def test_tool_effects_are_still_declared_for_audit(self):
        from computer_mcp import tool_registry
        spec = tool_registry.get('click')
        self.assertEqual(set(spec.effects), {'input'})
        self.assertTrue(spec.needs_authority({}))


if __name__ == '__main__':
    unittest.main()
