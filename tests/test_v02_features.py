"""v0.2 新增能力的不变量测试。

守四件事：
    1. `permission` 闸门模块：API 齐全、输入/只读分类正确、fail-closed、环境变量可关
    2. `verify_flow` 分级验证：分级证据结构、遇错即停、报告可落盘
    3. `mcp.py` 里闸门与 verify_flow 都已接线（且闸门在路由之前）
    4. `_patched/` 与安装副本字节一致（防漂移）

不点鼠标、不读屏幕、不依赖 GUI。
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    from computer_mcp import permission as perm
    from computer_mcp import verify_flow as vf
    HAVE_PKG = True
except Exception:
    HAVE_PKG = False

NEED = unittest.skipUnless(HAVE_PKG, "当前解释器导不进 computer_mcp")


def _pkg_dir() -> str:
    here = os.path.dirname(os.path.abspath(perm.__file__))
    return here


class TestPermissionGate(unittest.TestCase):
    @NEED
    def test_api_and_classification(self) -> None:
        self.assertTrue(callable(perm.check_tool))
        self.assertTrue(callable(perm.status))
        self.assertTrue(callable(perm.require))
        # 输入类必须在集合里
        for t in ("click", "type", "key_press", "batch", "macro_run", "ui_click", "click_template"):
            self.assertIn(t, perm.INPUT_TOOLS, f"{t} 未被纳入闸门")
        # 只读类必须放行
        for t in ("screenshot", "screen_state", "ocr_read", "match_template", "vision_list"):
            self.assertIsNone(perm.check_tool(t), f"只读工具 {t} 不应被拦")
            self.assertNotIn(t, perm.INPUT_TOOLS)

    @NEED
    def test_fail_closed_when_unknown(self) -> None:
        """读不到 GUI 时必须按未授权处理，且拒绝载荷结构完整。"""
        old_env = os.environ.get("DSH_MOUSE_GATE")
        old_state = perm.STATE_PATH
        try:
            os.environ.pop("DSH_MOUSE_GATE", None)
            perm.STATE_PATH = os.path.join(tempfile.gettempdir(), "no_such_state_mouse.json")
            if os.path.isfile(perm.STATE_PATH):
                os.remove(perm.STATE_PATH)
            # 把屏幕读取打桩成"读不到"
            orig = perm._read_pill
            perm._read_pill = lambda: (None, "")
            try:
                st = perm.status(force=True)
                self.assertFalse(st["granted"], "读不到时必须 fail closed")
                self.assertEqual(st["source"], "unknown")
                denial = perm.check_tool("click")
                self.assertIsNotNone(denial)
                self.assertTrue(denial["blocked"])
                self.assertIn("permission", denial)
            finally:
                perm._read_pill = orig
        finally:
            perm.STATE_PATH = old_state
            if old_env is not None:
                os.environ["DSH_MOUSE_GATE"] = old_env

    @NEED
    def test_env_switch_disables_gate(self) -> None:
        old = os.environ.get("DSH_MOUSE_GATE")
        try:
            os.environ["DSH_MOUSE_GATE"] = "off"
            self.assertFalse(perm.enabled())
            self.assertIsNone(perm.check_tool("click"), "关闭闸门后应放行")
            st = perm.status(force=True)
            self.assertTrue(st["granted"])
            self.assertEqual(st["source"], "env-disabled")
        finally:
            if old is None:
                os.environ.pop("DSH_MOUSE_GATE", None)
            else:
                os.environ["DSH_MOUSE_GATE"] = old

    @NEED
    def test_cache_short_circuits(self) -> None:
        """状态文件新鲜时应命中缓存（不再读屏幕）。"""
        old_state = perm.STATE_PATH
        tmpdir = tempfile.mkdtemp()
        try:
            perm.STATE_PATH = os.path.join(tmpdir, "state.json")
            with open(perm.STATE_PATH, "w", encoding="utf-8") as fh:
                json.dump({"granted": True, "source": "cache-test",
                           "checked_at": "x", "checked_at_ts": __import__("time").time()}, fh)
            called = {"n": 0}
            orig = perm._read_pill

            def spy():
                called["n"] += 1
                return (False, "")

            perm._read_pill = spy
            try:
                st = perm.status()
                self.assertTrue(st["granted"], "应使用缓存里的 granted")
                self.assertEqual(called["n"], 0, "缓存命中不应再读屏幕")
            finally:
                perm._read_pill = orig
        finally:
            perm.STATE_PATH = old_state


class TestVerifyFlow(unittest.TestCase):
    @NEED
    def test_pass_then_fail_stops(self) -> None:
        d = tempfile.mkdtemp()
        good = os.path.join(d, "ok.txt")
        with open(good, "w", encoding="utf-8") as fh:
            fh.write("hello world")
        rep = vf.run([
            {"name": "s1", "assert": [{"kind": "file", "path": good, "contains": "hello"}]},
            {"name": "s2", "assert": [{"kind": "file", "path": good + ".missing"}]},
            {"name": "s3", "assert": [{"kind": "file", "path": good}]},
        ])
        self.assertFalse(rep["ok"])
        self.assertEqual(rep["failed_stage"], "s2")
        self.assertEqual(rep["ran"], 2, "遇错即停：第三级不应执行")
        self.assertTrue(rep["stages"][0]["ok"])
        self.assertFalse(rep["stages"][1]["ok"])
        # 每级都带证据
        self.assertIn("detail", rep["stages"][0]["checks"][0])
        self.assertIn("elapsed_ms", rep["stages"][0])

    @NEED
    def test_continue_on_fail_and_report_file(self) -> None:
        d = tempfile.mkdtemp()
        rep_path = os.path.join(d, "report.json")
        rep = vf.run([
            {"name": "bad", "assert": [{"kind": "file", "path": os.path.join(d, "nope")}]},
            {"name": "alsobad", "assert": [{"kind": "file", "path": os.path.join(d, "nope2")}]},
        ], stop_on_fail=False, report_path=rep_path)
        self.assertEqual(rep["ran"], 2, "stop_on_fail=False 时应跑完全部")
        self.assertTrue(os.path.isfile(rep_path), "报告应落盘")
        with open(rep_path, encoding="utf-8") as fh:
            disk = json.load(fh)
        self.assertEqual(disk["failed_stage"], "bad", "failed_stage 应记第一处失败")
        self.assertEqual(disk["failed_stages"], ["bad", "alsobad"], "应记全部失败级")
        self.assertEqual(len(disk["stages"]), 2)

    @NEED
    def test_unknown_kind_is_failure_not_crash(self) -> None:
        rep = vf.run([{"name": "s", "assert": [{"kind": "no-such-kind"}]}])
        self.assertFalse(rep["ok"])
        self.assertFalse(rep["stages"][0]["checks"][0]["ok"])

    @NEED
    def test_all_kinds_registered(self) -> None:
        for k in ("text", "template", "baseline", "stable", "file"):
            self.assertIn(k, vf.KINDS, f"缺少断言类型 {k}")


class TestWiring(unittest.TestCase):
    @NEED
    def test_gate_before_routing(self) -> None:
        src = open(os.path.join(_pkg_dir(), "mcp.py"), encoding="utf-8").read()
        gate_at = src.find("mouse permission HARD GATE")
        route_at = src.find("# Route to appropriate action function")
        self.assertGreater(gate_at, 0, "mcp.py 里没有闸门")
        self.assertGreater(route_at, 0)
        self.assertLess(route_at, gate_at, "闸门必须在进入路由之后、动作之前")
        self.assertIn("_perm_gate.check_tool", src)

    @NEED
    def test_verify_flow_registered_and_dispatched(self) -> None:
        import asyncio
        import computer_mcp.mcp as m
        tools = asyncio.run(m.list_tools())
        names = {t.name for t in tools}
        self.assertIn("verify_flow", names, "verify_flow 未注册")
        src = open(os.path.join(_pkg_dir(), "mcp.py"), encoding="utf-8").read()
        self.assertIn('name == "verify_flow"', src, "verify_flow 无分发分支")
        self.assertGreaterEqual(len(names), 58, f"工具总数异常：{len(names)}")

    def test_patched_in_sync(self) -> None:
        pkg = os.path.join(HERE, "venv", "Lib", "site-packages", "computer_mcp")
        if not os.path.isdir(pkg):
            self.skipTest("没有 venv 安装副本")
        for f in ("permission.py", "verify_flow.py", "mcp.py"):
            a = os.path.join(pkg, f)
            b = os.path.join(HERE, "_patched", f)
            if not (os.path.isfile(a) and os.path.isfile(b)):
                self.skipTest(f"{f} 缺少一侧")
            self.assertEqual(open(a, "rb").read(), open(b, "rb").read(), f"{f} 漂移了")


if __name__ == "__main__":
    unittest.main()
