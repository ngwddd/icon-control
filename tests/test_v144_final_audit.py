"""v1.4.4 final: the recognition→injection chain, tested at the MCP boundary."""
import asyncio
import json
import unittest
from unittest.mock import Mock, patch

from authority_fixture import AuthorityCase
from computer_mcp import input_guard as G
from computer_mcp import mcp as M
from computer_mcp import ocr_ext as O
from computer_mcp import ui_ext as U
from computer_mcp import vision_state as VS

SCREEN = {"x": 0, "y": 0, "w": 2560, "h": 1440}


def call_tool(name, arguments):
    with patch("computer_mcp.permission.check_tool", return_value=None):
        out = asyncio.run(M._call_tool_impl(name, dict(arguments)))
    for item in out:
        text = getattr(item, "text", None)
        if text:
            try:
                return json.loads(text)
            except Exception:                           # noqa: BLE001
                continue
    return {}


class DispatchPlumbingTests(unittest.TestCase):
    """The tool layer must not overwrite what the functions need to refuse."""

    def test_click_text_reaches_the_function_without_index(self):
        sentinel = {"success": True, "ok": True, "clicked_text": "x", "chosen_index": 0}
        with patch.object(O, "click_text", return_value=sentinel) as fake:
            call_tool("click_text", {"query": "Confirm", "hwnd": 42})
        self.assertIsNone(fake.call_args.kwargs["index"],
                          "index must stay None so the automatic path can refuse ambiguity")
        self.assertEqual(fake.call_args.kwargs["hwnd"], 42)

    def test_an_explicit_index_still_passes_through(self):
        with patch.object(O, "click_text", return_value={"ok": True}) as fake:
            call_tool("click_text", {"query": "Confirm", "index": 2})
        self.assertEqual(fake.call_args.kwargs["index"], 2)

    def test_click_template_receives_the_region(self):
        with patch.object(VS, "click_template", return_value={"success": True}) as fake:
            call_tool("click_template", {"name": "btn", "x": 1, "y": 2, "w": 30, "h": 40})
        self.assertEqual(fake.call_args.kwargs["region"], {"x": 1, "y": 2, "w": 30, "h": 40})


raw_click_template = getattr(VS.click_template, "__wrapped__", VS.click_template)
raw_ui_click = getattr(U.ui_click, "__wrapped__", U.ui_click)


class InjectedClickBindingTests(unittest.TestCase):

    def test_click_template_binds_the_press_to_the_window(self):
        mouse = Mock()
        match = {"success": True, "found": True, "center": [500, 400], "score": 0.99}
        with patch.object(VS, "match_template", return_value=match):
            result = raw_click_template("btn", mouse=mouse, hwnd=42)
        self.assertTrue(result["success"])
        self.assertEqual(mouse.press.call_args.kwargs.get("expected_hwnd"), 42)
        self.assertEqual(mouse.press.call_args.kwargs.get("expected_point"), (500, 400))
        mouse.release.assert_called_once()

    def test_ui_click_right_presses_the_right_button(self):
        from pynput.mouse import Button

        mouse = Mock()
        target = {"name": "Row", "type": "ListItemControl", "cx": 100, "cy": 200}
        with patch.object(U, "_resolve", return_value=(target, {})), \
                patch("computer_mcp.winutil.point_owner", return_value=42):
            raw_ui_click("Row", hwnd=42, button="right", mouse=mouse)
        self.assertEqual(mouse.click.call_args.args[0], Button.right)

    def test_ui_click_middle_presses_the_middle_button(self):
        from pynput.mouse import Button

        mouse = Mock()
        target = {"name": "Row", "type": "ListItemControl", "cx": 100, "cy": 200}
        with patch.object(U, "_resolve", return_value=(target, {})), \
                patch("computer_mcp.winutil.point_owner", return_value=42):
            raw_ui_click("Row", hwnd=42, button="middle", mouse=mouse)
        self.assertEqual(mouse.click.call_args.args[0], Button.middle)

    def test_ui_click_binds_the_press_to_the_window(self):
        mouse = Mock()
        target = {"name": "Row", "type": "ListItemControl", "cx": 100, "cy": 200}
        with patch.object(U, "_resolve", return_value=(target, {})), \
                patch("computer_mcp.winutil.point_owner", return_value=42):
            raw_ui_click("Row", hwnd=42, mouse=mouse)
        self.assertEqual(mouse.click.call_args.kwargs.get("expected_hwnd"), 42)


