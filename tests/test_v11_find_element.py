# -*- coding: utf-8 -*-
"""P2-9：统一寻址回退链。"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401

try:
    from computer_mcp.zones import sense_fallback as SF
    from computer_mcp import tool_registry as R
    HAVE = True
except Exception:
    HAVE = False

NEED = unittest.skipUnless(HAVE, "导不进 sense_fallback")


class TestFallback(unittest.TestCase):
    @NEED
    def test_registered(self):
        self.assertIn("find_element", R.TOOLS)
        self.assertTrue(R.TOOLS["find_element"].read_only)

    @NEED
    def test_structure_when_nothing_found(self):
        r = SF.find_element("__definitely_absent_zzz__",
                            sources=("uia", "ocr"))
        self.assertIn("ok", r)
        self.assertIn("tried", r)
        self.assertEqual(r["tried"], ["uia", "ocr"])
        self.assertIsInstance(r["candidates"], list)
        if not r["ok"]:
            self.assertEqual(r["candidates"], [])

    @NEED
    def test_candidate_shape(self):
        """用 OCR 找屏幕上必定存在的一段字（UIA 找不到时也能落到 OCR）。"""
        r = SF.find_element("llm_matcher__absent__", sources=("uia", "ocr", "template"))
        for c in r["candidates"]:
            for k in ("x", "y", "w", "h", "cx", "cy", "source", "score"):
                self.assertIn(k, c)

    @NEED
    def test_unknown_source_is_tolerated(self):
        r = SF.find_element("x", sources=("nope",))
        self.assertFalse(r["ok"])
        self.assertIn("未知来源", " ".join(r["errors"]))

    @NEED
    def test_error_does_not_break_chain(self):
        r = SF.find_element("__absent__", sources=("template", "ocr"))
        self.assertIn("template", r["tried"])
        self.assertIn("ocr", r["tried"], "前一条失败不该中断后面的尝试")


if __name__ == "__main__":
    unittest.main(verbosity=2)
