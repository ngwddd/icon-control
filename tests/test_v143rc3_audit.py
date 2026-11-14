"""v1.4.3rc3: absence needs a complete scan, lazy siblings, virtual desktop, identity."""
import unittest
from unittest.mock import Mock, patch

from authority_fixture import AuthorityCase
from computer_mcp import snapshots as S
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
        self.sibling_reads = 0

    @property
    def BoundingRectangle(self):
        left, top, right, bottom = self._rect
        return Mock(left=left, top=top, width=lambda: right - left, height=lambda: bottom - top)

    def GetChildren(self):
        raise AssertionError("the walk must not materialise children when it can stream them")

    def GetFirstChildControl(self):
        return self._children[0] if self._children else None

    def GetNextSiblingControl(self):
        parent = getattr(self, "_parent", None)
        if parent is None:
            return None
        index = parent._children.index(self)
        parent.sibling_reads += 1
        return parent._children[index + 1] if index + 1 < len(parent._children) else None


def attach_parents(control):
    for child in control._children:
        child._parent = control
        attach_parents(child)
    return control


def wide_tree(count=900):
    leaves = [FakeControl(f"Leaf{i}", "ListItemControl", (0, i, 10, 10)) for i in range(count)]
    list_control = FakeControl("List", "ListControl", (0, 0, 100, 900), leaves)
    root = FakeControl("Window", "WindowControl", (0, 0, 400, 900), [list_control])
    return attach_parents(root), list_control


class LazyChildrenTests(unittest.TestCase):
    def test_a_miss_stops_without_enumerating_the_whole_list(self):
        root, list_control = wide_tree(900)
        with patch.object(U, "_UIA_OK", True), \
                patch.object(U, "_control_from", return_value=root):
            result = raw_find(name="NoSuchControl", max_nodes=50, max_hits=10)
        self.assertEqual(result["visited"], 50)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["truncated_reason"], "max_nodes")
        self.assertLess(list_control.sibling_reads, 60,
                        "a spent budget must stop the sibling enumeration")

    def test_a_complete_scan_marks_itself_complete(self):
        root, _ = wide_tree(5)
        with patch.object(U, "_UIA_OK", True), \
                patch.object(U, "_control_from", return_value=root):
            result = raw_find(name="NoSuchControl", max_nodes=400)
        self.assertEqual(result["found"], 0)
        self.assertTrue(result["scan_complete"])
        self.assertEqual(result["scan_errors"], 0)

    def test_a_broken_subtree_makes_the_scan_incomplete(self):
        root, list_control = wide_tree(4)
        stem = list_control._children[0]

        def explode(self):
            raise RuntimeError("uia read failed")

        stem.GetFirstChildControl = explode.__get__(stem)
        with patch.object(U, "_UIA_OK", True), \
                patch.object(U, "_control_from", return_value=root):
            result = raw_find(name="NoSuchControl", max_nodes=400)
        self.assertEqual(result["found"], 0)
        self.assertGreaterEqual(result["scan_errors"], 1)
        self.assertFalse(result["scan_complete"],
                         "an unreadable subtree cannot prove absence")


class PresenceVerdictTests(unittest.TestCase):
    """found=0 from a truncated scan is unknown, never "absent"."""

    def verdict(self, **found):
        from computer_mcp.zones.dispatch import _presence_from_scan

        return _presence_from_scan(dict(ok=True, found=0, **found))

    def test_truncated_scan_is_unknown(self):
        self.assertIsNone(self.verdict(truncated=True, truncated_reason="max_nodes",
                                       visited=400, scan_complete=False, scan_errors=0))

    def test_errorful_scan_is_unknown(self):
        self.assertIsNone(self.verdict(truncated=False, visited=120,
                                       scan_complete=False, scan_errors=2))

    def test_complete_scan_proves_absence(self):
        self.assertFalse(self.verdict(truncated=False, visited=120,
                                      scan_complete=True, scan_errors=0))

    def test_a_hit_proves_presence_even_when_truncated(self):
        from computer_mcp.zones.dispatch import _presence_from_scan

        self.assertTrue(_presence_from_scan(dict(ok=True, found=1, truncated=True,
                                                 scan_complete=False, scan_errors=0)))

    def test_an_error_result_proves_nothing(self):
        from computer_mcp.zones.dispatch import _presence_from_scan

        self.assertIsNone(_presence_from_scan({"ok": False, "error": "boom"}))

    def test_old_result_shape_falls_back_to_flags(self):
        self.assertIsNone(self.verdict(truncated=True))
        self.assertFalse(self.verdict(truncated=False))


class VirtualDesktopTests(unittest.TestCase):
    def test_a_secondary_screen_left_of_the_primary_is_not_rejected(self):
        from computer_mcp import vision_state as VS

        metrics = {76: -1920, 77: 0, 78: 4480, 79: 1440}
        with patch("win32api.GetSystemMetrics", side_effect=lambda index: metrics.get(index, 0)):
            bounds = VS._screen_rect(None)
        self.assertEqual(bounds, {"x": -1920, "y": 0, "w": 4480, "h": 1440})


class IdentityTests(unittest.TestCase):
    """with_ids=false stays a pure observation shortcut (no extra restriction)."""

    def test_a_tree_with_paths_stays_resolvable_even_without_ids(self):
        nodes = [{"path": "0/1", "name": "Button", "type": "ButtonControl",
                  "x": 1, "y": 1, "w": 5, "h": 5}]
        with patch.object(S, "window_identity", return_value=(1, 2, 3.0, "p", (0, 0, 100, 100), 96)), \
                patch.object(S, "screen_fingerprint", return_value=""):
            attached = S.attach(1, nodes)
        self.assertTrue(attached["resolvable"],
                        "dropping the id read must not turn every reference into a visual one")

    def test_an_id_tree_is_resolvable(self):
        nodes = [{"path": "0/1", "name": "Button", "type": "ButtonControl",
                  "x": 1, "y": 1, "w": 5, "h": 5, "automation_id": "okBtn"}]
        with patch.object(S, "window_identity", return_value=(1, 2, 3.0, "p", (0, 0, 100, 100), 96)), \
                patch.object(S, "screen_fingerprint", return_value=""):
            attached = S.attach(1, nodes)
        self.assertTrue(attached["resolvable"])


if __name__ == "__main__":
    unittest.main()
