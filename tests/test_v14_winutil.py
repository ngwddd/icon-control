# -*- coding: utf-8 -*-
"""winutil：窗口健壮性的纯逻辑。

守的三条实测教训（跟具体应用无关）：
    ・句柄会被应用重建 → 失效必须返回 None / 能自愈，而不是抛异常
    ・点自绘 UI 会丢包 → 所以要有 verify/retries（train 侧）
    ・"可见"不等于"在前台/没被盖住" → 落点必须用 WindowFromPoint 验
"""
from __future__ import annotations

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "venv", "Lib", "site-packages"))

try:
    from computer_mcp import winutil as W
    HAVE = True
except Exception:
    HAVE = False

NEED = unittest.skipUnless(HAVE, "导不进 computer_mcp（需要 venv）")


@NEED
class TestDeadHandles(unittest.TestCase):
    def test_rect_of_zero(self) -> None:
        self.assertIsNone(W.win_rect(0))

    def test_alive_false(self) -> None:
        self.assertFalse(W.is_alive(0))
        self.assertFalse(W.is_alive(123456789))

    def test_heal_without_candidate(self) -> None:
        self.assertEqual(W.heal(0), 0)
        self.assertEqual(W.heal(0, "绝对不存在的窗口标题_zzz"), 0)

    def test_find_missing(self) -> None:
        self.assertEqual(W.find_window("绝对不存在的窗口标题_zzz"), 0)

    def test_activate_dead(self) -> None:
        self.assertFalse(W.activate(0))


@NEED
class TestLiveWindow(unittest.TestCase):
    """开一个真 Tk 窗口来验 find/heal/point_owner（Tk 必须主线程，这里就是）。"""

    def setUp(self) -> None:
        try:
            import tkinter as tk
        except Exception:
            self.skipTest("没有 tkinter")
        self.tk = tk
        self.root = tk.Tk()
        self.root.title("winutil-selftest")
        self.root.geometry("320x200+120+120")
        self.root.deiconify()
        self.root.update_idletasks()
        self.root.update()
        time.sleep(0.25)          # 让 IsWindowVisible 真的变 True
        self.frame = int(self.root.wm_frame(), 16)

    def tearDown(self) -> None:
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_find_by_title(self) -> None:
        h = W.find_window("winutil-selftest")
        self.assertTrue(h)
        r = W.win_rect(h)
        self.assertIsNotNone(r)
        self.assertGreaterEqual(r[2], 300)

    def test_heal_reacquires(self) -> None:
        h = W.heal(0, "winutil-selftest")
        self.assertTrue(h, "失效句柄应能按标题自愈")

    def test_point_owner(self) -> None:
        r = W.win_rect(W.find_window("winutil-selftest"))
        self.assertIsNotNone(r)
        x = r[0] + r[2] // 2
        y = r[1] + r[3] // 2
        owner = W.point_owner(x, y)
        self.assertTrue(owner, "落点应该能解析到某个顶层窗口")

    def test_pid_of(self) -> None:
        h = W.find_window("winutil-selftest")
        self.assertGreater(W.pid_of(h), 0)


if __name__ == "__main__":
    unittest.main()
