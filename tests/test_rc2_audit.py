"""Adversarial RC2 regressions; authority and files are test-local."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from authority_fixture import AuthorityCase
from computer_mcp import permission_bridge as bridge, permission, verify_flow
from computer_mcp.dataset import export as exporter, writer
from computer_mcp.dataset import schema
from computer_mcp import retention, panic_watch


class RevocationTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def test_lost_revoke_is_recovered_by_owner_negative_heartbeat(self):
        # Explicit revoke never reaches the server; only the next heartbeat does.
        bridge.write_state(False, client='fixture', event='hb')
        self.assertFalse(permission.status()['granted'])
        revision = bridge.read_state()['revision']
        bridge.write_state(True, client='fixture', event='hb')
        self.assertFalse(permission.status()['granted'])
        self.assertEqual(bridge.read_state()['revision'], revision)

    def test_unrelated_negative_heartbeat_cannot_revoke_owner(self):
        bridge.write_state(False, client='unrelated', event='hb')
        self.assertTrue(permission.status()['granted'])

    def test_reordered_old_grant_cannot_undo_negative_heartbeat(self):
        now = int(time.time() * 1000)
        with patch.multiple(bridge, _client_sequences={}, _last_event_stamp=0):
            bridge.write_state(True, client='fixture', event='action', sequence=1, action_at=now)
            bridge.write_state(False, client='fixture', event='hb', sequence=2, action_at=now+1)
            bridge.write_state(True, client='fixture', event='action', sequence=1, action_at=now)
            self.assertFalse(permission.status()['granted'])


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, ICON_CONTROL_HOME=str(self.root / 'home'))
        self.env.start(); self.addCleanup(self.env.stop)

    def test_report_cannot_write_user_file(self):
        victim = self.root / 'user.txt'
        victim.write_text('keep', encoding='utf-8')
        result = verify_flow.run([{'assert':[{'kind':'file','path':str(victim)}]}],
                                 report_path=str(victim))
        self.assertFalse(result['ok'])
        self.assertIn('report_error', result)
        self.assertEqual(victim.read_text(), 'keep')

    def test_report_traversal_and_existing_output_are_rejected(self):
        for name in ('../outside.json', '..\\outside.json', str(self.root / 'outside.json'), 'x:stream'):
            with self.subTest(name=name):
                self.assertIn('report_error', verify_flow.run([], report_path=name))
        result = verify_flow.run([], report_path='proof.json')
        self.assertIn('report_path', result)
        self.assertIn('report_error', verify_flow.run([], report_path='proof.json'))

    def test_export_tag_is_one_safe_component(self):
        with patch.object(writer, 'ROOT', self.root / 'dataset'):
            for tag in ('../escape','..\\escape',str(self.root / 'escape'),'x:stream','CON','a/b'):
                with self.subTest(tag=tag), self.assertRaises(ValueError):
                    exporter.export(tag=tag)

    def test_empty_verification_cannot_succeed(self):
        self.assertFalse(verify_flow.run([])['ok'])
        self.assertFalse(verify_flow.run([{'name':'empty'}])['ok'])

    def test_unknown_and_string_success_are_not_success(self):
        self.assertIsNone(schema.ok_of('{"success":"false"}'))
        self.assertIsNone(schema.ok_of('{"message":"done"}'))
        self.assertIs(schema.ok_of('{"ok":false}'),False)

    def test_training_never_records_input_or_exception_content(self):
        import json
        secret = 'ordinary words that are also a private password'
        episode = schema.build_episode(tool='type', zone='z1',
            arguments={'text':secret, 'steps':[{'value':secret, 'clipboard':secret}]},
            result_text=secret, ok=False, latency_ms=3, error=secret, labels=[secret])
        self.assertNotIn(secret, json.dumps(episode))

    def test_cleanup_cannot_touch_unrelated_global_temp_files(self):
        import time
        system_temp = self.root / 'other-temp'
        system_temp.mkdir()
        files = [system_temp / n for n in ('t_user.py','patch_customer.py','t_user.json')]
        for f in files:
            f.write_text('unrelated')
            os.utime(f,(1,1))
        owned = self.root / 'home' / 'tmp' / 'owned.tmp'
        owned.parent.mkdir(parents=True); owned.write_text('owned'); os.utime(owned,(1,1))
        with patch.object(retention,'DRAW_ROOT',self.root/'home'), \
             patch('tempfile.gettempdir',return_value=str(system_temp)), patch('computer_mcp.capabilities.has_scope',side_effect=lambda scope: scope=='file_delete'):
            retention.sweep_temp()
        self.assertTrue(all(f.exists() for f in files))
        self.assertFalse(owned.exists())

    def test_watchdog_does_not_enumerate_unregistered_python(self):
        with patch('psutil.process_iter',side_effect=AssertionError('broad scan')), \
             patch('computer_mcp.process_registry.registered',return_value=iter([])):
            self.assertEqual(panic_watch.automation_pids(), [])


if __name__ == '__main__':
    unittest.main()
