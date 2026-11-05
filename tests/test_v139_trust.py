"""v1.3.9-beta: the 30-day trust record and the authority it mints.

The record is signed, subject-bound (workspace + tool fingerprint + host),
expiry-checked and beaten by revocation and the emergency stop. It never skips
the gate: permission.status() still runs on every call.
"""
import os
import sys
import time
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401

from authority_fixture import AuthorityCase
from computer_mcp import capabilities, permission, trust


class TrustRecordTests(AuthorityCase, unittest.TestCase):
    def test_grant_requires_a_user_confirmation(self):
        with self.assertRaises(PermissionError):
            trust.grant()
        with self.assertRaises(PermissionError):
            trust.grant(confirm=lambda: False)

    def test_valid_record_is_accepted(self):
        record = trust.grant(confirm=lambda: True)
        self.assertEqual(record['subject'], trust.subject_id())
        state = trust.validate()
        self.assertTrue(state['ok'])
        self.assertEqual(state['reason'], 'trusted')
        self.assertGreater(state['days_left'], 29)

    def test_expired_record_is_rejected(self):
        trust.grant(confirm=lambda: True)
        later = time.time() + 31 * 86400
        state = trust.validate(now=later)
        self.assertFalse(state['ok'])
        self.assertEqual(state['reason'], 'trust expired')

    def test_revocation_wins(self):
        trust.grant(confirm=lambda: True)
        record = trust.revoke()
        self.assertEqual(record['revocation_generation'], 1)
        state = trust.validate()
        self.assertFalse(state['ok'])
        self.assertEqual(state['reason'], 'revoked')

    def test_subject_change_invalidates_the_record(self):
        trust.grant(confirm=lambda: True)
        with patch.object(trust, 'subject_id', return_value='f' * 32):
            state = trust.validate()
        self.assertFalse(state['ok'])
        self.assertIn('subject changed', state['reason'])

    def test_tampered_record_is_rejected(self):
        trust.grant(confirm=lambda: True)
        path = trust.path()
        payload = path.read_text(encoding='utf-8').replace('"days": 30', '"days": 3000')
        path.write_text(payload, encoding='utf-8')
        self.assertIsNone(trust.load())
        self.assertFalse(trust.validate()['ok'])

    def test_emergency_stop_after_grant_blocks_trust(self):
        trust.grant(confirm=lambda: True)
        stop = trust.path().parent / 'emergency-stop.json'
        stop.write_text('{"stopped_at": %f}' % (time.time() + 1), encoding='utf-8')
        state = trust.validate()
        self.assertFalse(state['ok'])
        self.assertIn('emergency stop', state['reason'])

    def test_stop_before_grant_does_not_block(self):
        stop = trust.path().parent
        stop.mkdir(parents=True, exist_ok=True)
        (stop / 'emergency-stop.json').write_text('{"stopped_at": 1.0}', encoding='utf-8')
        trust.grant(confirm=lambda: True)
        self.assertTrue(trust.validate()['ok'])


class TrustAuthorityTests(AuthorityCase, unittest.TestCase):
    def test_status_uses_trust_when_no_bridge_grant_exists(self):
        trust.grant(confirm=lambda: True)
        state = permission.status(force=True)
        self.assertTrue(state['granted'])
        self.assertEqual(state['source'], 'trust')
        auth = state['authorization']
        self.assertEqual(auth['applications'], ['*'])
        self.assertEqual(auth['agent_id'], trust.subject_id())
        self.assertTrue(capabilities.validate(auth))
        self.assertNotIn('code', state)

    def test_status_stays_denied_without_trust(self):
        state = permission.status(force=True)
        self.assertFalse(state['granted'])
        self.assertEqual(state['code'], 'authority_unavailable')

    def test_revoked_trust_is_denied_again(self):
        trust.grant(confirm=lambda: True)
        trust.revoke()
        state = permission.status(force=True)
        self.assertFalse(state['granted'])
        self.assertNotEqual(state.get('source'), 'trust')

    def test_scope_check_passes_for_a_trusted_authorization(self):
        trust.grant(confirm=lambda: True)
        auth = trust.authorization()
        self.assertIsNotNone(auth)
        state = {'granted': True, 'authorization': auth}
        spec = type('Spec', (), {'effects_for': lambda self, args: ('input',),
                                 'name': 'click', 'reads': ('screen_read',)})()
        why = capabilities.check_scope(state, spec, {})
        self.assertIsNone(why, f'unexpected denial: {why} (auth={sorted(auth)})')


class TrustCliTests(AuthorityCase, unittest.TestCase):
    def test_grant_requires_the_native_prompt_to_accept(self):
        with patch('computer_mcp.native_dialog.ask_trust', return_value=False):
            code = trust.main(['grant'])
        self.assertEqual(code, 1)
        self.assertFalse(trust.validate()['ok'])

    def test_grant_writes_the_record_after_the_user_accepts(self):
        with patch('computer_mcp.native_dialog.ask_trust', return_value=True) as prompt:
            code = trust.main(['grant', '--days', '7'])
        self.assertEqual(code, 0)
        prompt.assert_called_once()
        self.assertTrue(trust.validate()['ok'])
        self.assertEqual(trust.load()['days'], 7)

    def test_days_out_of_range_is_rejected_before_the_prompt(self):
        with patch('computer_mcp.native_dialog.ask_trust') as prompt:
            self.assertEqual(trust.main(['grant', '--days', '0']), 2)
            self.assertEqual(trust.main(['grant', '--days', '999']), 2)
        prompt.assert_not_called()

    def test_revoke_command_clears_trust(self):
        trust.grant(confirm=lambda: True)
        self.assertEqual(trust.main(['revoke']), 0)
        self.assertEqual(trust.validate()['reason'], 'revoked')

    def test_status_command_reports_state(self):
        self.assertEqual(trust.main(['status']), 3)     # nothing trusted yet
        trust.grant(confirm=lambda: True)
        self.assertEqual(trust.main(['status']), 0)


class WildcardTargetTests(unittest.TestCase):
    """A trusted install covers any ordinary app, never the permission UI."""

    def _call(self, applications, command=None):
        command = command or ['notepad.exe']
        process = type('P', (), {'cmdline': lambda self: command})()
        fake_psutil = types.SimpleNamespace(
            Process=staticmethod(lambda pid: process), Error=OSError)
        gui = types.ModuleType('win32gui')
        gui.GetForegroundWindow = lambda: 1
        gui.WindowFromPoint = lambda point: 1
        gui.GetWindowText = lambda hwnd: 'Notepad'
        gui.GetAncestor = lambda hwnd, flag: 1
        proc = types.ModuleType('win32process')
        proc.GetWindowThreadProcessId = lambda hwnd: (0, 1234)
        state = {'authorization': {'applications': applications}}
        with patch.dict(sys.modules, {'win32gui': gui, 'win32process': proc}), \
                patch.object(capabilities, 'psutil', fake_psutil), \
                patch.object(capabilities, 'process_record',
                             lambda pid: {'pid': pid, 'created': 1.0, 'exe': 'notepad.exe'}):
            return capabilities.check_target(state)

    def test_wildcard_allows_an_unlisted_app(self):
        self.assertIsNone(self._call(['*']))

    def test_explicit_list_still_blocks_unknown_apps(self):
        self.assertIn('outside', self._call([]))

    def test_permission_ui_is_never_a_target(self):
        reason = self._call(['*'], command=['pythonw.exe', '-m', 'computer_mcp.consent'])
        self.assertIn('cannot be automated', reason)


if __name__ == '__main__':
    unittest.main()
