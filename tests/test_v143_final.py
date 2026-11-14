"""v1.4.3 final: the window identity must gate the injection, and depth is not proof."""
import unittest
from unittest.mock import Mock, patch

from computer_mcp import input_guard as G
from computer_mcp import ui_ext as U

raw_find = getattr(U.ui_find, "__wrapped__", U.ui_find)


class FakeControl:
    def __init__(self, name, ctype, rect, children=(), automation_id=""):
        self.Name = name
        self.ControlTypeName = ctype
        self.AutomationId = automation_id
        self.IsEnabled = True
        self._rect = rect
        self._children = list(children)

    @property
    def BoundingRectangle(self):
        left, top, right, bottom = self._rect
        return Mock(left=left, top=top, width=lambda: right - left, height=lambda: bottom - top)

    def GetChildren(self):
        return self._children

    def GetFirstChildControl(self):
        return self._children[0] if self._children else None


def nested_tree(levels: int, target_name: str = "Deep"):
    """A chain: root -> level1 -> ... -> levelN, with the target at the bottom."""
    node = FakeControl(target_name, "ButtonControl", (0, 0, 10, 10))
    for depth in range(levels, 0, -1):
        node = FakeControl(f"Level{depth}", "PaneControl", (0, 0, 100, 100), [node])
    root = FakeControl("Window", "WindowControl", (0, 0, 400, 400), [node])
    return root


class DepthProofTests(unittest.TestCase):
    def find(self, root, **kwargs):
        with patch.object(U, "_UIA_OK", True), \
                patch.object(U, "_control_from", return_value=root):
            return raw_find(name="Deep", **kwargs)

    def test_a_target_beyond_the_depth_is_not_reported_absent(self):
        root = nested_tree(10)
        shallow = self.find(root, depth=8)
        self.assertEqual(shallow["found"], 0)
        self.assertFalse(shallow["scan_complete"],
                         "a depth-limited scan cannot prove the target is gone")
        self.assertTrue(shallow["depth_truncated"])
        deeper = self.find(root, depth=12)
        self.assertEqual(deeper["found"], 1,
                         "the target is reachable when the search is deep enough")

    def test_a_fully_explored_tree_reports_no_depth_cut(self):
        root = nested_tree(3)
        result = self.find(root, depth=12)
        self.assertEqual(result["found"], 1)
        self.assertFalse(result["depth_truncated"])

    def test_the_frontier_without_children_is_a_complete_scan(self):
        root = nested_tree(3)
        empty = self.find(root, depth=12)
        self.assertTrue(empty["scan_complete"])
        self.assertFalse(empty["depth_truncated"])


class WindowGateTests(unittest.TestCase):
    """expected_hwnd alone must be enough to refuse a changed window."""

    def controller(self):
        controller = G.MouseController.__new__(G.MouseController)
        controller.raw = Mock(position=(100, 100), press=Mock(), release=Mock(), scroll=Mock())
        controller.held = set()
        controller._mutex = __import__("threading").RLock()
        return controller

    def test_press_refuses_a_changed_window_without_a_process_record(self):
        controller = self.controller()
        with patch.object(G, "check"), \
                patch.object(G, "_retain"), \
                patch("win32gui.WindowFromPoint", return_value=999), \
                patch("win32gui.GetAncestor", return_value=999), \
                patch("win32process.GetWindowThreadProcessId", return_value=(1, 2)), \
                patch("computer_mcp.capabilities.require_target"):
            with self.assertRaises(Exception) as caught:
                controller.press("left", expected_hwnd=42)
        self.assertIn("window changed", str(caught.exception))
        controller.raw.press.assert_not_called()

    def test_press_allows_the_expected_window(self):
        controller = self.controller()
        with patch.object(G, "check"), \
                patch.object(G, "_retain"), \
                patch("win32gui.WindowFromPoint", return_value=42), \
                patch("win32gui.GetAncestor", return_value=42), \
                patch("win32process.GetWindowThreadProcessId", return_value=(1, 2)), \
                patch("computer_mcp.capabilities.require_target"):
            controller.press("left", expected_hwnd=42)
        controller.raw.press.assert_called_once()

    def test_double_click_passes_the_window_to_every_press(self):
        from computer_mcp.actions import mouse as M

        controller, raw = Mock(), getattr(M.double_click, "__wrapped__", M.double_click)
        controller.position = (0, 0)
        with patch("computer_mcp.core.screenshot.to_physical", return_value=(10, 10)), \
                patch("computer_mcp.core.screenshot.assert_frame_target"), \
                patch("computer_mcp.core.screenshot.frame_target",
                      return_value={"hwnd": 42, "pid": 7, "created": 1.0}):
            raw(controller=controller, frame_id="f_1", x=1, y=1)
        self.assertEqual(controller.click.call_args.kwargs.get("expected_hwnd"), 42)


if __name__ == "__main__":
    unittest.main()
