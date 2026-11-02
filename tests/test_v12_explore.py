# -*- coding: utf-8 -*-
"""P2-10：探索采集器的安全边界与标签。"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401
from authority_fixture import AuthorityCase

try:
    from computer_mcp.dataset import explore, writer
    from computer_mcp import permission as P
    from computer_mcp import tool_registry as R
    HAVE = True
except Exception:
    HAVE = False

NEED = unittest.skipUnless(HAVE, "导不进 dataset.explore")


class TestExploreSafety(AuthorityCase,unittest.TestCase):
    fixture_authorized=True
    @NEED
    def test_pool_is_read_only(self):
        pool = explore.candidates()
        self.assertTrue(pool, "候选池不能为空")
        for name in pool:
            self.assertTrue(R.TOOLS[name].read_only, f"{name} 不是只读工具")
            self.assertNotIn(name, P.INPUT_TOOLS, f"{name} 会动输入，绝不能进游走池")

    @NEED
    def test_meta_tools_excluded(self):
        pool = set(explore.candidates())
        for bad in ("dataset_status", "dataset_export", "control_claim", "housekeeping"):
            self.assertNotIn(bad, pool)

    @NEED
    def test_run_records_labeled_episodes(self):
        tmp = Path(tempfile.mkdtemp())
        old = (writer.DATA, writer.FRAMES, writer.CONFIG)
        writer.DATA = tmp / "raw"
        writer.FRAMES = tmp / "frames"
        writer.CONFIG = tmp / "config.json"
        writer.save_config({"enabled": True, "frames": False})
        try:
            r = explore.run(steps=2, interval_ms=0, seed=7)
            self.assertTrue(r["ok"])
            self.assertGreaterEqual(r["recorded"], 1, "至少要记下样本")
            eps = list(writer._iter_episodes())
            self.assertTrue(any("explore" in (e.get("labels") or []) for e in eps),
                            "样本应带 explore 标签")
        finally:
            writer.DATA, writer.FRAMES, writer.CONFIG = old

    @NEED
    def test_steps_are_bounded(self):
        tmp = Path(tempfile.mkdtemp())
        old = (writer.DATA, writer.FRAMES, writer.CONFIG)
        writer.DATA = tmp / "raw"
        writer.FRAMES = tmp / "frames"
        writer.CONFIG = tmp / "config.json"
        writer.save_config({"enabled": True, "frames": False})
        try:
            r = explore.run(steps=1, interval_ms=0, seed=1)
            self.assertEqual(r["steps"], 1)
            self.assertLessEqual(sum(r["tools_used"].values()), 1)
        finally:
            writer.DATA, writer.FRAMES, writer.CONFIG = old


if __name__ == "__main__":
    unittest.main(verbosity=2)
