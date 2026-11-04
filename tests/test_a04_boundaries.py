"""Fourth-audit regressions: definitions only, fake input and isolated policy."""
import unittest
from unittest.mock import Mock, patch
from pynput.keyboard import Key, KeyCode
from computer_mcp import input_guard, native_keyboard, permission, tool_registry, verify_flow


class ReleaseBoundaryTests(unittest.TestCase):
    def test_unheld_key_up_rechecks_message_target(self):
        raw = Mock(hwnd=4321)
        controller = input_guard.KeyboardController(raw)
        with patch.object(input_guard, 'check'), patch('computer_mcp.capabilities.require_target', side_effect=permission.PermissionDenied('wrong app')) as target:
            with self.assertRaises(permission.PermissionDenied):
                controller.release('x')
        target.assert_called_once_with(hwnd=4321)
        raw.release.assert_not_called()

    def test_normal_held_release_is_not_an_emergency_bypass(self):
        raw = Mock(hwnd=4321)
        controller = input_guard.KeyboardController(raw)
        controller.held.add('x')
        with patch.object(input_guard, 'check', side_effect=permission.PermissionDenied('revoked')):
            with self.assertRaises(permission.PermissionDenied):
                controller.release('x')
        raw.release.assert_not_called()
        controller.cleanup()
        raw.release.assert_called_once_with('x')
        self.assertFalse(controller.held)

    def test_emergency_cleanup_never_sends_to_reused_window(self):
        raw = Mock(hwnd=4321)
        raw.target_exists.return_value = False
        controller = input_guard.KeyboardController(raw)
        controller.held.add('x')
        controller.cleanup()
        raw.release.assert_not_called()
        self.assertFalse(controller.held)


class ClipboardChordTests(unittest.TestCase):
    def test_standard_and_alternative_clipboard_chords(self):
        cases = [(KeyCode.from_char('c'), {Key.ctrl}, {'clipboard_write'}),
                 (KeyCode.from_char('x'), {Key.ctrl_l}, {'clipboard_write'}),
                 (KeyCode.from_char('v'), {Key.ctrl_r}, {'clipboard_read'}),
                 (Key.insert, {Key.ctrl}, {'clipboard_write'}),
                 (Key.insert, {Key.shift}, {'clipboard_read'}),
                 (Key.delete, {Key.shift_l}, {'clipboard_write'})]
        for key, modifiers, expected in cases:
            with self.subTest(key=key, modifiers=modifiers), patch.object(native_keyboard, 'require_clipboard_scopes') as require:
                native_keyboard.check_clipboard_chord(key, modifiers)
                require.assert_called_once_with(expected)

    def test_plain_text_and_select_all_do_not_require_clipboard(self):
        with patch.object(native_keyboard, 'require_clipboard_scopes') as require:
            native_keyboard.check_clipboard_chord(KeyCode.from_char('v'), set())
            native_keyboard.check_clipboard_chord(KeyCode.from_char('a'), {Key.ctrl})
        require.assert_not_called()

    def test_chord_denial_precedes_raw_key_injection(self):
        raw = Mock(ctrl_pressed=False, shift_pressed=False, alt_pressed=False)
        controller = input_guard.KeyboardController(raw)
        controller.held.add(Key.ctrl)
        try:
            with patch.object(input_guard, 'check'), patch.object(native_keyboard, 'require_clipboard_scopes', side_effect=permission.PermissionDenied('clipboard read')):
                with self.assertRaises(permission.PermissionDenied):
                    controller.press(KeyCode.from_char('v'))
            raw.press.assert_not_called()
        finally:
            controller.cleanup()


class VerificationPreflightTests(unittest.TestCase):
    def test_permissions_follow_the_entire_plan_and_optional_report(self):
        spec = tool_registry.get('verify_flow')
        self.assertEqual(set(spec.effects_for({'stages': [{'assert': [{'kind': 'text'}]}]})), {'screen_read'})
        self.assertEqual(set(spec.effects_for({'stages': [{'checks': [{'kind': 'file'}]}]})), {'file_read'})
        plan = {'stages': [{'assert': [{'kind': 'stable'}]}, {'assert': [{'kind': 'file'}]}], 'report_path': 'proof.json'}
        self.assertEqual(set(spec.effects_for(plan)), {'screen_read', 'file_read', 'file_write'})

    def test_missing_plan_permission_blocks_before_first_check(self):
        stages = [{'assert': [{'kind': 'text', 'query': 'fixture'}]}]
        with patch('computer_mcp.execution.check', side_effect=permission.PermissionDenied('screen_read')), patch.dict(verify_flow.KINDS, text=Mock()) as kinds:
            with self.assertRaises(permission.PermissionDenied):
                verify_flow.run(stages)
            kinds['text'].assert_not_called()
