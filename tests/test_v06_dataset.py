# -*- coding: utf-8 -*-
"""R5 不变量：训练数据分区的六条硬约束。

1. 脱敏覆盖六类（身份证/银行卡/手机/邮箱/token/家目录）
2. 落盘样本里不含敏感信息
3. tee 关闭时不写样本
4. tee 在工具抛异常时仍然记录，并把异常原样抛出
5. 默认不抓屏（frames=False）
6. 样本字段齐全、verdict 合理
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401
from authority_fixture import AuthorityFixture

try:
    from computer_mcp import dataset as DS
    from computer_mcp.dataset import redact, schema, writer
    HAVE = True
except Exception:
    HAVE = False

NEED = unittest.skipUnless(HAVE, "导不进 computer_mcp.dataset")


class TestRedaction(unittest.TestCase):
    CASES = {
        "id_card": "身份证 210421199409052417 结束",
        "phone": "电话 13812345678",
        "bank_card": "卡号 6222021234567890123",
        "email": "邮箱 a.b@example.com",
        "token": "凭据 ghp_abcdefghijklmnop",
        "home_path": str(os.path.expanduser("~")) + r"\Desktop\x.png",
    }

    @NEED
    def test_all_six_classes(self) -> None:
        for kind, raw in self.CASES.items():
            clean, hits = redact.redact_args({"v": raw})
            self.assertNotEqual(clean["v"], raw, f"{kind} 没被脱敏")
            self.assertTrue(hits, f"{kind} 没记录命中类型")
            self.assertFalse(redact.is_sensitive(str(clean["v"])),
                             f"{kind} 脱敏后仍被判定为敏感: {clean['v']}")

    @NEED
    def test_clean_text_untouched(self) -> None:
        clean, hits = redact.redact_args({"v": "screen_state"})
        self.assertEqual(clean["v"], "screen_state")
        self.assertEqual(hits, [])

    @NEED
    def test_nested_and_long(self) -> None:
        big = {"a": {"b": ["x" * 900, "13812345678"]}}
        clean, _ = redact.redact_args(big)
        self.assertLessEqual(len(clean["a"]["b"][0]), 401, "超长字符串要截断")
        self.assertEqual(clean["a"]["b"][1], "<phone>")


class TestConfig(unittest.TestCase):
    @NEED
    def test_frames_off_by_default(self) -> None:
        cfg = writer.load_config()
        self.assertFalse(cfg["frames"], "默认不抓屏（隐私）")
        self.assertFalse(cfg['enabled'],'训练采集需要显式开启')

    @NEED
    def test_retention_defaults(self) -> None:
        ret = writer.load_config()["retention"]
        for k in ("raw_days", "frame_days", "frames_gb", "exports"):
            self.assertIn(k, ret)


class TestTee(unittest.TestCase):
    def setUp(self) -> None:
        authority=AuthorityFixture(authorized=True)
        authority.__enter__();self.addCleanup(authority.__exit__,None,None,None)
        self.tmp = tempfile.mkdtemp()
        self._old = (writer.DATA, writer.FRAMES, writer.CONFIG)
        writer.DATA = __import__("pathlib").Path(self.tmp) / "raw"
        writer.FRAMES = __import__("pathlib").Path(self.tmp) / "frames"
        writer.CONFIG = __import__("pathlib").Path(self.tmp) / "config.json"
        writer.save_config({"enabled": True, "frames": False})

    def tearDown(self) -> None:
        writer.DATA, writer.FRAMES, writer.CONFIG = self._old

    def _count(self) -> int:
        return writer.stats()["episodes_total"]

    @NEED
    def test_records_episode(self) -> None:
        async def call():
            return "ok"

        async def run():
            return await DS.tee("list_windows", {"hwnd": 1}, call, lambda n: "Z2")

        asyncio.run(run())
        self.assertEqual(self._count(), 1)
        ep = next(iter(writer._iter_episodes()))
        for f in schema.FIELDS:
            self.assertIn(f, ep, f"字段缺失: {f}")
        self.assertEqual(ep["zone"], "Z2")
        self.assertEqual(ep["tool"], "list_windows")

    @NEED
    def test_disabled_writes_nothing(self) -> None:
        writer.save_config({"enabled": False})

        async def call():
            return "ok"

        asyncio.run(DS.tee("x", {}, call, lambda n: "Z1"))
        self.assertEqual(self._count(), 0)

    @NEED
    def test_error_is_recorded_and_reraised(self) -> None:
        async def boom():
            raise ValueError("炸了")

        async def run():
            return await DS.tee("click", {"x": 1}, boom, lambda n: "Z3")

        with self.assertRaises(ValueError):
            asyncio.run(run())
        self.assertEqual(self._count(), 1, "异常也要留痕")
        ep = next(iter(writer._iter_episodes()))
        self.assertEqual(ep["verdict"], "error")
        self.assertIn("ValueError", ep["result"]["error"])

    @NEED
    def test_episode_has_no_secret(self) -> None:
        async def call():
            return "ok"

        async def run():
            return await DS.tee("type", {"text": "13812345678"}, call, lambda n: "Z3")

        asyncio.run(run())
        raw = next(writer.DATA.glob("*/episodes.jsonl")).read_text(encoding="utf-8")
        self.assertNotIn("13812345678", raw, "原始手机号落盘")
        for line in raw.splitlines():
            if not line.strip():
                continue
            episode = json.loads(line)
            carried = json.dumps({key: episode.get(key)
                                  for key in ("args", "result", "target", "labels")},
                                 ensure_ascii=False)
            self.assertFalse(redact.is_sensitive(carried),
                             "args/result/target 落盘仍含敏感信息")
            hits = episode.get("redactions") or []
            self.assertTrue(hits, "没有记录脱敏命中")
            # The whole text field is dropped as private content; the phone
            # pattern never gets a chance to personalise the sample.
            self.assertIn("private_content", hits)


class TestVerdict(unittest.TestCase):
    @NEED
    def test_ok_parsing(self) -> None:
        self.assertTrue(schema.ok_of('{"success": true}'))
        self.assertFalse(schema.ok_of('{"success": false}'))
        self.assertFalse(schema.ok_of('{"blocked": true, "success": false}'))
        self.assertIsNone(schema.ok_of("不是 JSON"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
