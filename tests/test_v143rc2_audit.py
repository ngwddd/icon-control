"""v1.4.3rc2 audit fixes: visit budget, index past max_hits, ROI clipping."""
import unittest
from unittest.mock import Mock, patch

import numpy as np

from computer_mcp import ui_ext as U
from computer_mcp import vision_state as VS

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


def wide_tree(count=900):
    leaves = [FakeControl(f"Leaf{i}", "ListItemControl", (0, i, 10, 10)) for i in range(count)]
    return FakeControl("Window", "WindowControl", (0, 0, 400, 900),
                       [FakeControl("List", "ListControl", (0, 0, 100, 900), leaves)])


class VisitBudgetTests(unittest.TestCase):
    def test_a_miss_still_stops_at_max_nodes(self):
        root = wide_tree(900)
        with patch.object(U, "_UIA_OK", True), \
                patch.object(U, "_control_from", return_value=root):
            result = raw_find(name="NoSuchControl", max_nodes=50, max_hits=10)
        self.assertEqual(result["found"], 0)
        self.assertEqual(result["visited"], 50, "max_nodes must bound the walk, not the hits")
        self.assertTrue(result["truncated"])
        self.assertEqual(result["truncated_reason"], "max_nodes")

    def test_a_full_match_reports_why_it_stopped(self):
        root = wide_tree(30)
        with patch.object(U, "_UIA_OK", True), \
                patch.object(U, "_control_from", return_value=root):
            result = raw_find(name="Leaf", max_nodes=400, max_hits=5)
        self.assertEqual(result["found"], 5)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["truncated_reason"], "max_hits")

    def test_a_complete_search_is_not_truncated(self):
        root = wide_tree(3)
        with patch.object(U, "_UIA_OK", True), \
                patch.object(U, "_control_from", return_value=root):
            result = raw_find(name="Leaf", max_nodes=400, max_hits=10)
        self.assertEqual(result["found"], 3)
        self.assertFalse(result["truncated"])
        self.assertIsNone(result["truncated_reason"])


class IndexPastMaxHitsTests(unittest.TestCase):
    def setUp(self):
        buttons = [FakeControl("确定", "ButtonControl", (0, i * 20, 60, 18)) for i in range(15)]
        self.root = FakeControl("Dialog", "WindowControl", (0, 0, 200, 400),
                                [FakeControl("Pane", "PaneControl", (0, 0, 200, 400), buttons)])
        patch.object(U, "_UIA_OK", True).start()
        patch.object(U, "_control_from", return_value=self.root).start()
        self.addCleanup(patch.stopall)

    def test_every_index_is_reachable_with_defaults(self):
        for index in (0, 9, 10, 12, 14):
            result = raw_find(name="确定", index=index)
            self.assertIsNotNone(result["target"], f"index {index} should resolve")
            self.assertEqual(result["target"]["y"], index * 20)

    def test_index_beyond_the_tree_returns_none_not_an_error(self):
        result = raw_find(name="确定", index=40)
        self.assertTrue(result["ok"])
        self.assertIsNone(result["target"])


class RoiClippingTests(unittest.TestCase):
    """The audit's two shapes: partially outside, and fully outside the window."""

    def setUp(self):
        rng = np.random.default_rng(5)
        self.template = (rng.random((16, 24)) * 255).astype(np.uint8)
        self.window = np.zeros((200, 300), dtype=np.uint8)
        # marker at window-relative (40, 30) -> screen (140, 130) for a window at (100, 100)
        self.window[30:46, 40:64] = self.template
        patch.object(VS, "_load_template", return_value=(self.template, {})).start()
        patch.object(VS, "_screen_rect",
                     return_value={"x": 100, "y": 100, "w": 300, "h": 200}).start()
        self.addCleanup(patch.stopall)

    def run_region(self, **kwargs):
        def fake_gray(region, hwnd=None):
            if not region:
                return self.window
            # _gray crops the window grab at the (clipped) region offset
            x, y = int(region["x"]) - 100, int(region["y"]) - 100
            return self.window[max(0, y):max(0, y) + int(region["h"]),
                               max(0, x):max(0, x) + int(region["w"])]

        with patch.object(VS, "_gray", side_effect=fake_gray):
            return VS.match_template("fixture", hwnd=1, **kwargs)

    def test_partially_outside_region_is_clipped_and_reports_screen_coordinates(self):
        # starts 10 px left of the window: the marker is at window x=40
        result = self.run_region(search_region={"x": 90, "y": 100, "w": 120, "h": 120})
        self.assertTrue(result["found"])
        self.assertEqual(result["search_rect"][0], 100, "search rect must be clipped to the window")
        self.assertEqual(result["center"], [140 + 12, 130 + 8])

    def test_fully_outside_region_is_refused(self):
        result = self.run_region(search_region={"x": 900, "y": 900, "w": 100, "h": 100})
        self.assertFalse(result["success"])
        self.assertIn("没有交集", result["error"])

    def test_search_region_wins_over_previous(self):
        result = self.run_region(search_region={"x": 100, "y": 100, "w": 120, "h": 120},
                                 previous=[500, 500], radius=30)
        self.assertTrue(result["found"])
        self.assertEqual(result["search_rect"], [100, 100, 120, 120])

    def test_refused_lock_has_no_clickable_coordinates(self):
        blank = np.zeros((200, 300), dtype=np.uint8)

        def fake_gray(region, hwnd=None):
            return blank

        with patch.object(VS, "_gray", side_effect=fake_gray):
            result = VS.match_template("fixture", hwnd=1, confidence=0.8)
        self.assertFalse(result["found"])
        for key in ("x", "y", "center"):
            self.assertNotIn(key, result, f"{key} must not look clickable when found=false")
        self.assertIn("candidate", result, "the best pixel match still belongs in diagnostics")


if __name__ == "__main__":
    unittest.main()
