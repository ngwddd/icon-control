"""v1.4.3 R1: find during the walk, narrowed by conditions, without paying for ids."""
import unittest
from unittest.mock import Mock, patch

from computer_mcp import ui_ext as U

raw_find = getattr(U.ui_find, "__wrapped__", U.ui_find)


class FakeControl:
    def __init__(self, name, ctype, rect, children=(), automation_id="", enabled=True):
        self.Name = name
        self.ControlTypeName = ctype
        self.AutomationId = automation_id
        self.IsEnabled = enabled
        self._rect = rect
        self._children = list(children)

    @property
    def BoundingRectangle(self):
        left, top, right, bottom = self._rect
        return Mock(left=left, top=top, width=lambda: right - left, height=lambda: bottom - top)

    def GetChildren(self):
        return self._children


def build():
    ok = FakeControl("OK", "ButtonControl", (10, 10, 70, 40), automation_id="okBtn")
    cancel = FakeControl("Cancel", "ButtonControl", (90, 10, 70, 40), automation_id="cancelBtn")
    pane = FakeControl("Pane", "PaneControl", (0, 0, 300, 100), [ok, cancel])
    address = FakeControl("地址栏", "EditControl", (0, 120, 300, 24), automation_id="TextBox")
    root = FakeControl("Window", "WindowControl", (0, 0, 300, 200), [pane, address])
    return root, ok, cancel, address


class FindBehaviourTests(unittest.TestCase):
    def setUp(self):
        self.root, self.ok, self.cancel, self.address = build()
        patch.object(U, "_UIA_OK", True).start()
        patch.object(U, "_control_from", return_value=self.root).start()
        self.addCleanup(patch.stopall)

    def test_conditions_narrow_by_control_type(self):
        typed = raw_find(name="OK", control_type="Button")
        self.assertTrue(typed["target"])
        self.assertEqual(typed["target"]["type"], "ButtonControl")
        wrong = raw_find(name="OK", control_type="EditControl")
        self.assertEqual(wrong["found"], 0)

    def test_conditions_narrow_by_automation_id(self):
        hit = raw_find(name="OK", automation_id="okBtn")
        self.assertEqual(hit["found"], 1)
        self.assertEqual(hit["target"]["automation_id"], "okBtn")
        self.assertEqual(raw_find(name="OK", automation_id="nope")["found"], 0)

    def test_conditions_narrow_by_enabled_state(self):
        self.ok.IsEnabled = False
        self.assertEqual(raw_find(name="OK", enabled=False)["found"], 1)
        self.assertEqual(raw_find(name="OK", enabled=True)["found"], 0)

    def test_found_is_marked_truncated_when_it_stops_early(self):
        many = [FakeControl("Item", "ListItemControl", (0, i * 10, 10, 10)) for i in range(30)]
        self.root._children = [FakeControl("List", "ListControl", (0, 0, 100, 400), many)]
        early = raw_find(name="Item", max_hits=5)
        self.assertTrue(early["truncated"])
        self.assertEqual(early["found"], 5)
        full = raw_find(name="Item", max_hits=100)
        self.assertFalse(full["truncated"])
        self.assertEqual(full["found"], 30)

    def test_truncated_is_false_when_every_match_fits(self):
        result = raw_find(name="Button", max_hits=10)   # matches via "Cancel"? no: names differ
        self.assertFalse(result["truncated"])


class IdLazinessTests(unittest.TestCase):
    def test_walk_skips_automation_id_when_asked(self):
        root, _, _, _ = build()
        plain = []
        U._walk(root, 4, plain, 100, only_named=True, want_id=False)
        self.assertTrue(all(node["automation_id"] == "" for node in plain))
        with_ids = []
        U._walk(root, 4, with_ids, 100, only_named=True, want_id=True)
        self.assertTrue(any(node["automation_id"] for node in with_ids))

    def test_ui_find_does_not_read_ids_unless_a_condition_needs_them(self):
        root, _, _, _ = build()
        with patch.object(U, "_UIA_OK", True), \
                patch.object(U, "_control_from", return_value=root):
            plain = raw_find(name="OK")
            narrowed = raw_find(name="OK", automation_id="okBtn")
        self.assertTrue(all(node["automation_id"] == "" for node in plain["candidates"]))
        self.assertEqual(narrowed["target"]["automation_id"], "okBtn")


class OcrScoreTests(unittest.TestCase):
    def test_missing_ratio_is_neutral_not_perfect(self):
        from computer_mcp.zones import sense_fallback as F

        fake = {"hits": [{"text": "保存", "x": 1, "y": 2, "w": 30, "h": 12}]}
        with patch("computer_mcp.ui_ext.ui_find",
                   return_value={"ok": True, "found": 0, "candidates": []}), \
                patch("computer_mcp.ocr_ext.find_text", return_value=fake):
            result = F.find_element("保存", hwnd=1)
        ocr = [item for item in result.get("candidates", []) if item.get("source") == "ocr"]
        self.assertTrue(ocr, result)
        self.assertLess(ocr[0]["score"], 0.95,
                        "a missing ratio must not outrank a UIA exact hit")
        self.assertTrue(ocr[0].get("ratio_missing"))


if __name__ == "__main__":
    unittest.main()
