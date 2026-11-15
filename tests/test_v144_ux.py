"""v1.4.4: coordinates, click_text candidates, focus_window, clipped capture."""
import unittest
from unittest.mock import Mock, patch

from authority_fixture import AuthorityCase
from computer_mcp import ocr_ext as O
from computer_mcp.actions import mouse as M
from computer_mcp.actions import window as W

raw_click = getattr(M.click, "__wrapped__", M.click)
SCREEN = {"x": 0, "y": 0, "w": 2560, "h": 1440}


class BoundsTests(unittest.TestCase):
    def test_click_outside_the_screen_says_where_the_screen_is(self):
        with patch.object(O, "screen_bounds", return_value=SCREEN):
            with self.assertRaises(ValueError) as caught:
                raw_click(x=1316, y=1504)
        message = str(caught.exception)
        self.assertIn("(1316, 1504)", message)
        self.assertIn("0..2559", message)
        self.assertIn("1439", message)
        self.assertIn("frame_id", message)

    def test_a_point_inside_the_screen_is_not_refused(self):
        self.assertTrue(O.point_on_screen(100, 100, SCREEN))
        self.assertFalse(O.point_on_screen(3000, 100, SCREEN))
        self.assertFalse(O.point_on_screen(100, -5, SCREEN))

    def test_negative_coordinates_are_valid_on_a_left_hand_monitor(self):
        wide = {"x": -1920, "y": 0, "w": 4480, "h": 1440}
        self.assertTrue(O.point_on_screen(-800, 100, wide))


def ocr_result(lines):
    return {"ok": True, "count": len(lines), "lines": lines, "screen": SCREEN,
            "text_angle": 0.0, "ms": 1.0}


class FindTextOrderingTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True
    def test_a_tighter_line_beats_a_longer_heading(self):
        heading = {"text": "Authorize GitHub CLI", "x": 300, "y": 200, "w": 400, "h": 40}
        button = {"text": "Authorize github", "x": 300, "y": 600, "w": 380, "h": 40}
        with patch.object(O, "ocr_read", return_value=ocr_result([heading, button])):
            result = O.find_text("Authorize github")
        self.assertGreaterEqual(result["found"], 2)
        self.assertEqual(result["matches"][0]["text"], "Authorize github",
                         "the button must outrank the heading it is contained in")
        self.assertLess(result["matches"][0]["slack"], result["matches"][1]["slack"])

    def test_off_screen_lines_are_marked(self):
        line = {"text": "Verify", "x": 300, "y": 1500, "w": 120, "h": 40}
        with patch.object(O, "ocr_read", return_value=ocr_result([line])):
            result = O.find_text("Verify")
        self.assertFalse(result["matches"][0]["onscreen"])
        self.assertEqual(result["onscreen"], 0)


class ClickTextTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True
    def matches(self, cy):
        return {"ok": True, "found": 2, "screen": SCREEN, "matches": [
            {"text": "Authorize github", "cx": 500, "cy": cy, "w": 300, "h": 40,
             "ratio": 1.0, "slack": 0, "onscreen": True},
            {"text": "Authorize GitHub CLI", "cx": 500, "cy": 200, "w": 300, "h": 40,
             "ratio": 1.0, "slack": 3, "onscreen": True},
        ]}

    def test_candidates_and_chosen_index_are_reported(self):
        mouse = Mock()
        with patch.object(O, "find_text", return_value=self.matches(600)):
            result = O.click_text("Authorize github", mouse=mouse)
        self.assertTrue(result["ok"])
        self.assertEqual(result["clicked_text"], "Authorize github")
        self.assertEqual(result["chosen_index"], 0)
        self.assertEqual(len(result["candidates"]), 2)
        self.assertEqual(mouse.position, (500, 600))

    def test_an_off_screen_target_is_refused_with_a_reason(self):
        mouse = Mock()
        with patch.object(O, "find_text", return_value=self.matches(1504)):
            result = O.click_text("Authorize github", mouse=mouse)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "offscreen_target")
        self.assertIn("最大化", result["hint"] + result["error"])
        mouse.click.assert_not_called()


class FocusWindowTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True
    def test_focus_reports_readback_and_attempts(self):
        def fake_foreground():
            return 42 if win32.get("focused") else 7

        win32 = {"focused": False}
        with patch("win32gui.IsWindow", return_value=True), \
                patch("win32gui.IsIconic", return_value=True), \
                patch("win32gui.ShowWindow"), \
                patch("win32gui.BringWindowToTop"), \
                patch("win32gui.SetForegroundWindow", side_effect=lambda h: win32.update(focused=True)), \
                patch("win32gui.GetForegroundWindow", side_effect=fake_foreground), \
                patch("win32gui.GetWindowText", side_effect=lambda h: "target" if h == 42 else "other"), \
                patch("win32gui.GetWindowRect", return_value=(100, 100, 900, 700)):
            result = W.focus_window(42)
        self.assertTrue(result["focused"])
        self.assertEqual(result["foreground_before"]["hwnd"], 7)
        self.assertEqual(result["foreground_after"]["hwnd"], 42)
        self.assertIn("restore", result["attempts"])

    def test_a_refused_focus_says_what_to_do(self):
        with patch("win32gui.IsWindow", return_value=True), \
                patch("win32gui.IsIconic", return_value=False), \
                patch("win32gui.BringWindowToTop"), \
                patch("win32gui.SetForegroundWindow", side_effect=RuntimeError("denied")), \
                patch("win32gui.GetForegroundWindow", return_value=7), \
                patch("win32gui.GetWindowText", return_value="other"), \
                patch("win32gui.GetWindowRect", return_value=(100, 100, 900, 700)), \
                patch("ctypes.windll.user32.AttachThreadInput", create=True), \
                patch("ctypes.windll.kernel32.GetCurrentThreadId", return_value=1, create=True), \
                patch("win32process.GetWindowThreadProcessId", return_value=(2, 7)):
            result = W.focus_window(42)
        self.assertFalse(result["focused"])
        self.assertIn("minimise", result["next_action"])

    def test_a_vanished_window_is_reported(self):
        with patch("win32gui.IsWindow", return_value=False):
            result = W.focus_window(42)
        self.assertFalse(result["success"])


class ClippedCaptureTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True
    def test_a_window_hanging_off_screen_is_flagged(self):
        from PIL import Image

        image = Image.new("RGB", (800, 600))
        with patch("computer_mcp.ocr_ext._print_window", return_value=(image, 100, 1200)), \
                patch.object(W, "_bounds_of",
                             return_value=({"x": 100, "y": 1200, "width": 800, "height": 600},
                                           "window")), \
                patch.object(W, "_register_frame", return_value="f_test", create=True), \
                patch.object(O, "screen_bounds", return_value=SCREEN):
            with patch("computer_mcp.core.screenshot._register_frame", return_value="f_test"):
                result = W.screenshot_window(99)
        self.assertTrue(result["success"])
        self.assertTrue(result["clipped_by_screen"])
        self.assertEqual(result["visible_rect"]["h"], 240)
        self.assertGreater(result["offscreen_px"], 0)

    def test_a_fully_visible_window_is_not_flagged(self):
        from PIL import Image

        image = Image.new("RGB", (800, 600))
        with patch("computer_mcp.ocr_ext._print_window", return_value=(image, 100, 100)), \
                patch.object(W, "_bounds_of",
                             return_value=({"x": 100, "y": 100, "width": 800, "height": 600},
                                           "window")), \
                patch.object(O, "screen_bounds", return_value=SCREEN):
            with patch("computer_mcp.core.screenshot._register_frame", return_value="f_test"):
                result = W.screenshot_window(99)
        self.assertFalse(result["clipped_by_screen"])
        self.assertEqual(result["offscreen_px"], 0)


if __name__ == "__main__":
    unittest.main()
