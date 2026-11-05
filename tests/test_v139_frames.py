"""v1.3.9-beta: frame_id coordinate contract.

Screenshots now carry the physical region they came from, and clicks accept
image coordinates for that frame. The server converts; the model never has to
guess the difference between a 1280x720 preview and a 2560x1440 screen.
"""
import os
import sys
import time
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401

from PIL import Image

from authority_fixture import AuthorityCase
from computer_mcp.actions import mouse as mouse_actions
from computer_mcp.core import screenshot as capture


class FrameRegistryTests(unittest.TestCase):
    def setUp(self):
        self._saved = dict(capture._frames)
        capture._frames.clear()
        self.addCleanup(self._restore)

    def _restore(self):
        capture._frames.clear()
        capture._frames.update(self._saved)

    def _frame(self, **overrides):
        params = dict(region={'x': 100, 'y': 50, 'w': 400, 'h': 200},
                      src_w=400, src_h=200, out_w=200, out_h=100, scale=0.5)
        params.update(overrides)
        with patch.object(capture, '_dpi_context', return_value=144), \
                patch.object(capture, '_foreground_hwnd', return_value=723186):
            return capture._register_frame(params.pop('region'),
                                           params['src_w'], params['src_h'],
                                           params['out_w'], params['out_h'],
                                           params['scale'])

    def test_frame_records_geometry_and_context(self):
        frame_id = self._frame()
        record = capture.get_frame(frame_id)
        self.assertEqual(record['source_rect'], [100, 50, 400, 200])
        self.assertEqual(record['image_size'], [200, 100])
        self.assertEqual(record['dpi'], 144)
        self.assertEqual(record['hwnd'], 723186)
        self.assertTrue(frame_id.startswith('f_'))

    def test_image_coordinates_map_to_physical_pixels(self):
        frame_id = self._frame()
        self.assertEqual(capture.to_physical(frame_id, 0, 0), (100, 50))
        self.assertEqual(capture.to_physical(frame_id, 200, 100), (500, 250))
        self.assertEqual(capture.to_physical(frame_id, 100, 50), (300, 150))

    def test_full_screen_frame_uses_the_monitor_origin(self):
        with patch.object(capture, '_sct', return_value=types.SimpleNamespace(
                monitors={1: {'left': -1920, 'top': 0, 'width': 1920, 'height': 1080}})):
            frame_id = self._frame(region=None, src_w=1920, src_h=1080,
                                   out_w=960, out_h=540)
        self.assertEqual(capture.to_physical(frame_id, 0, 0), (-1920, 0))
        self.assertEqual(capture.to_physical(frame_id, 960, 540), (0, 1080))

    def test_unknown_frame_is_rejected(self):
        with self.assertRaises(ValueError):
            capture.to_physical('f_deadbeef', 1, 1)

    def test_stale_frame_is_rejected(self):
        frame_id = self._frame()
        capture._frames[frame_id]['captured_at'] = time.time() - capture.FRAME_TTL_S - 1
        with self.assertRaises(ValueError) as caught:
            capture.to_physical(frame_id, 1, 1)
        self.assertIn('stale', str(caught.exception))

    def test_point_outside_the_frame_is_rejected(self):
        frame_id = self._frame()
        with self.assertRaises(ValueError):
            capture.to_physical(frame_id, 201, 50)
        with self.assertRaises(ValueError):
            capture.to_physical(frame_id, 50, -1)

    def test_registry_is_bounded(self):
        with patch.object(capture, 'FRAME_MAX', 3):
            ids = [self._frame() for _ in range(5)]
        self.assertLessEqual(len([i for i in ids if i in capture._frames]), 3)


