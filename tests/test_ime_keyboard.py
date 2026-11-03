"""IME regressions use packet sinks, never the user's keyboard or clipboard."""
import ctypes
import unittest
from unittest.mock import Mock, patch
from authority_fixture import AuthorityCase
from computer_mcp import input_guard as I, native_keyboard as N, permission
from computer_mcp.actions import keyboard


class UnicodeKeyboardTests(AuthorityCase,unittest.TestCase):
    fixture_authorized=True
    fixture_monitoring=True

    def test_utf16_units_include_surrogate_pairs(self):
        self.assertEqual(N.unicode_units('😀'),[0xd83d,0xde00])
        self.assertEqual(ctypes.sizeof(N.INPUT),40 if ctypes.sizeof(ctypes.c_void_p)==8 else 28)

    def test_all_ascii_chinese_and_symbols_use_unicode_packets(self):
        raw=object.__new__(I.InjectedKeyboard)
        with patch.object(N,'send_key') as sink:
            for char in 'IconControl-123 []{}@#%\\中文✓😀':
                key=I.UnicodeKey.from_char(char)
                I.InjectedKeyboard._handle(raw,key,True)
                I.InjectedKeyboard._handle(raw,key,False)
        for call in sink.call_args_list:
            self.assertNotIn('vk',call.kwargs)
            self.assertIn(call.kwargs['flags'],(N.UNICODE,N.UNICODE|N.KEYUP))

    def test_text_marker_survives_shift_resolution(self):
        raw=object.__new__(I.InjectedKeyboard)
        key=I.UnicodeKey.from_char('a')
        self.assertIs(raw._resolve(key),key)

    def test_zero_native_injection_is_an_error(self):
        dll=Mock()
        dll.SendInput.return_value=0
        with patch.object(ctypes,'WinDLL',return_value=dll):
            with self.assertRaises(OSError):N.send_key(scan=ord('A'),flags=N.UNICODE)

    def test_standard_edit_shortcut_does_not_type_a_letter(self):
        raw=object.__new__(I.InjectedKeyboard)
        raw._edit_keys=set()
        with patch.object(I.InjectedKeyboard,'ctrl_pressed',True),patch.object(I.InjectedKeyboard,'shift_pressed',False),patch.object(I.InjectedKeyboard,'alt_pressed',False),patch.object(N,'edit_shortcut',return_value=True) as edit,patch.object(N,'send_key') as send:
            key=I.KeyCode.from_char('a')
            raw._handle(key,True)
            raw._handle(key,False)
        edit.assert_called_once_with('a')
        send.assert_not_called()

    def test_declined_shortcut_uses_normal_key_events(self):
        raw=object.__new__(I.InjectedKeyboard)
        raw._edit_keys=set()
        with patch.object(I.InjectedKeyboard,'ctrl_pressed',True),patch.object(I.InjectedKeyboard,'shift_pressed',False),patch.object(I.InjectedKeyboard,'alt_pressed',False),patch.object(N,'edit_shortcut',return_value=False),patch.object(N,'send_key') as send:
            raw._handle(I.KeyCode.from_vk(0x41),True)
        self.assertEqual(send.call_args.kwargs['vk'],0x41)

    def test_count_and_failure_cleanup(self):
        raw=Mock()
        ctl=I.KeyboardController(raw)
        self.assertEqual(ctl.type('ABC'),3)
        raw.press.side_effect=OSError('native failed')
        with self.assertRaises(OSError):ctl.type('D')
        self.assertFalse(ctl.held)

    def test_result_describes_injection_without_claiming_app_verification(self):
        result=keyboard.type_text('abc',controller=I.KeyboardController(Mock()))
        self.assertEqual(result['injected_characters'],3)
        self.assertFalse(result['verified'])
        self.assertEqual(result['status'],'executed_unverified')

    def test_focus_change_blocks_shortcut_before_message(self):
        import win32gui,win32process
        dll=Mock()
        def info(thread, pointer):
            pointer._obj.hwndFocus=20
            return 1
        dll.GetGUIThreadInfo.side_effect=info
        with patch.object(ctypes,'WinDLL',return_value=dll),patch.object(win32gui,'GetForegroundWindow',side_effect=[10,11]),patch.object(win32process,'GetWindowThreadProcessId',return_value=(1,2)),patch.object(win32gui,'GetClassName',return_value='WindowsForms10.EDIT.app'),patch.object(win32gui,'GetAncestor',return_value=10):
            with self.assertRaises(permission.PermissionDenied):N.edit_shortcut('a')
        dll.SendMessageTimeoutW.assert_not_called()

    def test_unknown_control_uses_no_edit_messages(self):
        import win32gui,win32process
        dll=Mock()
        def info(thread,pointer):
            pointer._obj.hwndFocus=20
            return 1
        dll.GetGUIThreadInfo.side_effect=info
        with patch.object(ctypes,'WinDLL',return_value=dll),patch.object(win32gui,'GetForegroundWindow',return_value=10),patch.object(win32process,'GetWindowThreadProcessId',return_value=(1,2)),patch.object(win32gui,'GetClassName',return_value='Chrome_RenderWidgetHostHWND'):
            self.assertFalse(N.edit_shortcut('a'))
        dll.SendMessageTimeoutW.assert_not_called()

    def test_empty_text_reports_zero_and_invalid_surrogate_sends_nothing(self):
        raw=Mock()
        ctl=I.KeyboardController(raw)
        self.assertEqual(ctl.type(''),0)
        with self.assertRaises(UnicodeEncodeError):ctl.type('ok\ud800')
        raw.press.assert_not_called()
