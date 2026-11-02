# -*- coding: utf-8 -*-
"""P1 不变量：截图后端回退、wait_for 统一入口、anchor 绝对坐标。"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401

try:
    from computer_mcp.core import screenshot as cap
    from computer_mcp.zones import wait_for as wf
    from computer_mcp import anchor_mem as A
    from computer_mcp import tool_registry as R
    HAVE = True
except Exception:
    HAVE = False

NEED = unittest.skipUnless(HAVE, "导不进 computer_mcp")


class TestBackend(unittest.TestCase):
    @NEED
    def test_backend_reported(self):
        b = cap.backend()
        self.assertIn(b, ("mss", "dxcam"), "后端只能是 mss 或 dxcam")

    @NEED
    def test_grab_falls_back_to_mss(self):
        from unittest.mock import patch
        from PIL import Image
        from authority_fixture import AuthorityFixture
        with AuthorityFixture(True), patch.object(cap,'_grab_dxcam',return_value=None), \
             patch.object(cap,'_grab_mss',return_value=(Image.new('RGB',(20,10)),20,10)):
            img, w, h = cap._grab(None)
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)
        self.assertEqual(img.size, (w, h))


class TestWaitFor(unittest.TestCase):
    @NEED
    def test_registered_and_dispatched(self):
        self.assertIn("wait_for", R.TOOLS)
        src = (R and open(os.path.join(os.path.dirname(cap.__file__), "..",
                                       "zones", "dispatch.py"),
                           encoding="utf-8").read())
        self.assertIn('name == "wait_for"', src)

    @NEED
    def test_unknown_kind_fails_cleanly(self):
        r = wf.run(kind="nope", timeout_ms=100)
        self.assertFalse(r["ok"])
        self.assertIn("未知 kind", r["detail"])

    @NEED
    def test_missing_query_fails_fast(self):
        r = wf.run(kind="text", timeout_ms=200)
        self.assertFalse(r["ok"])
        self.assertIn("query", r["detail"])
        r2 = wf.run(kind="element", timeout_ms=200)
        self.assertFalse(r2["ok"])
        self.assertIn("element_id", r2["detail"])

    @NEED
    def test_timeout_is_respected(self):
        import time

        t0 = time.perf_counter()
        r = wf.run(kind="text", query="__definitely_absent__", timeout_ms=300,
                   interval_ms=50)
        elapsed = time.perf_counter() - t0
        self.assertFalse(r["ok"])
        self.assertLess(elapsed, 3.0, "超时不应拖太久")


class TestAnchorAbsolute(unittest.TestCase):
    @NEED
    def test_same_size_uses_absolute(self):
        from unittest.mock import patch
        import tempfile
        from pathlib import Path
        geometry = {'x':10,'y':20,'w':600,'h':400}
        hwnd,px,py=11,210,150
        with tempfile.TemporaryDirectory() as folder, patch.object(A,'STORE',str(Path(folder)/'memory.json')), \
             patch.object(A,'_geometry',return_value=geometry), \
             patch.object(A,'layout_signature',return_value={'aspect':1.5}), \
             patch.object(A,'_patch_hash',return_value='abcd'):
            A.learn('__unit__','k',hwnd,px,py)
            loc=A.locate('__unit__','k',hwnd)
        self.assertEqual(loc.get("source"), "absolute")
        self.assertLessEqual(abs(loc["x"] - px), 1)
        self.assertLessEqual(abs(loc["y"] - py), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
