# -*- coding: utf-8 -*-
"""P0 不变量：控制权交接、元素 id、工具白黑名单。

1. claim → AI 持有；物理输入 → 用户接管，闸门立刻拒绝
2. 用户闲置到期 → 自动释放
3. 注入静默窗内的事件不算接管（否则 AI 每点一下把自己锁死）
4. registry 的 DSH_TOOLS_ALLOW / DENY 只影响可见工具
5. element_id 稳定且可复现
"""
from __future__ import annotations

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401
from authority_fixture import AuthorityFixture

try:
    from computer_mcp import control as C
    from computer_mcp import permission as P
    from computer_mcp import tool_registry as R
    HAVE = True
except Exception:
    HAVE = False

NEED = unittest.skipUnless(HAVE, "导不进 computer_mcp")


def _reset():
    C.STATE.update({"owner": "idle", "since": time.time(), "last_user": 0.0,
                    "last_inject": 0.0, "takeovers": 0, "reason": ""})


class TestControlState(unittest.TestCase):
    def setUp(self):
        authority=AuthorityFixture(authorized=True,monitoring=True)
        authority.__enter__();self.addCleanup(authority.__exit__,None,None,None)
        _reset()

    def tearDown(self):
        _reset()

    @NEED
    def test_claim_makes_ai_owner(self):
        C.claim("test")
        st = C.status()
        self.assertEqual(st["owner"], "ai")
        self.assertIsNone(C.blocking_reason())

    @NEED
    def test_physical_input_takes_over(self):
        C.claim("test")
        time.sleep(0.3)                     # 跳过注入静默窗
        C.note_physical("unit test")
        st = C.status()
        self.assertEqual(st["owner"], "user")
        self.assertTrue(st["takeover"])
        self.assertIsNotNone(C.blocking_reason(), "接管后闸门必须能给出理由")

    @NEED
    def test_quiet_window_does_not_ignore_physical_input(self):
        C.claim("test")
        C.quiet()                           # 刚注入 → 接下来 250ms 内的输入不算用户
        C.note_physical("injected")
        self.assertEqual(C.status()['owner'],'user','静默窗口不得隐藏物理接管')

    @NEED
    def test_idle_resume(self):
        C.claim("test")
        time.sleep(0.3)
        C.note_physical("unit test")
        self.assertEqual(C.status()["owner"], "user")
        # 把接管时间往前推，模拟闲置到期
        C.STATE["since"] = time.time() - (C.IDLE_RESUME_S + 1)
        C.STATE["last_user"] = C.STATE["since"]
        self.assertEqual(C.status()["owner"], "idle")
        self.assertIsNone(C.blocking_reason())

    @NEED
    def test_release(self):
        C.claim("test")
        C.release("unit test")
        self.assertNotEqual(C.status()["owner"], "ai")


class TestGateRespectsControl(unittest.TestCase):
    def setUp(self):
        _reset()
        self._orig = P.status

    def tearDown(self):
        P.status = self._orig
        _reset()

    @NEED
    def test_blocked_when_user_owns(self):
        from authority_fixture import approval
        P.status = lambda force=False: {"granted": True, 'authorization':approval(), "source": "bridge",
                                        "age_s": 0.0, "checked_at": "", "screen_text": ""}
        C.claim("test")
        time.sleep(0.3)
        C.note_physical("unit test")
        denial = P.check_tool("click", {"x": 1, "y": 2})
        self.assertIsNotNone(denial, "用户接管时 click 必须被拒")
        self.assertTrue(denial["blocked"])
        self.assertIn("控制权", denial["error"])
        self.assertIn("control", denial)

    @NEED
    def test_allowed_when_ai_owns(self):
        from authority_fixture import approval
        P.status = lambda force=False: {"granted": True, 'authorization':approval(), "source": "bridge",
                                        "age_s": 0.0, "checked_at": "", "screen_text": ""}
        C.claim("test")
        self.assertIsNone(P.check_tool("click", {"x": 1, "y": 2}))


class TestToolAllowDeny(unittest.TestCase):
    @NEED
    def test_deny_hides_tool(self):
        os.environ["DSH_TOOLS_DENY"] = "housekeeping"
        try:
            names = [t.name for t in R.all_tools()]
            self.assertNotIn("housekeeping", names)
            self.assertIn("housekeeping", R.disabled())
            self.assertIn("click", names)
        finally:
            os.environ.pop("DSH_TOOLS_DENY", None)

    @NEED
    def test_allow_only_listed(self):
        os.environ["DSH_TOOLS_ALLOW"] = "click,type"
        try:
            names = sorted(t.name for t in R.all_tools())
            self.assertEqual(names, ["click", "type"])
        finally:
            os.environ.pop("DSH_TOOLS_ALLOW", None)

    @NEED
    def test_default_all_visible(self):
        os.environ.pop("DSH_TOOLS_ALLOW", None)
        os.environ.pop("DSH_TOOLS_DENY", None)
        self.assertEqual(len(R.all_tools()), len(R.TOOLS))
        self.assertEqual(R.disabled(), [])


class TestElementId(unittest.TestCase):
    @NEED
    def test_id_is_deterministic(self):
        from computer_mcp import ui_ext as U

        if not hasattr(U, "_element_id"):
            self.skipTest("ui_ext 未升级")
        a = U._element_id("ButtonControl", "确定", (10, 20, 80, 30))
        b = U._element_id("ButtonControl", "确定", (10, 20, 80, 30))
        c = U._element_id("ButtonControl", "取消", (10, 20, 80, 30))
        self.assertEqual(a, b)
        self.assertNotEqual(a, c, "名字不同必须不同 id")
        self.assertEqual(len(a), 8)

    @NEED
    def test_exclude_env_parsing(self):
        from computer_mcp import ui_ext as U

        os.environ["DSH_UI_EXCLUDE_PROCESSES"] = "Code.exe, Cursor.exe"
        try:
            got = U.excluded_processes()
            self.assertIn("code.exe", got)
            self.assertIn("cursor.exe", got)
            self.assertEqual(len(got), 2)
        finally:
            os.environ.pop("DSH_UI_EXCLUDE_PROCESSES", None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
