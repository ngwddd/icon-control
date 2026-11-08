"""v1.4.2rc2 audit: window binding, per-region frames, key cleanup, bounds."""
import unittest
from unittest.mock import Mock, patch

from authority_fixture import AuthorityCase
from computer_mcp import ui_ext
from computer_mcp.actions import mouse as mouse_actions
from computer_mcp.core import screenshot as capture_core
from computer_mcp.input_guard import KeyboardController, MouseController
from computer_mcp.zones.dispatch import ComputerState, dispatch

IDENTITY = (11, 21, 123.0, 'Win', (0, 0, 300, 200), 144)


def call(tool, **arguments):
    return dispatch(tool, dict(arguments), computer_state=ComputerState(),
                    mouse_controller=MouseController(),
                    keyboard_controller=KeyboardController()).get("result") or {}


class WindowBindingTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def setUp(self):
        super().setUp()
        capture_core._frames.clear()

    def window_frame(self, target=42):
        with patch.object(capture_core, '_foreground_hwnd', return_value=target), \
                patch.object(capture_core, '_window_snapshot', return_value=None):
            return capture_core._register_frame(
                dict(x=100, y=50, w=400, h=300), 400, 300, 400, 300, 1.0,
                hwnd=target, target_hwnd=target)

    def test_covered_window_refuses_the_click(self):
        """E01: a PrintWindow capture succeeds while covered; the click must not."""
        frame = self.window_frame()
        with patch('win32gui.WindowFromPoint', return_value=99), \
                patch('win32gui.GetAncestor', return_value=99), \
                patch('win32gui.IsWindow', return_value=True):
            with self.assertRaises(ValueError) as caught:
                capture_core.assert_frame_target(frame, 200, 150)
        self.assertIn('target_occluded', str(caught.exception))

    def test_visible_target_is_allowed(self):
        frame = self.window_frame()
        with patch('win32gui.WindowFromPoint', return_value=42), \
                patch('win32gui.GetAncestor', return_value=42), \
                patch('win32gui.IsWindow', return_value=True):
            capture_core.assert_frame_target(frame, 200, 150)   # must not raise

    def test_screen_frames_have_no_target_to_check(self):
        with patch.object(capture_core, '_foreground_hwnd', return_value=7), \
                patch.object(capture_core, '_window_snapshot', return_value=None):
            frame = capture_core._register_frame(None, 1000, 800, 1000, 800, 1.0)
        with patch('win32gui.WindowFromPoint') as wfp:
            capture_core.assert_frame_target(frame, 10, 10)
        wfp.assert_not_called()

    def test_click_on_a_covered_window_sends_no_input(self):
        frame = self.window_frame()
        controller = Mock()
        with patch('win32gui.WindowFromPoint', return_value=99), \
                patch('win32gui.GetAncestor', return_value=99), \
                patch('win32gui.IsWindow', return_value=True), \
                patch('win32process.GetWindowThreadProcessId', return_value=(1, 2)), \
                patch('computer_mcp.capabilities.process_record', return_value=('p',)), \
                patch('computer_mcp.capabilities.require_target'):
            with self.assertRaises(ValueError):
                mouse_actions.click(controller=controller, frame_id=frame, x=10, y=10)
        controller.click.assert_not_called()


class RegionFrameTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def setUp(self):
        super().setUp()
        guard = patch('computer_mcp.control.blocking_reason', return_value=None)
        guard.start()
        self.addCleanup(guard.stop)

    def test_each_region_reports_its_own_frame(self):
        """E02: three crops, three frames; using the first one would mis-map."""
        counter = {"n": 0}

        def fake_capture(region=None):
            counter["n"] += 1
            return dict(format='base64_png', data='AAA', width=region['w'],
                        height=region['h'], region=region,
                        frame_id=f'f_{counter["n"]}',
                        source_rect=[region['x'], region['y'], region['w'], region['h']],
                        image_size=[region['w'], region['h']])

        with patch('computer_mcp.core.screenshot.capture_screenshot', side_effect=fake_capture):
            result = call('screenshot', regions=[dict(x=0, y=0, w=10, h=10),
                                                 dict(x=20, y=20, w=30, h=30),
                                                 dict(x=40, y=40, w=50, h=50)])
        frames = [region['frame_id'] for region in result['regions']]
        self.assertEqual(frames, ['f_1', 'f_2', 'f_3'])
        self.assertEqual(result['regions'][1]['source_rect'], [20, 20, 30, 30])
        self.assertEqual(result['regions'][1]['image_size'], [30, 30])


class BatchCleanupTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def setUp(self):
        super().setUp()

    class FlakyKeyboard:
        def __init__(self):
            self.events = []
            self.fail_release_once = True

        def press(self, key):
            self.events.append(('press', key))

        def release(self, key):
            if self.fail_release_once and key == 'w':
                self.fail_release_once = False
                raise RuntimeError('release failed')
            self.events.append(('release', key))

        def type(self, text):
            self.events.append(('type', text))

    def test_e03_base_key_release_failure_is_tracked_and_retried(self):
        keyboard = self.FlakyKeyboard()
        run_batch = getattr(ui_ext.run_batch, '__wrapped__', ui_ext.run_batch)
        with patch('computer_mcp.execution.sleep'):
            result = run_batch([dict(action='key', key='w', hold_ms=100)],
                               Mock(), keyboard, default_sleep_ms=0)
        self.assertIn(('press', 'w'), keyboard.events)
        releases = [event for event in keyboard.events if event[0] == 'release']
        self.assertGreaterEqual(len(releases), 1,
                                'the cleanup pass must retry the key that failed to release')
        self.assertFalse(result['ok'], 'a failed release must not read as success')


class FrameBoundsTests(unittest.TestCase):
    def setUp(self):
        capture_core._frames.clear()
        with patch.object(capture_core, '_foreground_hwnd', return_value=1), \
                patch.object(capture_core, '_window_snapshot', return_value=None):
            self.frame = capture_core._register_frame(
                dict(x=100, y=50, w=1000, h=800), 1000, 800, 1000, 800, 1.0)

    def test_last_pixel_maps_inside(self):
        """E05: the bottom-right pixel must not land one pixel outside."""
        self.assertEqual(capture_core.to_physical(self.frame, 999, 799), (1099, 849))

    def test_width_is_past_the_last_pixel(self):
        with self.assertRaises(ValueError):
            capture_core.to_physical(self.frame, 1000, 799)
        with self.assertRaises(ValueError):
            capture_core.to_physical(self.frame, 999, 800)


if __name__ == '__main__':
    unittest.main()
