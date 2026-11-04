"""Desktop feedback regressions. All actuators and page observations are fake."""
import unittest
from unittest.mock import Mock, patch
from authority_fixture import AuthorityCase
from computer_mcp import native_dialog, native_keyboard, input_guard, macro_ext, permission, verify_flow, runtime_contract
from computer_mcp.actions import keyboard, mouse
from computer_mcp.text_integrity import fingerprint


class TextIntegrityTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True
    fixture_monitoring = True

    def test_quotes_and_mixed_text_generate_exact_unicode_units(self):
        text = '中文 "quotes" “弯引号” \'single\'\n😀'
        raw = object.__new__(input_guard.InjectedKeyboard)
        expected = []
        for char in text:
            for pressed in (True, False):
                for unit in native_keyboard.unicode_units(char):
                    expected.append((unit, native_keyboard.UNICODE | (0 if pressed else native_keyboard.KEYUP)))
        with patch.object(native_keyboard, 'send_key') as sink:
            for char in text:
                key = input_guard.UnicodeKey.from_char(char)
                raw._handle(key, True)
                raw._handle(key, False)
        self.assertEqual([(c.kwargs['scan'], c.kwargs['flags']) for c in sink.call_args_list], expected)
        self.assertEqual(sum(c.kwargs['scan'] == 34 for c in sink.call_args_list), 4)

    def test_type_returns_argument_fingerprint_without_claiming_draft_matches(self):
        text = '中文 "exact" 😀'
        result = keyboard.type_text(text, controller=input_guard.KeyboardController(Mock()))
        self.assertEqual(result['text_integrity'], fingerprint(text))
        self.assertEqual(result['text_integrity']['ascii_double_quotes'], 2)
        self.assertFalse(result['verified'])
        self.assertEqual(result['verification_method'], 'not_performed')
        self.assertIn('before', result['next_action'])


class ScrollBoundaryTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True
    fixture_monitoring = True

    def test_target_change_blocks_wheel_events(self):
        raw = Mock(position=(10, 20))
        controller = input_guard.MouseController(raw)
        target = dict(pid=11, created=1, exe='fixture.exe')
        with patch('win32gui.GetAncestor', return_value=123), patch('win32gui.WindowFromPoint', return_value=123), patch('win32process.GetWindowThreadProcessId', return_value=(1, 11)), patch('computer_mcp.capabilities.process_record', side_effect=[target, dict(target, created=2)]):
            with self.assertRaises(permission.PermissionDenied):
                mouse.scroll(dy=-3, controller=controller)
        raw.scroll.assert_not_called()

    def test_invalid_scroll_is_rejected_before_moving(self):
        controller = Mock()
        for delta in (True, 101, -101, 1.5):
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                mouse.scroll(dy=delta, controller=controller)
        controller.scroll.assert_not_called()


class PageTransitionTests(unittest.TestCase):
    def step(self):
        return dict(action='guarded_click', rel=[10, 20],
                    before=[dict(kind='text', query='main')],
                    after=[dict(kind='text', query='moments')])

    def window(self):
        return dict(hwnd=123, x=0, y=0, w=100, h=100, rect_x=0, rect_y=0, rect_w=100, rect_h=100)

    def test_missing_page_precondition_never_clicks(self):
        with patch('win32gui.GetAncestor', return_value=123), patch('win32process.GetWindowThreadProcessId', return_value=(1, 11)), patch('computer_mcp.capabilities.process_record', return_value={'pid':11}), patch.object(verify_flow, 'run', return_value={'ok':False}), patch.object(mouse, 'click') as click:
            result = macro_ext._guarded_click(self.step(), self.window(), Mock())
        self.assertFalse(result['ok'])
        self.assertFalse(result['clicked'])
        click.assert_not_called()

    def test_failed_postcondition_reports_failure_after_one_click(self):
        with patch('win32gui.GetAncestor', return_value=123), patch('win32gui.WindowFromPoint', return_value=123), patch('win32process.GetWindowThreadProcessId', return_value=(1, 11)), patch('computer_mcp.capabilities.process_record', return_value={'pid':11}), patch.object(verify_flow, 'run', side_effect=[{'ok':True}, {'ok':False}]), patch.object(macro_ext, '_execution') as execution, patch.object(mouse, 'click') as click:
            result = macro_ext._guarded_click(self.step(), self.window(), Mock())
        self.assertFalse(result['ok'])
        self.assertTrue(result['clicked'])
        click.assert_called_once()

    def test_ocr_failure_cannot_prove_text_absent(self):
        with patch('computer_mcp.ocr_ext.ocr_read', return_value={'error':'unavailable'}):
            result = verify_flow._check_text({'query':'视频号', 'absent':True})
        self.assertFalse(result['ok'])


class ApplicationChoiceTests(unittest.TestCase):
    def test_single_application_requires_explicit_selection(self):
        apps = [dict(pid=1, exe='fixture.exe', title='fixture')]
        with patch.object(native_dialog, '_choose_record', return_value=None) as choose:
            self.assertIsNone(native_dialog.choose_application(apps))
        self.assertFalse(choose.call_args.kwargs['auto_single'])

    def test_manifest_exposes_coordinate_schema_and_scroll(self):
        contract = runtime_contract.describe()
        self.assertIn('x', contract['click_input_schema']['properties'])
        self.assertIn('y', contract['click_input_schema']['properties'])
        self.assertEqual(len(contract['tools_sha256']), 64)
