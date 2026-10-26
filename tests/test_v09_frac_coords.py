# -*- coding: utf-8 -*-
"""按比例坐标（rel_frac / region_frac）的单测。

守的是"同一个宏在任何窗口尺寸下都点对"这件事 —— 微信的 type_verified
就是因为写死像素、窗口从 600x700 变成 1566x1054 后整体偏移而失败的。
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "venv", "Lib", "site-packages"))

try:
    from computer_mcp import macro_ext as M
    HAVE = True
except Exception:
    HAVE = False

NEED = unittest.skipUnless(HAVE, "导不进 computer_mcp（需要 venv）")

WIN_SMALL = {"x": 100, "y": 200, "w": 600, "h": 700,
             "rect_x": 94, "rect_y": 169, "rect_w": 612, "rect_h": 731}
WIN_LARGE = {"x": 0, "y": 0, "w": 1566, "h": 1054,
             "rect_x": -11, "rect_y": 175, "rect_w": 1588, "rect_h": 1085}


@NEED
class TestRelFrac(unittest.TestCase):
    def test_center_scales(self) -> None:
        step = {"rel_frac": [0.5, 0.5]}
        a = M._resolve_point(step, WIN_SMALL)
        b = M._resolve_point(step, WIN_LARGE)
        self.assertEqual(a, (94 + 306, 169 + 365))
        # round() 是银行家舍入：0.5*1085=542.5 → 717.5 → 718
        self.assertEqual(b, (-11 + 794, 175 + 543))
        self.assertNotEqual(a, b)

    def test_absolute_rel_unchanged(self) -> None:
        step = {"rel": [50, 60]}
        self.assertEqual(M._resolve_point(step, WIN_SMALL), (94 + 50, 169 + 60))

    def test_br_anchor_still_works(self) -> None:
        step = {"rel": [-100, -50], "anchor": "br"}
        self.assertEqual(M._resolve_point(step, WIN_SMALL),
                         (94 + 612 - 100, 169 + 731 - 50))

    def test_no_win_returns_none(self) -> None:
        self.assertIsNone(M._resolve_point({"rel_frac": [0.5, 0.5]}, None))


@NEED
class TestRegionFrac(unittest.TestCase):
    def test_region_frac_scales(self) -> None:
        step = {"region_frac": [0.25, 0.75, 0.5, 0.2]}
        r = M._resolve_region(step, WIN_LARGE)
        self.assertEqual(r["x"], int(round(-11 + 0.25 * 1588)))
        self.assertEqual(r["y"], int(round(175 + 0.75 * 1085)))
        self.assertEqual(r["w"], int(round(0.5 * 1588)))
        self.assertEqual(r["h"], max(1, int(round(0.2 * 1085))))

    def test_region_frac_min_one_pixel(self) -> None:
        r = M._resolve_region({"region_frac": [0.9, 0.9, 0.001, 0.001]}, WIN_SMALL)
        self.assertGreaterEqual(r["w"], 1)
        self.assertGreaterEqual(r["h"], 1)

    def test_region_rel_still_works(self) -> None:
        r = M._resolve_region({"region_rel": [10, 20, 300, 40]}, WIN_SMALL)
        self.assertEqual(r, {"x": 94 + 10, "y": 169 + 20, "w": 300, "h": 40})

    def test_br_region_still_works(self) -> None:
        r = M._resolve_region({"region_rel": [40, 30, 540, 300],
                               "region_anchor": "br"}, WIN_SMALL)
        self.assertEqual(r["x"], 94 + 612 - 40 - 540)
        self.assertEqual(r["y"], 169 + 731 - 30 - 300)


if __name__ == "__main__":
    unittest.main()
