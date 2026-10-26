# -*- coding: utf-8 -*-
"""screen_model 的单测：四个通用探测器，全部用合成图。

守的是"通用性"：判据必须是**结构**（周期性 / 长宽比 / 饱和度 / 行投影），
不能依赖任何具体游戏的坐标或颜色值。
"""
from __future__ import annotations

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "venv", "Lib", "site-packages"))

try:
    from computer_mcp import screen_model as sm
    HAVE = True
except Exception:
    HAVE = False

NEED = unittest.skipUnless(HAVE, "导不进 computer_mcp（需要 venv）")


def blank(w=400, h=300, color=(0, 0, 0)) -> np.ndarray:
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :] = color
    return img


def draw_strokes(img, x, y, color, n=8, sw=3, sh=14, gap=5):
    cx = x
    for _ in range(n):
        img[y:y + sh, cx:cx + sw] = color
        cx += sw + gap


@NEED
class TestContentBox(unittest.TestCase):
    def test_letterboxed_canvas(self) -> None:
        """画布贴在左上角，右下是黑边 —— 必须只框住画布。"""
        img = blank(400, 300, (0, 0, 0))
        img[20:20 + 160, 10:10 + 240] = (70, 60, 55)     # 内容区
        x, y, w, h = sm.content_box(img)
        self.assertLessEqual(abs(x - 10), 3, f"x={x}")
        self.assertLessEqual(abs(y - 20), 3, f"y={y}")
        self.assertLessEqual(abs(w - 240), 6, f"w={w}")
        self.assertLessEqual(abs(h - 160), 6, f"h={h}")

    def test_full_window(self) -> None:
        img = blank(200, 150, (90, 90, 90))
        self.assertEqual(sm.content_box(img), (0, 0, 200, 150))


@NEED
class TestTextRows(unittest.TestCase):
    def test_two_colored_rows(self) -> None:
        img = blank()
        draw_strokes(img, 20, 20, (0, 255, 255))
        draw_strokes(img, 20, 60, (232, 192, 64))
        rows = sm.find_text_rows(img)
        self.assertGreaterEqual(len(rows), 2, f"只找到 {len(rows)} 行")
        self.assertLess(rows[0]["y0"], rows[-1]["y0"])

    def test_gray_wall_not_text(self) -> None:
        """灰色墙面（低饱和）不算 HUD 文字。"""
        img = blank()
        img[20:80, 20:200] = (110, 105, 100)
        self.assertEqual(sm.find_text_rows(img), [])


@NEED
class TestLattice(unittest.TestCase):
    def test_grid_pitch_detected(self) -> None:
        """画一个 12x10 的格子面板，pitch=11 —— 不告诉它这是什么游戏。"""
        pitch = 11
        rows, cols = 10, 12
        img = blank(cols * pitch + 20, rows * pitch + 20, (8, 8, 8))
        for r in range(rows):
            for c in range(cols):
                y = 10 + r * pitch + 1
                x = 10 + c * pitch + 1
                img[y:y + pitch - 2, x:x + pitch - 2] = (110, 110, 110)

        found = sm.find_lattice(img)
        self.assertTrue(found, "没找到网格面板")
        best = max(found, key=lambda d: d["score"])
        self.assertLessEqual(abs(best["pitch"] - pitch), 2.5,
                             f"pitch 判成 {best['pitch']}，期望 {pitch}")
        self.assertGreaterEqual(best["cells"][0], 8)
        self.assertGreaterEqual(best["cells"][1], 6)

    def test_plain_wall_is_not_lattice(self) -> None:
        img = blank()
        img[30:200, 30:300] = (100, 90, 85)          # 一整块墙，没有周期
        self.assertEqual(sm.find_lattice(img), [])


@NEED
class TestBars(unittest.TestCase):
    def test_half_filled_bar(self) -> None:
        img = blank(300, 120)
        img[40:52, 20:220] = (200, 180, 60)          # 长条
        img[40:52, 120:220] = (30, 30, 30)           # 右半空
        bars = sm.find_bars(img)
        self.assertTrue(bars, "没找到进度条")
        b = max(bars, key=lambda d: d["box"][2] * d["box"][3])
        self.assertAlmostEqual(b["fill"], 0.5, delta=0.15)

    def test_square_is_not_bar(self) -> None:
        img = blank()
        img[40:60, 40:60] = (200, 60, 60)            # 方块，长宽比 1
        self.assertEqual(sm.find_bars(img), [])


@NEED
class TestState(unittest.TestCase):
    def test_state_has_normalized_coords(self) -> None:
        img = blank(500, 400, (0, 0, 0))
        img[30:30 + 300, 20:20 + 340] = (60, 55, 52)      # 画布
        draw_strokes(img, 40, 45, (0, 255, 255))          # HUD 行（画布内）
        img[300:310, 40:240] = (200, 180, 60)             # 进度条
        st = sm.state(img)
        self.assertIn("canvas", st)
        for key in ("text_rows", "lattices", "bars"):
            self.assertIn(key, st)
            for item in st[key]:
                rel = item["rel"]
                self.assertEqual(len(rel), 4)
                for v in rel:
                    self.assertGreaterEqual(v, -0.02)
                    self.assertLessEqual(v, 1.02)

    def test_empty_image(self) -> None:
        st = sm.state(np.zeros((0, 0, 3), dtype=np.uint8))
        self.assertIn("canvas", st)


if __name__ == "__main__":
    unittest.main()
