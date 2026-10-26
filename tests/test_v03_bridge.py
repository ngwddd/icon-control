"""v0.3：授权状态通道（本地桥）的不变量测试。

守五件事：
    1. 桥模块存在、端口/token 就位、只写状态文件不执行命令
    2. 闸门优先信任 bridge 来源，且 bridge 的有效期比 OCR 缓存短（15s < 45s）
    3. bridge 状态过期后不再被信任（退回 fail-closed 的 unknown）
    4. 客户端插件带桥上报（挂载上报 + 心跳 + 点击立即上报）
    5. CLI 检查器与闸门同源（不再自己 OCR）

**绝不写 granted=true** —— 测试只碰 false 和"过期"，避免任何自我授权。
"""

from __future__ import annotations

import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401

import json
import os
import pathlib
import re
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    from computer_mcp import permission as perm
    import computer_mcp.permission_bridge as bridge  # noqa: F401  (探测可导入性)
    HAVE = True
except Exception:
    HAVE = False

NEED = unittest.skipUnless(HAVE, "当前解释器导不进 computer_mcp / permission_bridge")


def _isolated_state() -> tuple[str, str]:
    """把闸门与桥的状态文件都指到临时目录，别碰真状态。"""
    d = tempfile.mkdtemp()
    path = os.path.join(d, "mouse-permission.json")
    return d, path


class TestBridgeModule(unittest.TestCase):
    @NEED
    def test_constants(self) -> None:
        self.assertEqual(int(bridge.DEFAULT_PORT), 18765)
        self.assertFalse(hasattr(bridge, "TOKEN"), "不该再把 token 写死在源码里")
        self.assertTrue(bridge.STATE_PATH.endswith("mouse-permission.json"))

    @NEED
    def test_write_then_read_state(self) -> None:
        old = bridge.STATE_PATH
        _, path = _isolated_state()
        try:
            bridge.STATE_PATH = path
            bridge.write_state(False, origin="unit-test")
            got = bridge.read_state()
            self.assertFalse(got["granted"])
            self.assertEqual(got["source"], "bridge")
            self.assertEqual(got["origin"], "unit-test")
            self.assertLess(abs(time.time() - got["checked_at_ts"]), 5)
        finally:
            bridge.STATE_PATH = old

    @NEED
    def test_no_secret_in_source(self) -> None:
        """源码里不许出现形似凭据的字面量（发布到开源仓库的前提）。"""
        src = pathlib.Path(bridge.__file__).read_text(encoding="utf-8")
        self.assertIsNone(re.search(r'(?i)(token|secret|password|apikey)\s*=\s*["\'][0-9a-zA-Z_-]{12,}["\']', src))
        self.assertIn("_authorized", src)
        self.assertIn("Origin", src, "必须有 Origin 白名单")

    @NEED
    def test_no_shell_execution_surface(self) -> None:
        """桥只能写文件；源码里不该出现执行命令的调用。"""
        src = pathlib.Path(bridge.__file__).read_text(encoding="utf-8")
        for bad in ("os.system(", "subprocess.", "eval(", "exec("):
            self.assertNotIn(bad, src, f"桥里不该有 {bad}")


class TestGatePrefersBridge(unittest.TestCase):
    @NEED
    def test_bridge_ttl_shorter_than_ocr(self) -> None:
        self.assertLess(perm.BRIDGE_TTL_S, perm.CACHE_TTL_S,
                        "bridge 的有效期必须比 OCR 缓存短，否则桥挂了还会被信任很久")

    @NEED
    def test_fresh_bridge_state_used_without_ocr(self) -> None:
        old_state = perm.STATE_PATH
        d, path = _isolated_state()
        calls = {"ocr": 0}
        orig_pill = perm._read_pill

        def spy_pill():
            calls["ocr"] += 1
            return (None, "")

        try:
            perm.STATE_PATH = path
            perm._read_pill = spy_pill
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"granted": True, "source": "bridge",
                           "checked_at_ts": time.time(), "origin": "unit-test"}, fh)
            st = perm.status()
            self.assertEqual(st["source"], "bridge")
            self.assertTrue(st["granted"])
            self.assertEqual(calls["ocr"], 0, "新鲜桥状态不该触发 OCR")
        finally:
            perm.STATE_PATH = old_state
            perm._read_pill = orig_pill

    @NEED
    def test_expired_bridge_state_not_trusted(self) -> None:
        old_state = perm.STATE_PATH
        d, path = _isolated_state()
        orig_pill = perm._read_pill
        orig_ensure = perm._ensure_bridge
        try:
            perm.STATE_PATH = path
            perm._ensure_bridge = lambda: None          # 别在测试里真的拉起桥
            perm._read_pill = lambda: (None, "")        # 模拟"屏幕上读不到"
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"granted": True, "source": "bridge",
                           "checked_at_ts": time.time() - (perm.BRIDGE_TTL_S + 10),
                           "origin": "unit-test"}, fh)
            st = perm.status()
            self.assertEqual(st["source"], "unknown", "过期桥状态必须失效")
            self.assertFalse(st["granted"], "过期 + 读不到 → fail closed")
        finally:
            perm.STATE_PATH = old_state
            perm._read_pill = orig_pill
            perm._ensure_bridge = orig_ensure


class TestClientReportsToBridge(unittest.TestCase):
    def _client_src(self) -> str:
        cands = [
            os.path.join(os.environ.get("DSH_DEV_HOME", os.path.expanduser("~")), "Desktop", "deepseek development", "dsh-mouse-permission", "client.js"),
            os.path.join(os.path.expanduser("~"), ".dsh", "profiles", "desktop", "node_modules",
                         "@local", "dsh-mouse-permission", "client.js"),
        ]
        for c in cands:
            if os.path.isfile(c):
                import pathlib
            return pathlib.Path(c).read_text(encoding="utf-8")
        self.skipTest("找不到 client.js")

    def test_has_bridge_url_and_heartbeat(self) -> None:
        src = self._client_src()
        self.assertIn("const BRIDGE", src)
        self.assertIn("HEARTBEAT_MS", src)
        self.assertIn("/beacon", src, "必须有图片信标通道")
        self.assertIn("127.0.0.1:18765", src)
        self.assertRegex(src, r"method:\s*'POST'")
        self.assertIn("no-cors", src, "跨源简单请求，避免预检")

    def test_reports_on_mount_and_click(self) -> None:
        src = self._client_src()
        self.assertGreaterEqual(src.count("pushToBridge("), 4,
                                "应在插件级心跳、组件挂载、点击三处都上报")


class TestCliUsesGate(unittest.TestCase):
    def test_mouse_permission_delegates_to_status(self) -> None:
        path = os.path.join(HERE, "mouse_permission.py")
        if not os.path.isfile(path):
            self.skipTest("没有 mouse_permission.py")
        src = __import__("pathlib").Path(path).read_text(encoding="utf-8")
        self.assertIn("_perm.status()", src, "CLI 必须走 status()")
        self.assertNotIn("_perm._read_pill()", src, "CLI 不许自己 OCR（会读到聊天正文）")

    @NEED
    def test_scan_regions_are_narrow(self) -> None:
        import pathlib
        src = pathlib.Path(os.path.dirname(perm.__file__), "permission.py").read_text(encoding="utf-8")
        m = re.search(r"SCAN_REGIONS\s*=\s*\((.*?)\)", src, re.S)
        self.assertIsNotNone(m)
        for h in re.findall(r'"h":\s*(\d+)', m.group(1)):
            self.assertLessEqual(int(h), 220, f"扫描区高度 {h} 太大，会把聊天正文卷进来")


if __name__ == "__main__":
    unittest.main()
