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


class FakeMouse:
    def __init__(self):
        self.position = (0, 0)
        self.clicks = []

    def click(self, button, *args, **kwargs):
        self.clicks.append((button, self.position))

    def press(self, button):
        self.clicks.append(('press', self.position))

    def release(self, button):
        self.clicks.append(('release', self.position))


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


if __name__ == '__main__':
    unittest.main()
