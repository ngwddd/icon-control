"""v1.4.2: hold-key, batch key_down/up, focus reporting, bounds fallback, frame_id."""
import unittest
from unittest.mock import Mock, patch

from authority_fixture import AuthorityCase
from computer_mcp import control
from computer_mcp.core import screenshot as capture_core
from computer_mcp.core.response import format_response
from computer_mcp.input_guard import KeyboardController, MouseController
from computer_mcp.zones.dispatch import ComputerState, dispatch


def call(tool, **arguments):
    return dispatch(tool, dict(arguments), computer_state=ComputerState(),
                    mouse_controller=MouseController(),
                    keyboard_controller=KeyboardController()).get("result") or {}


class HoldKeyTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def setUp(self):
        super().setUp()
        guard = patch('computer_mcp.control.blocking_reason', return_value=None)
        guard.start()
        self.addCleanup(guard.stop)

    def test_hold_ms_presses_waits_and_releases(self):
        events = []
        with patch('computer_mcp.actions.keyboard.key_down',
                   side_effect=lambda key, controller=None: events.append(('down', key)) or dict(success=True)), \
                patch('computer_mcp.actions.keyboard.key_up',
                      side_effect=lambda key, controller=None: events.append(('up', key)) or dict(success=True)), \
                patch('computer_mcp.execution.sleep') as sleep:
            result = call('key_press', key='w', hold_ms=250)
        self.assertEqual(events, [('down', 'w'), ('up', 'w')])
        sleep.assert_called_once()
        self.assertAlmostEqual(sleep.call_args[0][0], 0.25, places=3)
        self.assertEqual(result.get('held_ms'), 250)
        self.assertFalse(result.get('capped'))

    def test_hold_is_capped_and_reported(self):
        events = []
        with patch('computer_mcp.actions.keyboard.key_down',
                   side_effect=lambda key, controller=None: events.append(('down', key)) or dict(success=True)), \
                patch('computer_mcp.actions.keyboard.key_up',
                      side_effect=lambda key, controller=None: events.append(('up', key)) or dict(success=True)), \
                patch('computer_mcp.execution.sleep') as sleep:
            result = call('key_press', key='w', hold_ms=60000)
        self.assertTrue(result.get('capped'))
        self.assertEqual(result.get('held_ms'), 10000.0)
        self.assertAlmostEqual(sleep.call_args[0][0], 10.0, places=3)

    def test_hold_accepts_a_chord(self):
        events = []
        with patch('computer_mcp.actions.keyboard.key_down',
                   side_effect=lambda key, controller=None: events.append(('down', key)) or dict(success=True)), \
                patch('computer_mcp.actions.keyboard.key_up',
                      side_effect=lambda key, controller=None: events.append(('up', key)) or dict(success=True)), \
                patch('computer_mcp.execution.sleep'):
            result = call('key_press', key='ctrl+w', hold_ms=120)
        self.assertEqual(events, [('down', 'ctrl'), ('down', 'w'), ('up', 'w'), ('up', 'ctrl')])
        self.assertTrue(result.get('chord'))

    def test_tap_without_hold_stays_a_tap(self):
        with patch('computer_mcp.actions.keyboard.key_press',
                   return_value=dict(success=True)) as press, \
                patch('computer_mcp.actions.keyboard.key_down') as down:
            call('key_press', key='esc')
        press.assert_called_once()
        down.assert_not_called()


class BatchKeyTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def run_batch(self, steps, fail_release=False):
        keyboard = Mock()
        release_calls = []

        def release(key):
            release_calls.append(key)
            if fail_release:
                raise RuntimeError('release failed')
        keyboard.release.side_effect = release
        from computer_mcp import ui_ext
        with patch.object(ui_ext, '_click', lambda *args, **kwargs: None), \
                patch('computer_mcp.execution.sleep'):
            result = ui_ext.run_batch(steps, Mock(), keyboard, default_sleep_ms=0)
        return result, keyboard

    def test_batch_can_hold_and_release_a_key(self):
        result, keyboard = self.run_batch([
            dict(action='key_down', key='w'),
            dict(action='sleep', ms=200),
            dict(action='key_up', key='w'),
        ])
        self.assertTrue(result['ok'])
        keyboard.press.assert_called_once()
        self.assertEqual(result['released_keys'], [])

    def test_held_key_is_released_when_a_later_step_fails(self):
        result, keyboard = self.run_batch([
            dict(action='key_down', key='ctrl'),
            dict(action='ui_click', name='missing', hwnd=1),
        ])
        self.assertFalse(result['ok'])
        self.assertEqual(result['released_keys'], ['ctrl'])

    def test_key_action_supports_hold_ms(self):
        result, keyboard = self.run_batch([dict(action='key', key='w', hold_ms=300)])
        self.assertTrue(result['ok'])
        self.assertEqual(result['log'][0].get('held_ms'), 300)


