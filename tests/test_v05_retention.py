# -*- coding: utf-8 -*-
"""保留策略测试（v0.5）：能不能真的"跑起来不产生垃圾"。

三个必须守住的东西：
    ① 超过上限时只删最老的，不删最新的
    ② 资产（macros / recipes / templates / _patched）永远不删
    ③ %TEMP% 只碰自己的前缀（vh- / dsh- / t_*.py），别人的目录不动
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "venv", "Lib", "site-packages"))

try:
    from computer_mcp import retention, live
    HAVE = True
except Exception:
    HAVE = False

NEED = unittest.skipUnless(HAVE, "导不进 computer_mcp（需要 venv）")


def _touch(p: Path, size: int = 32, age_hours: float = 0.0) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    if age_hours:
        old = time.time() - age_hours * 3600
        os.utime(p, (old, old))
    return p


@NEED
class TestPruneTool(unittest.TestCase):
    def test_files_cap_keeps_newest(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            d = root / "_draw"
            d.mkdir()
            cap = retention.POLICY["_draw"]["files"]
            n = cap + 20                     # 必须超过上限，否则没什么可裁
            for i in range(n):
                # 天龄必须都落在 3 天阈值内，否则会先按天龄删掉，测不到"按数量裁剪"
                _touch(d / f"shot{i:03d}.png", age_hours=(n - i) * 0.5)
            res = retention.sweep(root)
            left = sorted(p.name for p in d.iterdir())
            self.assertEqual(len(left), cap, f"该裁到上限 {cap}")
            self.assertIn(f"shot{n-1:03d}.png", left, "最新的不能被删")
            self.assertNotIn("shot000.png", left, "最老的该被删")
            self.assertGreater(res["removed_count"], 0)

    def test_age_cap(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            d = root / "_draw"
            _touch(d / "old.png", age_hours=24 * 10)     # 10 天前
            _touch(d / "new.png")
            retention.sweep(root)
            names = [p.name for p in d.iterdir()]
            self.assertNotIn("old.png", names)
            self.assertIn("new.png", names)

    def test_assets_never_touched(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            assets = ("macros/a.json", "recipes/b.json", "templates/c.png",
                      "vision/glyphs.json", "_patched/mcp.py")
            for rel in assets:
                _touch(root / rel, age_hours=24 * 60)     # 两个月前
            retention.sweep(root)
            for rel in assets:
                self.assertTrue((root / rel).is_file(), f"{rel} 被误删了")

    def test_recordings_dir_cap(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            base = root / "recordings"
            for i in range(6):
                d = base / f"run{i:02d}"
                d.mkdir(parents=True)
                (d / "f00001.jpg").write_bytes(b"x" * 16)
                old = time.time() - (10 - i) * 3600
                os.utime(d, (old, old))
            retention.sweep(root)
            left = sorted(p.name for p in base.iterdir())
            self.assertLessEqual(len(left), retention.POLICY["recordings"]["dirs"])
            self.assertIn("run05", left)

    def test_usage_reports_without_deleting(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            _touch(root / "_draw" / "a.png")
            before = len(list((root / "_draw").iterdir()))
            u = retention.usage(root)
            self.assertGreaterEqual(u["areas"]["_draw"]["files"], before)
            self.assertEqual(len(list((root / "_draw").iterdir())), before)


@NEED
class TestTempSweep(unittest.TestCase):
    def test_own_prefixes_removed(self) -> None:
        base = Path(tempfile.gettempdir())
        mine = base / f"vh-test-{os.getpid()}"
        mine.mkdir(exist_ok=True)
        (mine / "x.txt").write_bytes(b"1")
        old = time.time() - 12 * 3600
        os.utime(mine, (old, old))
        try:
            res = retention.sweep_temp(max_age_hours=6)
            self.assertIn(mine.name, res["removed"])
            self.assertFalse(mine.exists())
        finally:
            import shutil
            shutil.rmtree(mine, ignore_errors=True)

    def test_other_programs_untouched(self) -> None:
        base = Path(tempfile.gettempdir())
        other = base / f"other-{os.getpid()}"
        other.mkdir(exist_ok=True)
        old = time.time() - 12 * 3600
        os.utime(other, (old, old))
        try:
            retention.sweep_temp(max_age_hours=6)
            self.assertTrue(other.exists(), "别人的目录不许删")
        finally:
            import shutil
            shutil.rmtree(other, ignore_errors=True)

    def test_fresh_dir_kept(self) -> None:
        base = Path(tempfile.gettempdir())
        fresh = base / f"vh-fresh-{os.getpid()}"
        fresh.mkdir(exist_ok=True)
        try:
            res = retention.sweep_temp(max_age_hours=6)
            self.assertNotIn(fresh.name, res["removed"])
        finally:
            import shutil
            shutil.rmtree(fresh, ignore_errors=True)


@NEED
class TestHousekeepingTool(unittest.TestCase):
    def test_status_is_read_only(self) -> None:
        r = live.tool_housekeeping({"action": "status"})
        self.assertTrue(r["success"])
        self.assertIn("areas", r)
        self.assertIn("total_mb", r)

    def test_sweep_dry_run(self) -> None:
        r = live.tool_housekeeping({"action": "sweep", "dry_run": True})
        self.assertTrue(r["success"])
        self.assertIn("tool", r)
        self.assertIn("temp", r)


if __name__ == "__main__":
    unittest.main()