class PointerDriftTests(unittest.TestCase):
    def controller(self, position=(100, 100)):
        controller = G.MouseController.__new__(G.MouseController)
        controller.raw = Mock(position=position, press=Mock(), release=Mock(), scroll=Mock())
        controller.held = set()
        controller._mutex = __import__("threading").RLock()
        return controller

    def test_a_pointer_that_drifted_is_refused_without_a_process_identity(self):
        controller = self.controller((140, 100))          # moved 40 px inside the window
        with patch.object(G, "check"), patch.object(G, "_retain"), \
                patch("win32gui.WindowFromPoint", return_value=42), \
                patch("win32gui.GetAncestor", return_value=42), \
                patch("win32process.GetWindowThreadProcessId", return_value=(1, 2)), \
                patch("computer_mcp.capabilities.require_target"):
            with self.assertRaises(Exception) as caught:
                controller.press("left", expected_point=(100, 100), expected_hwnd=42)
        self.assertIn("expected point", str(caught.exception))
        controller.raw.press.assert_not_called()


class TemplateWaitVerdictTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def test_ambiguity_is_never_reported_as_absent(self):
        ambiguous = {"success": True, "found": False, "reason": "ambiguous", "score": 0.9}
        with patch.object(VS, "match_template", return_value=ambiguous):
            result = VS.wait_template("btn", timeout_ms=120, poll_ms=30, appear=False)
        self.assertFalse(result["matched"])
        self.assertEqual(result["verdict"], "inconclusive")

    def test_a_clear_absence_is_still_absent(self):
        gone = {"success": True, "found": False, "reason": "below_threshold", "score": 0.1}
        with patch.object(VS, "match_template", return_value=gone):
            result = VS.wait_template("btn", timeout_ms=120, poll_ms=30, appear=False)
        self.assertTrue(result["matched"])
        self.assertEqual(result["verdict"], "absent")


class OcrRegionTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def test_a_partial_region_is_refused(self):
        result = O.find_text("Save", region={"x": 1, "y": 2, "w": 30})
        self.assertFalse(result.get("ok"))
        self.assertEqual(result["code"], "invalid_argument")

    def test_a_full_region_is_accepted(self):
        with patch.object(O, "ocr_read", return_value={"ok": True, "count": 0, "lines": [],
                                                       "screen": SCREEN, "ms": 1.0}):
            result = O.find_text("Save", region={"x": 1, "y": 2, "w": 30, "h": 40})
        self.assertTrue(result["ok"])

    def test_ownership_failure_never_falls_back_to_an_unbound_click(self):
        mouse = Mock()
        data = {"ok": True, "found": 1, "screen": SCREEN, "matches": [
            dict(text="Confirm", cx=400, cy=300, w=80, h=24, ratio=1.0, slack=0, onscreen=True)]}
        raw = getattr(O.click_text, "__wrapped__", O.click_text)
        with patch.object(O, "find_text", return_value=data), \
                patch("win32gui.WindowFromPoint", side_effect=RuntimeError("boom")):
            result = raw("Confirm", mouse=mouse, hwnd=42)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "target_unverified")
        mouse.click.assert_not_called()


class VirtualDesktopSearchTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def test_a_template_search_without_a_region_covers_every_monitor(self):
        captured = {}

        class FakeSct:
            monitors = [{"left": 0, "top": 0, "width": 2560, "height": 1440},
                        {"left": 0, "top": 0, "width": 2560, "height": 1440}]

            def grab(self, box):
                captured.update(box)
                shot = Mock()
                shot.size = (box["width"], box["height"])
                shot.bgra = bytes(box["width"] * box["height"] * 4)
                return shot

        virtual = {"x": -1920, "y": 0, "w": 4480, "h": 1440}
        with patch.object(O, "_sct", return_value=FakeSct()), \
                patch.object(O, "screen_bounds", return_value=virtual), \
                patch("computer_mcp.permission.require"):
            O._grab_screen(None)
        self.assertEqual(captured["left"], -1920)
        self.assertEqual(captured["width"], 4480)


if __name__ == "__main__":
    unittest.main()
