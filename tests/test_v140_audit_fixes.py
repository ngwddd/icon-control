"""Regression tests for the v1.4.0rc1 audit: stops must survive, saves must fail loudly."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from computer_mcp import policy, security


class AuditCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        (self.home / 'state').mkdir()
        self.env = patch.dict(os.environ, ICON_CONTROL_HOME=str(self.home),
                              ICON_CONTROL_POLICY='local')
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.temp.cleanup)
        policy._FACTS.update(signature=None, value=None)
        security.provision_token()

    def stop(self, when=None):
        import time
        body = dict(stopped_at=time.time() if when is None else when)
        body['signature'] = security.signature(body, security.load_token())
        (self.home / 'state' / 'emergency-stop.json').write_text(json.dumps(body), encoding='utf-8')
        policy._FACTS.update(signature=None, value=None)

    def record_path(self):
        return policy.record_path()


class StopSurvivalTests(AuditCase):
    def test_deleting_the_record_does_not_cancel_a_stop(self):
        policy.resume()
        self.stop()
        self.assertFalse(policy.state()['granted'])
        self.record_path().unlink()
        policy._FACTS.update(signature=None, value=None)
        self.assertFalse(policy.state()['granted'], 'deleting the record revived the agent')
        self.assertFalse(self.record_path().exists(), 'authority was invented across a stop')

    def test_corrupting_the_record_does_not_cancel_a_stop(self):
        policy.resume()
        self.stop()
        self.record_path().write_text('{broken', encoding='utf-8')
        policy._FACTS.update(signature=None, value=None)
        self.assertFalse(policy.state()['granted'])

    def test_a_fresh_install_without_a_stop_still_works(self):
        self.assertFalse(self.record_path().exists())
        self.assertTrue(policy.state()['granted'])
        self.assertTrue(self.record_path().exists())

    def test_status_reports_stopped_runtime(self):
        policy.resume()
        self.stop()
        self.assertEqual(policy.runtime_state(), 'stopped')


class ResumeIsExplicitTests(AuditCase):
    def test_resume_is_the_only_way_back(self):
        policy.resume()
        self.stop()
        self.assertFalse(policy.state()['granted'])
        policy.resume()
        self.assertTrue(policy.state()['granted'])

    def test_ensure_initialised_never_clears_a_stop(self):
        self.stop()
        self.assertIsNone(policy.ensure_initialised())
        self.assertFalse(policy.state()['granted'])

    def test_ensure_initialised_leaves_an_existing_record_alone(self):
        policy.resume()
        before = json.loads(self.record_path().read_text(encoding='utf-8'))
        self.assertIsNone(policy.ensure_initialised())
        after = json.loads(self.record_path().read_text(encoding='utf-8'))
        self.assertEqual(before['authorized_at'], after['authorized_at'])


class SaveFailureTests(AuditCase):
    def test_save_raises_instead_of_pretending(self):
        with patch('computer_mcp.policy.os.replace', side_effect=PermissionError('locked')):
            with self.assertRaises(OSError):
                policy._save(dict(authorized_at=1))

    def test_resume_propagates_a_write_failure(self):
        with patch('computer_mcp.policy.os.replace', side_effect=PermissionError('locked')):
            with self.assertRaises(OSError):
                policy.resume()


class DisableTests(AuditCase):
    def test_disable_switches_the_effective_mode(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('ICON_CONTROL_POLICY', None)
            policy.main(['disable'])
            self.assertEqual(policy.mode(), 'human')
            self.assertFalse(policy.is_local())
            from computer_mcp import permission
            self.assertFalse(permission.status()['granted'])

    def test_enable_switches_back(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('ICON_CONTROL_POLICY', None)
            policy.main(['disable'])
            self.assertEqual(policy.mode(), 'human')
            policy.main(['enable'])
            self.assertEqual(policy.mode(), 'local')


class SessionIsolationTests(AuditCase):
    def test_each_caller_gets_its_own_session_in_the_state(self):
        policy.resume()
        for token in ('a' * 48, 'b' * 48):
            with patch('computer_mcp.policy.agent_session.current', return_value=token):
                state = policy.state()
            self.assertEqual(state['authorization']['agent_session'], token)
            self.assertEqual(state['session'], token)

    def test_cached_facts_do_not_carry_a_session(self):
        policy.resume()
        with patch('computer_mcp.policy.agent_session.current', return_value='c' * 48):
            first = policy.state()
        with patch('computer_mcp.policy.agent_session.current', return_value='d' * 48):
            second = policy.state()
        self.assertEqual(first['authorization']['agent_session'], 'c' * 48)
        self.assertEqual(second['authorization']['agent_session'], 'd' * 48)


class ForcedExitTests(AuditCase):
    def test_forced_exit_accepts_the_wildcard_application_set(self):
        from computer_mcp import appkit
        def pids(*_args, **_kwargs):
            return [4321]

        with patch.object(appkit, '_pids_matching', side_effect=pids), \
                patch('computer_mcp.capabilities.process_record', return_value=dict(pid=4321)), \
                patch('computer_mcp.permission.status',
                      return_value=dict(granted=True, authorization=dict(applications=['*']))), \
                patch('computer_mcp.permission.require'), \
                patch('computer_mcp.execution.checkpoint'), \
                patch('computer_mcp.execution.sleep'), \
                patch('psutil.Process') as proc:
            proc.return_value.create_time.return_value = 1.0
            result = appkit.exit_app('probe', force=True, timeout_ms=0)
        self.assertTrue(proc.return_value.terminate.called,
                        'forced exit skipped a process the wildcard allows')
        self.assertGreaterEqual(result.get('terminated', 0), 1)


class SecondRoundAuditTests(AuditCase):
    """rc2 audit round two: authority must never be granted as a side effect."""

    def test_enable_does_not_clear_a_stop(self):
        policy.resume()
        self.stop()
        self.assertFalse(policy.state()['granted'])
        policy.main(['enable'])
        self.assertFalse(policy.state()['granted'], 'enable cancelled the emergency stop')

    def test_resume_refuses_when_a_new_stop_lands_midway(self):
        import time
        policy.resume()
        real_save = policy._save

        def save_then_new_stop(payload):
            saved = real_save(payload)
            body = dict(stopped_at=time.time() + 1)
            body['signature'] = security.signature(body, security.load_token())
            (self.home / 'state' / 'emergency-stop.json').write_text(json.dumps(body), encoding='utf-8')
            return saved

        with patch.object(policy, '_save', side_effect=save_then_new_stop):
            with self.assertRaises(RuntimeError):
                policy.resume()
        policy._FACTS.update(signature=None, value=None)
        self.assertFalse(policy.state()['granted'], 'the new stop was swallowed')

    def test_non_finite_authorised_time_is_not_authority(self):
        self.stop()
        for bad in ('inf', '-inf', 'nan'):
            (self.home / 'state' / 'local-policy.json').write_text(
                '{"authorized_at": ' + bad + ', "mode": "local"}', encoding='utf-8')
            policy._FACTS.update(signature=None, value=None)
            self.assertFalse(policy.state()['granted'], f'{bad} was accepted as authority')

    def test_future_authorised_time_is_rejected(self):
        import time
        (self.home / 'state' / 'local-policy.json').write_text(
            json.dumps({'authorized_at': time.time() + 86400, 'mode': 'local'}), encoding='utf-8')
        policy._FACTS.update(signature=None, value=None)
        self.assertFalse(policy.state()['granted'])

    def test_disable_reports_that_an_env_override_wins(self):
        with patch.dict(os.environ, {'ICON_CONTROL_POLICY': 'local'}):
            code = policy.main(['disable'])
            self.assertEqual(code, 3)
            self.assertEqual(policy.mode(), 'local')


class TakeoverTests(AuditCase):
    def test_takeover_is_not_yielded_by_a_timestamp_in_headless(self):
        from computer_mcp import control
        policy.resume()
        with patch.object(control, 'ensure_watcher', return_value=True), \
                patch.object(control, 'status',
                             return_value=dict(owner='user', enabled=True, idle_s=0.0,
                                               idle_resume_s=10.0)), \
                patch('computer_mcp.permission.status',
                      return_value=dict(granted=True, authorized_at=9e9)):
            reason = control.blocking_reason()
        self.assertIsNotNone(reason, 'a timestamp must not steal control back from the user')


class ProcessScopeTests(AuditCase):
    def test_forced_exit_is_opt_in(self):
        import inspect
        from computer_mcp import appkit
        signature = inspect.signature(appkit.exit_app)
        self.assertIs(signature.parameters['force'].default, False)

    def test_process_match_is_exact(self):
        from computer_mcp import appkit
        info = {111: ('python.exe', r'C:\x\python.exe'), 222: ('python3.exe', r'C:\x\python3.exe')}
        with patch.object(appkit, '_pid_info', return_value=info):
            self.assertEqual(appkit._pids_matching('python.exe', None), {111})
            self.assertEqual(appkit._pids_matching('python', None), set())


if __name__ == '__main__':
    unittest.main()