class CaptureFieldsTests(unittest.TestCase):
    def setUp(self):
        self._saved = dict(capture._frames)
        capture._frames.clear()
        capture._prev_small = None
        self.addCleanup(self._restore)

    def _restore(self):
        capture._frames.clear()
        capture._frames.update(self._saved)

    def test_capture_returns_frame_identity(self):
        image = Image.new('RGB', (400, 200), (10, 20, 30))
        with patch.object(capture, '_grab', return_value=(image, 400, 200)), \
                patch.object(capture, '_origin', return_value=(64, 32)), \
                patch.object(capture, '_dpi_context', return_value=120), \
                patch.object(capture, '_foreground_hwnd', return_value=1234), \
                patch.dict(capture._CONFIG, {'scale': 0.5, 'format': 'png'}):
            result = capture.capture_screenshot(region={'x': 64, 'y': 32, 'w': 400, 'h': 200})
        self.assertIn('frame_id', result)
        self.assertEqual(result['image_size'], [200, 100])
        self.assertEqual(result['source_rect'], [64, 32, 400, 200])
        self.assertEqual(result['dpi'], 120)
        self.assertEqual(result['hwnd'], 1234)
        self.assertEqual(capture.to_physical(result['frame_id'], 100, 50), (264, 132))


class WindowInvalidationTests(unittest.TestCase):
    def setUp(self):
        self._saved = dict(capture._frames)
        capture._frames.clear()
        self.addCleanup(self._restore)

    def _restore(self):
        capture._frames.clear()
        capture._frames.update(self._saved)

    def _frame(self, window):
        with patch.object(capture, '_window_snapshot', return_value=window), \
                patch.object(capture, '_dpi_context', return_value=96):
            return capture._register_frame({'x': 0, 'y': 0, 'w': 800, 'h': 600},
                                           800, 600, 400, 300, 0.5)

    def test_window_that_did_not_move_still_maps(self):
        window = dict(rect=[10, 20, 810, 620], dpi=96, valid=True)
        frame_id = self._frame(window)
        with patch.object(capture, '_window_snapshot', return_value=window):
            self.assertEqual(capture.to_physical(frame_id, 0, 0), (0, 0))

    def test_moved_window_invalidates_the_frame(self):
        frame_id = self._frame(dict(rect=[10, 20, 810, 620], dpi=96, valid=True))
        moved = dict(rect=[40, 60, 840, 660], dpi=96, valid=True)
        with patch.object(capture, '_window_snapshot', return_value=moved):
            with self.assertRaises(ValueError) as caught:
                capture.to_physical(frame_id, 10, 10)
        self.assertIn('moved', str(caught.exception))

    def test_dpi_change_invalidates_the_frame(self):
        frame_id = self._frame(dict(rect=[10, 20, 810, 620], dpi=96, valid=True))
        scaled = dict(rect=[10, 20, 810, 620], dpi=144, valid=True)
        with patch.object(capture, '_window_snapshot', return_value=scaled):
            with self.assertRaises(ValueError):
                capture.to_physical(frame_id, 10, 10)

    def test_closed_window_invalidates_the_frame(self):
        frame_id = self._frame(dict(rect=[10, 20, 810, 620], dpi=96, valid=True))
        gone = dict(rect=None, dpi=None, valid=False)
        with patch.object(capture, '_window_snapshot', return_value=gone):
            with self.assertRaises(ValueError):
                capture.to_physical(frame_id, 10, 10)

    def test_frame_without_a_window_is_not_invalidated(self):
        frame_id = self._frame(None)
        self.assertEqual(capture.to_physical(frame_id, 0, 0), (0, 0))


class FakeMouse:
    def __init__(self):
        self.position = (0, 0)
        self.clicks = []
        self.presses = []

    def click(self, button, *args, **kwargs):
        self.clicks.append((button, self.position))

    def press(self, button):
        self.presses.append(button)

    def release(self, button):
        self.presses.append(('release', button))


class ClickFrameTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def _win32(self):
        gui = types.ModuleType('win32gui')
        gui.WindowFromPoint = lambda point: 111
        gui.GetAncestor = lambda hwnd, flag: 111
        proc = types.ModuleType('win32process')
        proc.GetWindowThreadProcessId = lambda hwnd: (0, 4242)
        return gui, proc

    def test_click_uses_converted_physical_coordinates(self):
        gui, proc = self._win32()
        mouse = FakeMouse()
        record = {'pid': 4242, 'created': 1.0, 'exe': 'notepad.exe'}
        with patch.dict(sys.modules, {'win32gui': gui, 'win32process': proc}), \
                patch('computer_mcp.capabilities.process_record', return_value=record), \
                patch('computer_mcp.capabilities.require_target'), \
                patch('computer_mcp.core.screenshot.to_physical', return_value=(300, 150)) as mapper:
            result = mouse_actions.click(controller=mouse, frame_id='f_1234', x=100, y=50)
        mapper.assert_called_once_with('f_1234', 100, 50)
        self.assertEqual(mouse.position, (300, 150))
        self.assertEqual(result['x'], 300)
        self.assertEqual(result['y'], 150)
        self.assertEqual(result['frame_id'], 'f_1234')
        self.assertEqual(result['image_point'], [100.0, 50.0])

    def test_frame_id_without_coordinates_is_rejected(self):
        with self.assertRaises(ValueError):
            mouse_actions.click(controller=FakeMouse(), frame_id='f_1234')

    def test_unknown_frame_surfaces_as_value_error(self):
        with patch('computer_mcp.core.screenshot.to_physical',
                   side_effect=ValueError('unknown frame_id')):
            with self.assertRaises(ValueError):
                mouse_actions.click(controller=FakeMouse(), frame_id='f_nope', x=1, y=1)


class DoubleClickAndDragFrameTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def test_double_click_converts_and_positions(self):
        mouse = FakeMouse()
        with patch('computer_mcp.core.screenshot.to_physical', return_value=(640, 360)) as mapper:
            result = mouse_actions.double_click(controller=mouse, frame_id='f_9', x=10, y=20)
        mapper.assert_called_once_with('f_9', 10, 20)
        self.assertEqual(mouse.position, (640, 360))
        self.assertEqual(result['frame_id'], 'f_9')
        self.assertEqual(result['image_point'], [10.0, 20.0])

    def test_double_click_without_coordinates_uses_the_cursor(self):
        mouse = FakeMouse()
        result = mouse_actions.double_click(controller=mouse)
        self.assertEqual(mouse.position, (0, 0))
        self.assertNotIn('frame_id', result)

    def test_drag_converts_both_points(self):
        mouse = FakeMouse()
        calls = {'n': 0}

        def mapper(frame_id, x, y):
            calls['n'] += 1
            return (int(x) * 2, int(y) * 2)

        with patch('computer_mcp.core.screenshot.to_physical', side_effect=mapper):
            result = mouse_actions.drag({'x': 10, 'y': 20}, {'x': 30, 'y': 40},
                                        controller=mouse, frame_id='f_9')
        self.assertEqual(calls['n'], 2)
        self.assertEqual(result['start'], {'x': 20, 'y': 40})
        self.assertEqual(result['end'], {'x': 60, 'y': 80})
        self.assertEqual(result['image_start'], [10.0, 20.0])
        self.assertEqual(mouse.position, (60, 80))

    def test_drag_without_frame_keeps_physical_coordinates(self):
        mouse = FakeMouse()
        result = mouse_actions.drag({'x': 1, 'y': 2}, {'x': 3, 'y': 4}, controller=mouse)
        self.assertEqual(result['start'], {'x': 1, 'y': 2})
        self.assertNotIn('frame_id', result)


class ScreenStateFrameTests(unittest.TestCase):
    def setUp(self):
        self._saved = dict(capture._frames)
        capture._frames.clear()
        self.addCleanup(self._restore)

    def _restore(self):
        capture._frames.clear()
        capture._frames.update(self._saved)

    def test_screen_state_reports_the_latest_usable_frame(self):
        image = Image.new('RGB', (200, 100), (5, 5, 5))
        with patch.object(capture, '_grab', return_value=(image, 200, 100)), \
                patch.object(capture, '_origin', return_value=(0, 0)), \
                patch.object(capture, '_dpi_context', return_value=96), \
                patch.object(capture, '_foreground_hwnd', return_value=None):
            frame_id = capture._register_frame(None, 200, 100, 200, 100, 1.0)
            state = capture.screen_state()
        self.assertEqual(state['frame_id'], frame_id)

    def test_screen_state_has_no_frame_when_registry_is_empty(self):
        image = Image.new('RGB', (200, 100), (5, 5, 5))
        with patch.object(capture, '_grab', return_value=(image, 200, 100)):
            state = capture.screen_state()
        self.assertIsNone(state['frame_id'])


if __name__ == '__main__':
    unittest.main()
