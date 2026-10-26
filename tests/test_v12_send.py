# -*- coding: utf-8 -*-
"""send 动作的三段验证里，第二环（文字真的进了输入框）的纯逻辑。

守的是这条教训：
    · stable / changed 判据会在"什么都没发生"时误判成功（实测栽过两次）
    · 所以"粘贴成功"必须由**输入框里读到的文字**来证明，而不是画面稳不稳
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "venv", "Lib", "site-packages"))

try:
    from computer_mcp.train import text_landed
    HAVE = True
except Exception:
    HAVE = False

NEED = unittest.skipUnless(HAVE, "导不进 computer_mcp（需要 venv）")


@NEED
class TestTextLanded(unittest.TestCase):
    def test_exact(self) -> None:
        self.assertTrue(text_landed("轨道验证 04:10:22", "轨道验证 04:10:22"))

    def test_ocr_noise(self) -> None:
        # OCR 会把空格/冒号弄丢，甚至把 au 读成 cu
        self.assertTrue(text_landed("轨道验证 04:10:22", "轨道验证041022"))

    def test_partial_prefix(self) -> None:
        # 区域偏了，只读到后半段
        self.assertTrue(text_landed("focus3 04:03:26", "cus3 04:03:26", min_lcs=0.5))

    def test_empty_input_box(self) -> None:
        # 输入框是空的 —— 这正是"粘贴没落进去"的真实情况
        self.assertFalse(text_landed("轨道验证 04:10:22", ""))

    def test_wrong_text(self) -> None:
        self.assertFalse(text_landed("轨道验证 04:10:22", "自动化验证 03:52:54"))

    def test_empty_sent(self) -> None:
        self.assertFalse(text_landed("", "随便什么"))


if __name__ == "__main__":
    unittest.main()
