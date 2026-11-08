"""v1.4.2 stable gate: full binding for click/double/drag, honest key release."""
import unittest
from unittest.mock import Mock, patch

from authority_fixture import AuthorityCase
from computer_mcp import ui_ext
from computer_mcp.actions import mouse as mouse_actions
from computer_mcp.core import screenshot as capture_core
from computer_mcp.input_guard import KeyboardController, MouseController
from computer_mcp.zones.dispatch import ComputerState, dispatch


def call(tool, **arguments):
    return dispatch(tool, dict(arguments), computer_state=ComputerState(),
                    mouse_controller=MouseController(),
                    keyboard_controller=KeyboardController()).get("result") or {}


def raw_action(function):
    """The undecorated action: these tests assert on the binding logic itself."""
    return getattr(function, '__wrapped__', function)


class BindingCase(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def setUp(self):
        super().setUp()
        capture_core._frames.clear()
        guard = patch('computer_mcp.control.blocking_reason', return_value=None)
        guard.start()
        self.addCleanup(guard.stop)
        with patch.object(capture_core, '_foreground_hwnd', return_value=42), \
                patch.object(capture_core, '_window_snapshot', return_value=None), \
                patch.object(capture_core, '_process_pid', return_value=7), \
                patch.object(capture_core, '_process_created', return_value=100.0):
            self.frame = capture_core._register_frame(
                dict(x=100, y=50, w=400, h=300), 400, 300, 400, 300, 1.0,
                hwnd=42, target_hwnd=42)

    def patched_windows(self, top=42, pid=7):
        from contextlib import ExitStack
        stack = ExitStack()
        for patcher in (
                patch('win32gui.WindowFromPoint', return_value=top),
                patch('win32gui.GetAncestor', return_value=top),
                patch('win32gui.IsWindow', return_value=True),
                patch.object(capture_core, '_process_pid', return_value=pid),
                patch.object(capture_core, '_process_created', return_value=100.0)):
            stack.enter_context(patcher)
        return stack


class DragBindingTests(BindingCase):
    def test_drag_is_refused_when_the_target_is_covered(self):
        mouse = Mock()
        with self.patched_windows(top=99):
            with self.assertRaises(ValueError) as caught:
                raw_action(mouse_actions.drag)({'x': 10, 'y': 10}, {'x': 50, 'y': 50},
                                   controller=mouse, frame_id=self.frame)
        self.assertIn('target_occluded', str(caught.exception))
        mouse.press.assert_not_called()
        mouse.release.assert_not_called()

    def test_drag_binds_the_press_to_the_frame_window(self):
        mouse = Mock()
        mouse.position = (0, 0)
        with self.patched_windows(top=42):
            raw_action(mouse_actions.drag)({'x': 10, 'y': 10}, {'x': 50, 'y': 50},
                               controller=mouse, frame_id=self.frame)
        self.assertEqual(mouse.press.call_args.kwargs.get('expected_hwnd'), 42)
        mouse.release.assert_called_once()

    def test_drag_releases_the_button_when_the_end_point_fails(self):
        mouse = Mock()
        calls = {"n": 0}

        def check(frame_id, x, y):
            calls["n"] += 1
            if calls["n"] >= 4:                     # start ok, then the end is covered
                raise ValueError('target_occluded: covered')

        with patch.object(capture_core, 'assert_frame_target', side_effect=check), \
                patch.object(capture_core, 'frame_target',
                             return_value=dict(hwnd=42, pid=7, created=100.0)):
            with self.assertRaises(ValueError):
                raw_action(mouse_actions.drag)({'x': 10, 'y': 10}, {'x': 50, 'y': 50},
                                   controller=mouse, frame_id=self.frame)
        mouse.press.assert_called_once()
        mouse.release.assert_called_once(), 'the button must come back up'


class ClickRecheckTests(BindingCase):
    def test_click_checks_before_and_after_positioning(self):
        mouse = Mock()
        mouse.position = (0, 0)
        with self.patched_windows(top=42), \
                patch('win32process.GetWindowThreadProcessId', return_value=(1, 2)), \
                patch('computer_mcp.capabilities.process_record', return_value=('p',)), \
                patch('computer_mcp.capabilities.require_target'):
            with patch.object(capture_core, 'assert_frame_target') as check:
                raw_action(mouse_actions.click)(controller=mouse, frame_id=self.frame, x=10, y=10)
        self.assertEqual(check.call_count, 2, 'one check before the move, one after')

    def test_click_passes_the_frame_window_to_the_final_press(self):
        mouse = Mock()
        mouse.position = (0, 0)
        with self.patched_windows(top=42), \
                patch('win32process.GetWindowThreadProcessId', return_value=(1, 2)), \
                patch('computer_mcp.capabilities.process_record', return_value=('p',)), \
                patch('computer_mcp.capabilities.require_target'):
            raw_action(mouse_actions.click)(controller=mouse, frame_id=self.frame, x=10, y=10)
        self.assertEqual(mouse.click.call_args.kwargs.get('expected_hwnd'), 42)

    def test_recycled_handle_is_rejected(self):
        with patch('win32gui.WindowFromPoint', return_value=42), \
                patch('win32gui.GetAncestor', return_value=42), \
                patch('win32gui.IsWindow', return_value=True), \
                patch.object(capture_core, '_process_pid', return_value=999), \
                patch.object(capture_core, '_process_created', return_value=999.0):
            with self.assertRaises(ValueError) as caught:
                capture_core.assert_frame_target(self.frame, 200, 150)
        self.assertIn('another process', str(caught.exception))


class HoldReleaseTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def setUp(self):
        super().setUp()
        guard = patch('computer_mcp.control.blocking_reason', return_value=None)
        guard.start()
        self.addCleanup(guard.stop)

    def test_failed_release_is_reported_not_hidden(self):
        with patch('computer_mcp.actions.keyboard.key_down', return_value=dict(success=True)), \
                patch('computer_mcp.actions.keyboard.key_up',
                      side_effect=RuntimeError('release failed')) as up, \
                patch('computer_mcp.execution.sleep'):
            result = call('key_press', key='w', hold_ms=100)
        self.assertFalse(result.get('released'))
        self.assertFalse(result.get('success'))
        self.assertTrue(result.get('release_failed'))
        self.assertGreaterEqual(up.call_count, 2, 'a failed release is retried once')


class BatchModifierTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    class CtrlStuckKeyboard:
        def __init__(self):
            self.events = []

        def press(self, key):
            self.events.append(('press', key))

        def release(self, key):
            if 'ctrl' in str(key).lower():
                raise RuntimeError('ctrl release failed')
            self.events.append(('release', key))

        def type(self, text):
            self.events.append(('type', text))

    def test_a_stuck_modifier_stops_the_batch(self):
        keyboard = self.CtrlStuckKeyboard()
        run_batch = getattr(ui_ext.run_batch, '__wrapped__', ui_ext.run_batch)
        with patch('computer_mcp.execution.sleep'):
            result = run_batch([
                dict(action='key', key='ctrl+a'),
                dict(action='type', text='hello'),
            ], Mock(), keyboard, stop_on_error=False, default_sleep_ms=0)
        self.assertFalse(result['ok'])
        self.assertNotIn(('type', 'hello'), keyboard.events,
                         'no input may run while a modifier is still down')
        self.assertIn('keyboard_state_unknown', result['log'][0])


class FloatBoundaryTests(unittest.TestCase):
    def test_fractional_edge_stays_inside(self):
        capture_core._frames.clear()
        with patch.object(capture_core, '_foreground_hwnd', return_value=1), \
                patch.object(capture_core, '_window_snapshot', return_value=None):
            frame = capture_core._register_frame(
                dict(x=100, y=50, w=1000, h=800), 1000, 800, 500, 400, 0.5)
        x, y = capture_core.to_physical(frame, 499.9, 399.9)
        self.assertLessEqual(x, 100 + 1000 - 1)
        self.assertLessEqual(y, 50 + 800 - 1)


if __name__ == '__main__':
    unittest.main()
