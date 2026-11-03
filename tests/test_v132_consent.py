"""v1.3.2 单窗口授权的模型回归：身份租约、授权即交接、预设范围。"""
import json
import time
import unittest
from unittest.mock import patch

from authority_fixture import AuthorityCase
from computer_mcp import agent_session, capabilities, control, native_dialog


class IdentityTests(unittest.TestCase):
    def test_identity_is_stable_and_32_hex(self):
        first = agent_session.identity()
        second = agent_session.identity()
        self.assertEqual(first, second)
        self.assertEqual(len(first), 32)
        int(first, 16)

    def test_identity_differs_from_session(self):
        self.assertNotEqual(agent_session.identity(), agent_session.current())


class LeaseValidationTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def _auth(self, **extra):
        base = dict(agent_session='a' * 48, scopes=['screen_read'], applications=[])
        base.update(extra)
        return base

    def test_session_only_approval_is_still_valid(self):
        self.assertTrue(capabilities.validate(self._auth()))

    def test_identity_lease_is_valid(self):
        self.assertTrue(capabilities.validate(self._auth(agent_id='b' * 32,
                                                        lease_expires_at=time.time() + 60)))

    def test_malformed_identity_is_rejected(self):
        self.assertFalse(capabilities.validate(self._auth(agent_id='too-short')))

    def test_lease_covers_another_session_of_the_same_identity(self):
        spec = type('Spec', (), {'effects_for': lambda self, args: ('input',)})()
        state = dict(granted=True, authorization=self._auth(
            scopes=['input'], agent_id=agent_session.identity()))
        with patch.object(agent_session, 'current', return_value='c' * 48):
            self.assertIsNone(capabilities.check_scope(state, spec, {}))

    def test_foreign_session_is_still_rejected_without_identity(self):
        spec = type('Spec', (), {'effects_for': lambda self, args: ('input',)})()
        state = dict(granted=True, authorization=self._auth(scopes=['input']))
        with patch.object(agent_session, 'current', return_value='c' * 48):
            self.assertIn('different Agent session', capabilities.check_scope(state, spec, {}))


class HandoverTests(unittest.TestCase):
    """A fresh approval must outrank the click that made it."""

    def setUp(self):
        self._saved = dict(control.STATE)
        self.addCleanup(lambda: (control.STATE.clear(), control.STATE.update(self._saved)))
        control.STATE.update(owner='user', last_user=time.time(), takeovers=1,
                             since=time.time(), reason='user')

    def test_approval_never_than_last_input_hands_control_back(self):
        approved = time.time() + 1
        with patch.object(control, 'ensure_watcher', return_value=True), \
                patch('computer_mcp.permission.status', return_value=dict(granted=True, authorized_at=approved)):
            self.assertIsNone(control.blocking_reason())
        self.assertEqual(control.STATE['owner'], 'ai')

    def test_old_approval_still_yields_to_the_user(self):
        with patch.object(control, 'ensure_watcher', return_value=True), \
                patch('computer_mcp.permission.status', return_value=dict(granted=True, authorized_at=1.0)):
            self.assertIn('用户已接管控制权', control.blocking_reason())
        self.assertEqual(control.STATE['owner'], 'user')


class PresetTests(unittest.TestCase):
    def test_three_presets_are_declared_with_valid_scopes(self):
        self.assertEqual(len(native_dialog.PRESETS), 3)
        for name, detail, scopes in native_dialog.PRESETS:
            self.assertTrue(name and detail)
            self.assertTrue(set(scopes) <= capabilities.SCOPES)
        self.assertEqual(native_dialog.PRESETS[0][2], ('screen_read', 'input', 'text_entry'))

    def test_common_preset_has_no_clipboard_or_file_access(self):
        scopes = native_dialog.PRESETS[0][2]
        self.assertNotIn('clipboard_read', scopes)
        self.assertNotIn('file_write', scopes)
        self.assertNotIn('process', scopes)


class TrayHostTests(unittest.TestCase):
    """The window procedure must resolve every message constant it compares."""

    def test_hotkey_and_show_messages_open_the_dialog(self):
        from computer_mcp import native_consent as nc
        host = nc.ConsentHost('nonce')
        shown = []
        host.show = lambda: shown.append(True)
        host._on_message(0, nc.WM_HOTKEY, 1, 0)
        host._on_message(0, nc.WM_SHOW, 0, 0)
        self.assertEqual(len(shown), 2)

    def test_hotkey_chain_has_fallbacks(self):
        from computer_mcp import native_consent as nc
        self.assertGreaterEqual(len(nc.HOTKEYS), 2)
        first = nc.HOTKEYS[0]
        self.assertIn('F9', first[0])
        self.assertEqual(first[1], nc.MOD_CONTROL | nc.MOD_ALT | nc.MOD_SHIFT)


if __name__ == '__main__':
    unittest.main()
