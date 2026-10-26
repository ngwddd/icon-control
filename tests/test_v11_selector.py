# -*- coding: utf-8 -*-
"""selector.py 的单测：软选择器的纯逻辑。

守的是"界面小改不崩"这件事：
    · OCR 匹配要容忍字符/空格差异（TRACK-OK → TRACKOK）
    · 同一段文字出现多次时，选**面积小**的那个（控件，不是整块面板）
    · within 区域能排除干扰（左栏的"发现" vs 正文里的"发现"）
    · 三级降级：text → template → rel，且 method 要如实上报（便于统计退化率）
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "venv", "Lib", "site-packages"))

try:
    from computer_mcp import selector as S
    HAVE = True
except Exception:
    HAVE = False

NEED = unittest.skipUnless(HAVE, "导不进 computer_mcp（需要 venv）")

RECT = (0, 0, 1000, 800)


def line(text: str, x: int, y: int, w: int = 80, h: int = 24) -> dict:
    """真实结构：ocr_ext 的行是扁平的 {text,x,y,w,h}（不是嵌套 rect）。"""
    return {"text": text, "x": x, "y": y, "w": w, "h": h}


def line_nested(text: str, x: int, y: int, w: int = 80, h: int = 24) -> dict:
    return {"text": text, "rect": {"x": x, "y": y, "width": w, "height": h}}


@NEED
class TestTextMatch(unittest.TestCase):
    def test_norm(self) -> None:
        self.assertEqual(S.norm_text("TRACK-OK-2152"), "trackok2152")
        self.assertEqual(S.norm_text("文件传输助手"), "文件传输助手")
        self.assertEqual(S.norm_text(""), "")

    def test_lcs(self) -> None:
        self.assertEqual(S.lcs_share("abc", "xxabcxx"), 1.0)
        self.assertGreater(S.lcs_share("trackok2152", "trackok2153"), 0.8)

    def test_score_exact(self) -> None:
        self.assertEqual(S.score_line("发现", "发现"), 1.0)

    def test_score_contains(self) -> None:
        self.assertGreaterEqual(S.score_line("朋友圈 昨天", "朋友圈"), 0.9)

    def test_score_ocr_noise(self) -> None:
        # OCR 少了一个字，仍应过线
        self.assertGreaterEqual(S.score_line("文件传助手", "文件传输助手", min_lcs=0.5), 0.5)

    def test_truncated_label(self) -> None:
        """界面把长名字截断成「文件传」时，query「文件传输助手」也应命中（实测踩过）。"""
        self.assertGreaterEqual(S.score_line("文件传", "文件传输助手"), 0.8)
        self.assertGreaterEqual(S.score_line("文件传...", "文件传输助手"), 0.8)

    def test_short_text_not_prefix_matched(self) -> None:
        self.assertEqual(S.score_line("发", "文件传输助手"), 0.0)

    def test_score_miss(self) -> None:
        self.assertEqual(S.score_line("月.纹", "朋友圈"), 0.0)


@NEED
class TestChooseLine(unittest.TestCase):
    def test_picks_matching(self) -> None:
        lines = [line("130 0...", 100, 100), line("发现", 60, 300),
                 line("朋友圈", 200, 200)]
        hit = S.choose_line(lines, "朋友圈")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["text"], "朋友圈")
        self.assertEqual(hit["at"], (240, 212))

    def test_no_match(self) -> None:
        self.assertIsNone(S.choose_line([line("月.纹", 1, 1)], "朋友圈"))

    def test_prefer_smallest_on_tie(self) -> None:
        big = line("发现", 0, 0, 400, 200)      # 面积 80000
        small = line("发现", 10, 400, 60, 20)   # 面积 1200
        hit = S.choose_line([big, small], "发现")
        self.assertEqual(hit["at"], (40, 410), "应当选面积小的那个控件")

    def test_within_region(self) -> None:
        left = line("发现", 10, 10, 40, 20)        # 在左栏
        body = line("发现", 600, 300, 80, 24)      # 在正文
        hit = S.choose_line([body, left], "发现", within=[0, 0, 0.35, 0.7], rect=RECT)
        self.assertEqual(hit["at"], (30, 20), "within 应该把正文那条排除掉")

    def test_nested_rect_still_works(self) -> None:
        hit = S.choose_line([line_nested("发现", 60, 300)], "发现")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["at"], (100, 312))

    def test_empty_lines(self) -> None:
        self.assertIsNone(S.choose_line([], "发现"))
        self.assertIsNone(S.choose_line(None, "发现"))


@NEED
class TestResolve(unittest.TestCase):
    def test_empty_spec(self) -> None:
        r = S.resolve(RECT, {})
        self.assertFalse(r["ok"])

    def test_rel_fallback(self) -> None:
        # 没有任何 OCR/模板时，必须安静地退回比例坐标（method=rel）
        S.clear_cache()
        r = S.resolve(RECT, {"text": "不存在的文字_zzz", "rel": [0.5, 0.5]})
        self.assertTrue(r["ok"])
        self.assertEqual(r["method"], "rel")
        self.assertEqual(r["at"], (500, 400))

    def test_nothing_at_all(self) -> None:
        S.clear_cache()
        r = S.resolve(RECT, {"text": "不存在的文字_zzz"})
        self.assertFalse(r["ok"])
        self.assertIn("三级都失败", r["detail"])


if __name__ == "__main__":
    unittest.main()
