# -*- coding: utf-8 -*-
"""layout_mem 的单测：标定 → 保存 → 匹配 → 按新尺寸换算成像素。

守的是"通用性 + 可复用"：
    · 同一个应用（标题带不同版本号）必须命中同一档案
    · 窗口缩放后，归一化坐标必须换算成正确的像素框（这是"0 成本复用"的核心）
    · 不合法的区域必须被拒绝，不能悄悄存坏数据
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "venv", "Lib", "site-packages"))

try:
    from computer_mcp import layout_mem as lm
    HAVE = True
except Exception:
    HAVE = False

NEED = unittest.skipUnless(HAVE, "导不进 computer_mcp（需要 venv）")


class _TempStore:
    """把 STORE 指到临时目录，避免污染真实档案。"""

    def __enter__(self):
        self.dir = tempfile.TemporaryDirectory()
        self.old = lm.STORE
        lm.STORE = Path(self.dir.name) / "layouts.json"
        return lm.STORE

    def __exit__(self, *a):
        lm.STORE = self.old
        self.dir.cleanup()


GOOD = {
    "map":    [0.66, 0.55, 0.34, 0.42],
    "prompt": [0.31, 0.73, 0.36, 0.09],
    "bar":    [0.16, 0.82, 0.24, 0.04],
}


@NEED
class TestStem(unittest.TestCase):
    def test_strips_version(self) -> None:
        self.assertEqual(lm.stem("Canity v1.6.5"), "canity")
        self.assertEqual(lm.stem("Canity v1.6.6"), "canity")

    def test_keeps_cjk(self) -> None:
        self.assertIn("图标", lm.stem("图标控制 2.0"))

    def test_empty(self) -> None:
        self.assertEqual(lm.stem(""), "unknown")


@NEED
class TestValidate(unittest.TestCase):
    def test_good_regions_rounded(self) -> None:
        regs, errs = lm.validate_regions(GOOD)
        self.assertEqual(errs, [])
        self.assertEqual(set(regs), set(GOOD))

    def test_rejects_out_of_range(self) -> None:
        _, errs = lm.validate_regions({"map": [1.2, 0.5, 0.3, 0.3]})
        self.assertTrue(errs)

    def test_rejects_overflow(self) -> None:
        _, errs = lm.validate_regions({"map": [0.8, 0.8, 0.4, 0.4]})
        self.assertTrue(errs)

    def test_rejects_zero_size(self) -> None:
        _, errs = lm.validate_regions({"map": [0.1, 0.1, 0.0, 0.2]})
        self.assertTrue(errs)


@NEED
class TestSaveLoad(unittest.TestCase):
    def test_round_trip(self) -> None:
        with _TempStore():
            r = lm.save_profile("Canity v1.6.5", (806, 640), GOOD,
                                meta={"pitch": 11})
            self.assertTrue(r["ok"], r)
            self.assertEqual(r["key"], "canity")
            got = lm.find_profile("Canity v1.6.6")
            self.assertIsNotNone(got, "同应用不同版本没命中")
            self.assertEqual(got["canvas"], [806, 640])
            self.assertIn("map", got["regions"])

    def test_bad_regions_not_saved(self) -> None:
        with _TempStore():
            r = lm.save_profile("X v1", (800, 600), {"map": [2, 0, 0.1, 0.1]})
            self.assertFalse(r["ok"])
            self.assertEqual(lm.list_profiles()["count"], 0)

    def test_other_app_misses(self) -> None:
        with _TempStore():
            lm.save_profile("Canity v1.6.5", (806, 640), GOOD)
            self.assertIsNone(lm.find_profile("Notepad"))
            self.assertIsNone(lm.find_profile(""))

    def test_list_and_delete(self) -> None:
        with _TempStore():
            lm.save_profile("Canity v1.6.5", (806, 640), GOOD)
            self.assertEqual(lm.list_profiles()["count"], 1)
            self.assertTrue(lm.delete_profile("canity")["ok"])
            self.assertEqual(lm.list_profiles()["count"], 0)


@NEED
class TestResolve(unittest.TestCase):
    def test_scale_to_double_canvas(self) -> None:
        """同一个档案，内容区从 806x640 变成 1612x1280 → 像素框必须等比例放大。"""
        prof = {"regions": {"map": [0.5, 0.5, 0.25, 0.25]}}
        a = lm.resolve(prof, (0, 0, 806, 640))
        b = lm.resolve(prof, (0, 0, 1612, 1280))
        self.assertEqual(a["map"][2], 202)      # 0.25 * 806 = 201.5
        self.assertAlmostEqual(b["map"][0], a["map"][0] * 2, delta=1)
        self.assertAlmostEqual(b["map"][2], a["map"][2] * 2, delta=1)

    def test_origin_offset_applied(self) -> None:
        prof = {"regions": {"bar": [0.0, 0.0, 0.5, 0.1]}}
        r = lm.resolve(prof, (100, 200, 400, 300))
        self.assertEqual(r["bar"], [100, 200, 200, 30])


    def test_fixed_mode_ignores_larger_client(self) -> None:
        """固定画布 806x640，客户区 1233x1019 → 仍按 806x640 算（游戏就是这么画的）。"""
        prof = {"canvas": [806, 640], "meta": {"scale_mode": "fixed"},
                "regions": {"map": [0.5, 0.5, 0.25, 0.25]}}
        r = lm.resolve(prof, (0, 0, 1233, 1019))
        self.assertEqual(r["map"], [403, 320, 202, 160])
        self.assertEqual(r["_canvas"], [0, 0, 806, 640])

    def test_fit_mode_uses_client(self) -> None:
        prof = {"canvas": [806, 640], "meta": {"scale_mode": "fit"},
                "regions": {"map": [0.5, 0.5, 0.25, 0.25]}}
        r = lm.resolve(prof, (0, 0, 1233, 1019))
        self.assertEqual(r["map"], [616, 510, 308, 255])   # round(0.5*1233)=616

    def test_min_size_one_pixel(self) -> None:
        prof = {"regions": {"tiny": [0.999, 0.999, 0.001, 0.001]}}
        r = lm.resolve(prof, (0, 0, 100, 100))
        self.assertGreaterEqual(r["tiny"][2], 1)
        self.assertGreaterEqual(r["tiny"][3], 1)


@NEED
class TestIntegrationShape(unittest.TestCase):
    def test_describe_is_readable(self) -> None:
        prof = {"title": "Canity v1.6.5", "canvas": [806, 640], "regions": GOOD}
        txt = lm.describe(prof)
        self.assertIn("Canity", txt)
        self.assertIn("map", txt)


if __name__ == "__main__":
    unittest.main()