class FocusSnapshotTests(unittest.TestCase):
    def test_snapshot_falls_back_to_the_foreground_window(self):
        """Custom renderers report no thread focus; the foreground is still useful."""
        with patch('win32gui.GetForegroundWindow', return_value=111), \
                patch('win32gui.GetWindowText', return_value='Game'), \
                patch('win32process.GetWindowThreadProcessId', return_value=(9, 4242)), \
                patch('win32gui.GetClassName', return_value='GameWindow'), \
                patch('psutil.Process') as process, \
                patch('ctypes.windll.user32.GetGUIThreadInfo', return_value=0), \
                patch('computer_mcp.ui_ext._UIA_OK', False):
            process.return_value.name.return_value = 'game.exe'
            snapshot = control._focus_snapshot()
        self.assertEqual(snapshot['foreground_hwnd'], 111)
        self.assertEqual(snapshot['foreground_title'], 'Game')
        self.assertEqual(snapshot['focus_hwnd'], 111)
        self.assertEqual(snapshot['focus_source'], 'foreground')
        self.assertEqual(snapshot['focus_process'], 'game.exe')

    def test_status_carries_the_snapshot(self):
        with patch.object(control, '_focus_snapshot',
                          return_value=dict(foreground_hwnd=1, focus_hwnd=2,
                                            focus_process='x.exe', focus_source='test')):
            status = control.status(include_focus=True)
        self.assertEqual(status['foreground_hwnd'], 1)
        self.assertEqual(status['focus_hwnd'], 2)


class BoundsFallbackTests(unittest.TestCase):
    def test_zero_rect_falls_back_to_the_client_rect(self):
        from computer_mcp.actions import window as window_actions
        with patch('win32gui.GetWindowRect', return_value=(0, 0, 0, 0)), \
                patch('ctypes.windll.dwmapi.DwmGetWindowAttribute', return_value=1), \
                patch('win32gui.GetClientRect', return_value=(0, 0, 530, 500)), \
                patch('win32gui.ClientToScreen', return_value=(1280, 684)):
            bounds, source = window_actions._bounds_of(99)
        self.assertEqual(source, 'client')
        self.assertEqual(bounds, dict(x=1280, y=684, width=530, height=500))

    def test_normal_window_is_used_as_is(self):
        from computer_mcp.actions import window as window_actions
        with patch('win32gui.GetWindowRect', return_value=(10, 20, 210, 120)):
            bounds, source = window_actions._bounds_of(99)
        self.assertEqual(source, 'window')
        self.assertEqual(bounds, dict(x=10, y=20, width=200, height=100))


class FrameIdTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def setUp(self):
        super().setUp()
        guard = patch('computer_mcp.control.blocking_reason', return_value=None)
        guard.start()
        self.addCleanup(guard.stop)

    def test_screenshot_returns_a_frame_id(self):
        shot = dict(format='base64_png', data='AAA', width=100, height=80,
                    frame_id='f_abc123')
        with patch('computer_mcp.actions.screenshot.get_screenshot', return_value=shot):
            result = call('screenshot')
        self.assertEqual(result['frame_id'], 'f_abc123')

    def test_window_screenshot_keeps_its_frame_id(self):
        shot = dict(success=True, format='base64_png', data='AAA', width=200,
                    height=100, frame_id='f_win999', bounds=dict(x=5, y=6, width=200, height=100))
        with patch('computer_mcp.actions.window.screenshot_window', return_value=shot):
            result = call('screenshot_window', hwnd=1234)
        self.assertEqual(result['frame_id'], 'f_win999')

    def test_frame_coordinates_convert_to_screen_pixels(self):
        capture_core._frames.clear()
        with patch('computer_mcp.core.screenshot._foreground_hwnd', return_value=42):
            frame_id = capture_core._register_frame(
                dict(x=100, y=50, w=1000, h=800), 1000, 800, 1000, 800, 1.0)
        x, y = capture_core.to_physical(frame_id, 500, 400)
        self.assertEqual((x, y), (600, 450))

    def test_metadata_carries_the_frame_id(self):
        state = Mock()
        state.config = {'observe_screen': True}
        state.get_state.return_value = {}
        shot = dict(format='base64_png', data='AAA', width=10, height=10,
                    frame_id='f_meta', source_width=20, source_height=20)
        with patch('computer_mcp.core.response.screenshot_to_image_content', return_value=None):
            content = format_response(dict(success=True), state, screenshot_data=shot)
        text = content[-1].text
        self.assertIn('f_meta', text)
        self.assertIn('source_width', text)


if __name__ == '__main__':
    unittest.main()
