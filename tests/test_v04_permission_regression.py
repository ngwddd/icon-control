# -*- coding: utf-8 -*-
"""v0.4 回归测试：修掉「前端绿 / 后台灰」的三个根因。

1) 多窗口互相覆盖：A 窗口点授权，B 窗口心跳上报 false 把它盖掉
2) 负向结果缓存过久：一次 OCR 失败 → 45 秒内连桥都不问
3) OCR 认错字：把「已授权」认成「床授权」→ 直接判灰

约定：只写 false / 只用临时状态文件；不碰真状态，不做任何自我授权。
"""
from __future__ import annotations

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401
from authority_fixture import AuthorityCase,signed_state

import json
import tempfile
import time
import unittest

try:
    from computer_mcp import permission as perm
    from computer_mcp import permission_bridge as bridge
    HAVE = True
except Exception:
    HAVE = False

NEED = unittest.skipUnless(HAVE, "导不进 computer_mcp")


def _fresh_bridge():
    bridge.CLIENTS.clear()


class TestMultiClient(AuthorityCase,unittest.TestCase):
    """bug 1：多窗口互相覆盖。"""

    @NEED
    def test_heartbeat_false_does_not_override_action_granted(self) -> None:
        _fresh_bridge()
        # A 窗口：用户点了授权（动作）
        bridge.write_state(True, origin="beacon", client="winA", event="action")
        # B 窗口：只是心跳，本地还是 false（它从没被点过）
        bridge.write_state(False, origin="beacon", client="winB", event="hb")
        st = bridge.read_state()
        self.assertTrue(st["granted"], "心跳不能把别处刚点的授权盖掉")
        self.assertTrue(st["effective_from"].startswith("action"))

    @NEED
    def test_latest_action_wins(self) -> None:
        _fresh_bridge()
        bridge.write_state(True, origin="beacon", client="winA", event="action")
        time.sleep(0.01)
        bridge.write_state(False, origin="beacon", client="winB", event="action")
        self.assertFalse(bridge.read_state()["granted"], "最后一次用户动作说了算")

    @NEED
    def test_heartbeat_any_true(self) -> None:
        _fresh_bridge()
        bridge.write_state(False, origin="beacon", client="winA", event="hb")
        bridge.write_state(True, origin="beacon", client="winB", event="hb")
        self.assertFalse(bridge.read_state()['granted'],'心跳不得自行建立用户授权')

    @NEED
    def test_no_client_is_pure_heartbeat(self) -> None:
        """旧版客户端（不带 client/event）上报 false 时，不能当动作。"""
        _fresh_bridge()
        bridge.write_state(True, origin="beacon", client="winA", event="action")
        bridge.write_state(False, origin="client")      # 老格式
        self.assertTrue(bridge.read_state()['granted'],
                        '旧格式属于心跳，不能覆盖明确用户动作')


class TestNegativeCache(AuthorityCase,unittest.TestCase):
    """bug 2：负向缓存 45 秒，期间不问桥。"""

    @NEED
    def test_negative_cache_is_short(self) -> None:
        self.assertLess(perm.NEG_TTL_S, perm.CACHE_TTL_S,
                        "负向缓存必须比正向短，否则一次 OCR 失败会卡很久")

    @NEED
    def test_stale_negative_lets_bridge_win(self) -> None:
        old_state = perm.STATE_PATH
        orig_pill, orig_ensure = perm._read_pill, perm._ensure_bridge
        try:
            d = tempfile.mkdtemp()
            perm.STATE_PATH = os.path.join(d, "mouse-permission.json")
            perm._ensure_bridge = lambda: None
            perm._read_pill = lambda: (None, "")     # 屏幕上永远读不到

            # 5 秒前的「读不到」负向缓存（旧代码会因此封死 45 秒）
            with open(perm.STATE_PATH, "w", encoding="utf-8") as fh:
                json.dump({"granted": False, "source": "unknown",
                           "checked_at_ts": time.time() - 5}, fh)

            # 桥上有新鲜的「用户动作=授权」
            bridge.CLIENTS.clear()
            bridge.write_state(True, origin="beacon", client="winA", event="action")
            with open(perm.STATE_PATH, "w", encoding="utf-8") as fh:
                json.dump(signed_state({"granted": True, "source": "bridge",
                           "checked_at_ts": time.time(),
                           "effective_from": "action@0s"}), fh)

            st = perm.status()
            self.assertTrue(st["granted"], "5 秒前的负向缓存不该继续封死")
            self.assertEqual(st["source"], "bridge")
        finally:
            perm.STATE_PATH = old_state
            perm._read_pill, perm._ensure_bridge = orig_pill, orig_ensure


class TestOcrAmbiguity(unittest.TestCase):
    """bug 3：OCR 认错字被当成"未授权"。"""

    @NEED
    def test_garbled_text_is_not_denied(self) -> None:
        src = open(perm.__file__, encoding="utf-8").read()
        # 「床授权」这种 OCR 误读不能再出现在"判灰"的分支里
        denied_block = src.split('if text and ("未授权"')[1][:120] if 'if text and ("未授权"' in src else ""
        self.assertNotIn("床授权", denied_block,
                         "OCR 误读的「床授权」不能当作未授权")

    @NEED
    def test_ambiguous_pill_returns_none(self) -> None:
        """有「鼠标」文字但绿没测到 → 返回 None（不表态），不是 False。"""
        orig = perm._green_capsule, perm._ocr_ext if hasattr(perm, "_ocr_ext") else None
        calls = {"n": 0}

        def fake_green(region):
            return None

        class FakeOcr:
            @staticmethod
            def ocr_read(**kw):
                return {"lines": [{"text": "鼠标·已授权"}]}

        try:
            perm._green_capsule = fake_green
            setattr(perm, "_ocr_ext", FakeOcr)
            got, snippet = perm._read_pill()
            self.assertIsNone(got, "绿没测到 + 文字含糊 → 必须返回 None，交给桥判")
        finally:
            perm._green_capsule = orig[0]
            if orig[1] is not None:
                setattr(perm, "_ocr_ext", orig[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
