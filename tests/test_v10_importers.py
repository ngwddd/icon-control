# -*- coding: utf-8 -*-
"""P1-8：外部导入链路（fixture → episode → 落盘 → 统计）。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401

try:
    from computer_mcp.dataset import importers, writer
    HAVE = True
except Exception:
    HAVE = False

NEED = unittest.skipUnless(HAVE, "导不进 dataset.importers")


class TestImporterPipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._old = (writer.DATA, writer.FRAMES, writer.CONFIG)
        writer.DATA = self.tmp / "raw"
        writer.FRAMES = self.tmp / "frames"
        writer.CONFIG = self.tmp / "config.json"
        writer.save_config({"enabled": True, "frames": False})
        import computer_mcp.dataset.importers.base as base

        self.base = base
        self._old_base = (base.MANIFEST, base.EXTERNAL_DIR)
        base.MANIFEST = self.tmp / "manifest.json"
        base.EXTERNAL_DIR = writer.DATA / "external"

    def tearDown(self):
        writer.DATA, writer.FRAMES, writer.CONFIG = self._old
        self.base.MANIFEST, self.base.EXTERNAL_DIR = self._old_base

    @NEED
    def test_fixture_to_episodes(self):
        fx = self.tmp / "fx.jsonl"
        fx.write_text(
            '{"key":"1","tool":"click","x":800,"y":600,"w":1920,"h":1080,"ok":true}\n'
            '{"key":"2","tool":"match_template","x":10,"y":20,"w":1280,"h":720,"ok":false}\n',
            encoding="utf-8")
        eps = importers.local_fixture.load(str(fx))
        self.assertEqual(len(eps), 2)
        self.assertIn("external", eps[0]["labels"])
        self.assertEqual(eps[1]["verdict"], "failed")
        self.assertEqual(eps[0]["target"]["screen_w"], 1920,
                         "分辨率必须跟坐标一起存")
        r = self.base.write(eps, "fixture", "test-only")
        self.assertTrue(r["ok"])
        st = self.base.stats()
        self.assertEqual(st["sources"]["fixture"], 2)

    @NEED
    def test_manifest_records_license(self):
        eps = [self.base.to_episode(source="src", key="1", tool="click", zone="Z3",
                                    args={"x": 1, "y": 2}, screen=(100, 100),
                                    license_="CC-BY-4.0")]
        self.base.write(eps, "src", "CC-BY-4.0")
        man = json.loads(self.base.MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(man["src"]["license"], "CC-BY-4.0")
        self.assertEqual(man["src"]["total"], 1)

    @NEED
    def test_never_writes_cases(self):
        cases = writer.ROOT / "cases"
        before = len(list(cases.glob("*.json"))) if cases.is_dir() else 0
        eps = [self.base.to_episode(source="src", key="2", tool="click", zone="Z3",
                                    args={"x": 1, "y": 1}, verdict="failed")]
        self.base.write(eps, "src", "test-only")
        after = len(list(cases.glob("*.json"))) if cases.is_dir() else 0
        self.assertEqual(before, after, "外部数据绝不能写 cases/")


if __name__ == "__main__":
    unittest.main(verbosity=2)
