"""v1.3.2 单窗口授权的模型回归：身份租约、授权即交接、预设范围。"""
import json
import time
from pathlib import Path
import unittest
from unittest.mock import patch

from authority_fixture import AuthorityCase
from computer_mcp import agent_session, capabilities, control, native_dialog


class RegisteredAuthorityCase(AuthorityCase):
    def setUp(self):
        super().setUp()
        agent_session.register('isolated identity regression')


class IdentityTests(RegisteredAuthorityCase, unittest.TestCase):
    def test_identity_is_stable_and_32_hex(self):
        first = agent_session.identity()
        second = agent_session.identity()
        self.assertEqual(first, second)
        self.assertEqual(len(first), 32)
        int(first, 16)

    def test_identity_differs_from_session(self):
        self.assertNotEqual(agent_session.identity(), agent_session.current())


class LeaseValidationTests(RegisteredAuthorityCase, unittest.TestCase):
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

    def test_identity_lease_does_not_cover_another_session(self):
        spec = type('Spec', (), {'effects_for': lambda self, args: ('input',)})()
        state = dict(granted=True, authorization=self._auth(
            scopes=['input'], agent_id=agent_session.identity()))
        with patch.object(agent_session, 'current', return_value='c' * 48):
            self.assertIn('different Agent session', capabilities.check_scope(state, spec, {}))

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


class LeaseExpiryTests(RegisteredAuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def _signed_state(self, authorization):
        from computer_mcp import permission, security
        payload = dict(session='s', revision=1, granted=True, source='bridge',
                       authorization=authorization, checked_at='now',
                       checked_at_ts=time.time(), authorized_at=time.time() - 10,
                       expires_at=time.time() + 15)
        payload['signature'] = security.signature(payload, security.load_token())
        Path(permission.STATE_PATH).write_text(json.dumps(payload), encoding='utf-8')

    def test_expired_lease_is_rejected_even_if_the_file_is_fresh(self):
        from computer_mcp import permission
        auth = dict(agent_session=agent_session.current(), scopes=['screen_read'], applications=[],
                    agent_id=agent_session.identity(), lease_expires_at=time.time() - 5)
        self._signed_state(auth)
        with patch('computer_mcp.consent_ipc.live_valid', return_value=True):
            state = permission.status(force=True)
        self.assertFalse(state['granted'])
        self.assertIn('Lease expired', state.get('reason', ''))

    def test_live_lease_still_passes(self):
        from computer_mcp import permission
        auth = dict(agent_session=agent_session.current(), scopes=['screen_read'], applications=[],
                    agent_id=agent_session.identity(), lease_expires_at=time.time() + 600)
        self._signed_state(auth)
        with patch('computer_mcp.consent_ipc.live_valid', return_value=True):
            state = permission.status(force=True)
        self.assertTrue(state['granted'])


class AutoConsentTests(unittest.TestCase):
    """A blocked tool call should surface the approval window by itself."""

    def test_blocked_tool_requests_the_window_once(self):
        from computer_mcp import permission
        with patch.object(permission, "status", return_value=dict(granted=False, reason="no")), \
                patch("computer_mcp.consent_ipc.request", return_value={"opened": True, "request_id": "request-fixture"}) as request, \
                patch.object(permission, "_last_consent_request", {}), patch.object(permission, "caller_diagnostic", return_value={}):
            first = permission.check_tool("screenshot", {})
            second = permission.check_tool("screenshot", {})
        self.assertTrue(first and first.get("blocked"))
        self.assertTrue(second and second.get("blocked"))
        self.assertEqual(request.call_count, 1)

    def test_missing_scope_also_opens_the_window(self):
        from computer_mcp import permission
        state = dict(granted=True, authorization=dict(
            agent_session=agent_session.current(), scopes=["screen_read"], applications=[]))
        spec = type("Spec", (), {
            "effects_for": lambda self, args: ("input",),
            "needs_authority": lambda self, args: True})()
        with patch.object(permission, "status", return_value=state), \
                patch("computer_mcp.tool_registry.get", return_value=spec), \
                patch("computer_mcp.tool_registry.allowed", return_value=True), \
                patch("computer_mcp.consent_ipc.request", return_value={"request_id": "request-fixture"}) as request, \
                patch.object(permission, "_last_consent_request", {}), patch.object(permission, "caller_diagnostic", return_value={}):
            denial = permission.check_tool("click", {})
        self.assertIn("input", denial["error"])
        request.assert_called_once()


class PendingScopeTests(unittest.TestCase):
    """The window must pre-select a range that actually satisfies the call."""

    def test_common_preset_covers_ordinary_input(self):
        self.assertEqual(native_dialog.preset_for(['screen_read', 'input', 'text_entry']), 0)

    def test_read_only_preset_for_screen_only(self):
        self.assertEqual(native_dialog.preset_for(['screen_read']), 1)

    def test_clipboard_or_file_needs_the_full_preset(self):
        self.assertEqual(native_dialog.preset_for(['screen_read', 'file_write']), 2)
        self.assertEqual(native_dialog.preset_for(['clipboard_read']), 2)

    def test_empty_request_defaults_to_common(self):
        self.assertEqual(native_dialog.preset_for(None), 0)


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
