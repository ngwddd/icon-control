"""v1.4.4rc2: errors reach the caller, click_text refuses to guess, focus tells the truth."""
import unittest
from unittest.mock import Mock, patch

from authority_fixture import AuthorityCase
from computer_mcp import ocr_ext as O
from computer_mcp.core.argument_error import ArgumentError

SCREEN = {"x": 0, "y": 0, "w": 2560, "h": 1440}


def matches(*items):
    return {"ok": True, "found": len(items), "screen": SCREEN,
            "matches": [dict(text=text, cx=cx, cy=cy, w=100, h=30, ratio=1.0,
                             slack=0, onscreen=onscreen)
                        for text, cx, cy, onscreen in items]}


class ErrorPayloadTests(unittest.TestCase):
    def test_an_argument_error_carries_code_hint_and_numbers(self):
        error = ArgumentError("boom", code="out_of_screen", hint="maximise",
                              point=[1, 2], screen=SCREEN)
        payload = error.payload("click")
        self.assertEqual(payload["code"], "out_of_screen")
        self.assertEqual(payload["hint"], "maximise")
        self.assertEqual(payload["data"]["point"], [1, 2])
        self.assertFalse(payload["success"])
        self.assertEqual(payload["tool"], "click")

    def test_the_mcp_layer_returns_it_instead_of_masking(self):
        import asyncio
        import json

        from computer_mcp import mcp as M

        def boom(name, arguments, **kwargs):
            raise ArgumentError("click point (1, 2) is outside the screen",
                                code="out_of_screen", hint="maximise the window")

        with patch.object(M, "_dispatch", side_effect=boom), \
                patch("computer_mcp.permission.check_tool", return_value=None):
            result = asyncio.run(M._call_tool_impl("click", {"x": 1, "y": 2}))
        body = json.loads(result[0].text)
        self.assertEqual(body["code"], "out_of_screen")
        self.assertIn("outside the screen", body["error"])
        self.assertEqual(body["hint"], "maximise the window")

    def test_other_exceptions_stay_masked(self):
        import asyncio
        import json

        from computer_mcp import mcp as M

        def boom(name, arguments, **kwargs):
            raise RuntimeError("typed secret text")

        with patch.object(M, "_dispatch", side_effect=boom), \
                patch("computer_mcp.permission.check_tool", return_value=None):
            result = asyncio.run(M._call_tool_impl("type", {"text": "secret"}))
        body = json.loads(result[0].text)
        self.assertEqual(body["error"], "Tool execution failed")
        self.assertNotIn("secret", json.dumps(body))


raw_click_text = getattr(O.click_text, "__wrapped__", O.click_text)


class ClickTextRefusalTests(unittest.TestCase):
    def setUp(self):
        # These tests cover OCR candidate selection. Native execution is covered
        # separately by pointer-contract tests and the real-HWND fault probe.
        from computer_mcp import pointer_contract as P
        self.binding = P.WindowBinding(42, {'pid': 123}, (0, 0, 2560, 1440))
        for item in (patch.object(P, 'bind_window', return_value=self.binding),
                     patch('win32gui.WindowFromPoint', return_value=42),
                     patch('win32gui.GetAncestor', return_value=42)):
            item.start()
            self.addCleanup(item.stop)
        item = patch.object(P, 'click_at', return_value={'outcome': 'executed_unverified'})
        self.executor = item.start()
        self.addCleanup(item.stop)

    def test_identical_candidates_are_ambiguous_not_guessed(self):
        mouse = Mock()
        data = matches(("Confirm", 500, 315, True), ("Confirm", 500, 415, True))
        with patch.object(O, "find_text", return_value=data):
            result = raw_click_text("Confirm", mouse=mouse)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ambiguous_target")
        mouse.click.assert_not_called()

    def test_an_explicit_index_resolves_the_ambiguity(self):
        mouse = Mock()
        data = matches(("Confirm", 500, 315, True), ("Confirm", 500, 415, True))
        with patch.object(O, "find_text", return_value=data):
            result = raw_click_text("Confirm", mouse=mouse, index=1)
        self.assertTrue(result["ok"])
        self.assertEqual(result["chosen_index"], 1)
        self.assertEqual(self.executor.call_args.args[1], (500, 415))

    def test_a_negative_index_is_rejected(self):
        mouse = Mock()
        data = matches(("Confirm", 500, 315, True), ("Confirm", 500, 415, True))
        with patch.object(O, "find_text", return_value=data):
            result = raw_click_text("Confirm", mouse=mouse, index=-1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "invalid_index")
        mouse.click.assert_not_called()

    def test_an_off_screen_candidate_never_wins_over_a_visible_one(self):
        mouse = Mock()
        data = matches(("Confirm", 500, 1515, False), ("Confirm", 500, 415, True))
        with patch.object(O, "find_text", return_value=data):
            result = raw_click_text("Confirm", mouse=mouse)
        self.assertTrue(result["ok"])
        self.assertEqual(result["chosen_index"], 1)
        self.assertEqual(self.executor.call_args.args[1], (500, 415))

    def test_every_candidate_off_screen_is_refused(self):
        mouse = Mock()
        data = matches(("Confirm", 500, 1515, False))
        with patch.object(O, "find_text", return_value=data):
            result = raw_click_text("Confirm", mouse=mouse)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "offscreen_target")
        mouse.click.assert_not_called()

    def test_a_point_owned_by_another_window_is_refused(self):
        mouse = Mock()
        data = matches(("Confirm", 500, 415, True))
        with patch.object(O, "find_text", return_value=data), \
                patch("win32gui.WindowFromPoint", return_value=777), \
                patch("win32gui.GetAncestor", return_value=777):
            result = raw_click_text("Confirm", mouse=mouse, hwnd=42)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "target_occluded")
        mouse.click.assert_not_called()

    def test_the_click_is_bound_to_the_window(self):
        mouse = Mock()
        data = matches(("Confirm", 500, 415, True))
        with patch.object(O, "find_text", return_value=data), \
                patch("win32gui.WindowFromPoint", return_value=42), \
                patch("win32gui.GetAncestor", return_value=42):
            result = raw_click_text("Confirm", mouse=mouse, hwnd=42)
        self.assertTrue(result["ok"])
        self.assertIs(self.executor.call_args.kwargs["binding"], self.binding)
        self.assertEqual(self.executor.call_args.args[1], (500, 415))


class FocusSemanticsTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def test_a_refused_focus_is_not_success(self):
        from computer_mcp.actions import window as W

        with patch("win32gui.IsWindow", return_value=True), \
                patch("win32gui.IsIconic", return_value=False), \
                patch("win32gui.BringWindowToTop"), \
                patch("win32gui.SetForegroundWindow", side_effect=RuntimeError("denied")), \
                patch("win32gui.GetForegroundWindow", return_value=7), \
                patch("win32gui.GetWindowText", return_value="other"), \
                patch("win32gui.GetWindowRect", return_value=(0, 0, 800, 600)), \
                patch("win32process.GetWindowThreadProcessId", return_value=(2, 7)), \
                patch("ctypes.windll.user32.AttachThreadInput", create=True), \
                patch("ctypes.windll.kernel32.GetCurrentThreadId", return_value=1, create=True):
            result = W.focus_window(42)
        self.assertFalse(result["success"])
        self.assertFalse(result["focused"])
        self.assertEqual(result["status"], "focus_denied")
        self.assertIn("next_action", result)

    def test_the_thread_id_fallback_uses_the_right_module(self):
        from computer_mcp.actions import window as W

        with patch("win32gui.IsWindow", return_value=True), \
                patch("win32gui.IsIconic", return_value=False), \
                patch("win32gui.BringWindowToTop"), \
                patch("win32gui.SetForegroundWindow", side_effect=RuntimeError("denied")), \
                patch("win32gui.GetForegroundWindow", return_value=7), \
                patch("win32gui.GetWindowText", return_value="other"), \
                patch("win32gui.GetWindowRect", return_value=(0, 0, 800, 600)), \
                patch.object(W, "_thread_of", return_value=5), \
                patch.object(W, "_attach_and_focus", return_value=True):
            result = W.focus_window(42)
        self.assertIn("attach_thread_input", result["attempts"])

    def test_thread_of_reads_the_pid_module(self):
        from computer_mcp.actions import window as W

        with patch("win32process.GetWindowThreadProcessId", return_value=(5, 9)):
            self.assertEqual(W._thread_of(42), 5)


class WaitForTemplateTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def test_a_matched_template_ends_the_wait(self):
        from computer_mcp.zones import wait_for as WF

        with patch("computer_mcp.vision_state.wait_template",
                   return_value={"success": True, "matched": True}), \
                patch("computer_mcp.vision_state.match_template",
                      return_value={"success": True, "found": True}):
            result = WF.run(kind="template", query="btn", timeout_ms=200)
        self.assertTrue(result.get("ok"), result)
        self.assertTrue((result.get("match") or {}).get("matched"))


if __name__ == "__main__":
    unittest.main()
