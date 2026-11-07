"""v1.4.1: one call, several regions (screenshots and OCR)."""
import unittest
from unittest.mock import Mock, patch

from authority_fixture import AuthorityCase
from computer_mcp.input_guard import KeyboardController, MouseController
from computer_mcp.zones.dispatch import ComputerState, dispatch


def call(name, **arguments):
    return dispatch(name, arguments, computer_state=ComputerState(),
                    mouse_controller=MouseController(),
                    keyboard_controller=KeyboardController())


class ScreenshotRegionTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def setUp(self):
        super().setUp()
        guard = patch('computer_mcp.control.blocking_reason', return_value=None)
        guard.start()
        self.addCleanup(guard.stop)

    def test_several_regions_come_back_as_several_images(self):
        def fake_capture(region=None):
            return dict(format='base64_png', data='AAA', width=region['w'],
                        height=region['h'], region=region)

        with patch('computer_mcp.core.screenshot.capture_screenshot', side_effect=fake_capture):
            out = call('screenshot', regions=[dict(x=0, y=0, w=10, h=10),
                                              [20, 20, 30, 30]])
        result = out['result']
        self.assertTrue(result['success'])
        self.assertEqual(len(result['regions']), 2)
        self.assertEqual(len(result['_images']), 2)
        self.assertEqual(result['regions'][1]['width'], 30)

    def test_a_single_region_returns_one_image(self):
        with patch('computer_mcp.core.screenshot.capture_screenshot',
                   return_value=dict(format='base64_png', data='AAA', width=5, height=5)):
            out = call('screenshot', region=dict(x=1, y=2, w=5, h=5))
        self.assertTrue(out['result']['success'])
        self.assertNotIn('_images', out['result'])

    def test_a_bad_region_is_reported_not_crashed(self):
        with patch('computer_mcp.core.screenshot.capture_screenshot',
                   return_value=dict(format='base64_png', data='AAA', width=1, height=1)):
            out = call('screenshot', regions=[dict(x=0, y=0, w=1, h=1), 'nonsense'])
        self.assertIn('error', out['result']['regions'][1])


class OcrRegionTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def test_several_regions_are_read_in_one_call(self):
        seen = []

        def fake_ocr(region=None, max_lines=80, hwnd=None):
            seen.append(region)
            return dict(lines=[dict(text=f"r{region['x']}")])

        with patch('computer_mcp.ocr_ext.ocr_read', side_effect=fake_ocr):
            result = call('ocr_read', regions=[dict(x=1, y=0, w=10, h=10),
                                               [50, 50, 20, 20]])['result']
        self.assertEqual(len(seen), 2)
        self.assertEqual(result['count'], 2)
        self.assertEqual(result['regions'][1]['lines'][0]['text'], 'r50')


class ResponseImageTests(unittest.TestCase):
    def test_extra_images_become_extra_content_blocks(self):
        from computer_mcp.core.response import format_response

        state = Mock()
        state.config = {'observe_screen': True}
        state.get_state.return_value = {}
        first = dict(format='base64_png', data='AAA', width=1, height=1)
        second = dict(format='base64_png', data='BBB', width=1, height=1)
        result = dict(success=True, _images=[first, second])
        with patch('computer_mcp.core.response.screenshot_to_image_content',
                   side_effect=lambda shot: ('image', shot['data'])):
            content = format_response(result, state, screenshot_data=first)
        images = [block for block in content if isinstance(block, tuple)]
        self.assertEqual([block[1] for block in images], ['AAA', 'BBB'])
        self.assertNotIn('_images', result)


if __name__ == '__main__':
    unittest.main()
