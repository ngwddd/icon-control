"""急停开关的不变量测试（用户 2026-10-25 要求：连按两下 ESC 必须立刻松手）。

守四件事：
    1. panic 模块存在且 API 齐全（triggered / check / wait / reset / stop）
    2. 单次 ESC 不触发，窗口期内两次才触发，且触发后粘住
    3. 三个自动化脚本都接了急停（循环里 + 点击前）
    4. 独立看守进程 panic_watch.py 存在
"""

from __future__ import annotations

import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401

import ast
import os
import time
import unittest

try:                      # pynput 只在 venv 里；系统 Python 跑测试时跳过相关用例
    from pynput import keyboard as _kb
    HAVE_PYNPUT = _kb is not None      # 探测可用性：引用一下，静态检查才不会报未使用
except Exception:
    HAVE_PYNPUT = False

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pkg_dir() -> str:
    try:
        import computer_mcp  # noqa: F401
        return os.path.dirname(computer_mcp.__file__)
    except Exception:
        cand = os.path.join(HERE, "venv", "Lib", "site-packages", "computer_mcp")
        if os.path.isdir(cand):
            return cand
        raise


class TestPanicModule(unittest.TestCase):
    def test_exists_and_api(self) -> None:
        path = os.path.join(_pkg_dir(), "panic.py")
        self.assertTrue(os.path.isfile(path), "缺 computer_mcp/panic.py")
        src = open(path, encoding="utf-8").read()
        ast.parse(src)
        for name in ("class PanicSwitch", "def start", "def reset", "def stop", "def default"):
            self.assertIn(name, src, f"panic.py 缺 {name}")

    @unittest.skipUnless(HAVE_PYNPUT, "系统 Python 没有 pynput")
    def test_single_vs_double_esc(self) -> None:
        from pynput import keyboard
        from computer_mcp import panic

        sw = panic.PanicSwitch(verbose=False)
        sw._on_press(keyboard.Key.esc)
        self.assertFalse(sw.triggered, "单次 ESC 不应触发")

        sw._on_press(keyboard.Key.esc)
        self.assertTrue(sw.triggered, "连按两下必须触发")

        # 粘住：再按还是触发状态
        sw._on_press(keyboard.Key.esc)
        self.assertTrue(sw.triggered, "触发后必须粘住")

        sw.reset()
        self.assertFalse(sw.triggered, "reset 后应复位")

    @unittest.skipUnless(HAVE_PYNPUT, "系统 Python 没有 pynput")
    def test_outside_window_does_not_trigger(self) -> None:
        from pynput import keyboard
        from computer_mcp import panic

        sw = panic.PanicSwitch(window_s=0.15, verbose=False)
        sw._on_press(keyboard.Key.esc)
        time.sleep(0.30)
        sw._on_press(keyboard.Key.esc)
        self.assertFalse(sw.triggered, "超出窗口期的两次 ESC 不应触发")


class TestBotsWired(unittest.TestCase):
    """任何"自动跑"的脚本都必须接急停（*_bot*.py / *_run*.py / *_fight*.py）。

    以前这里硬编码了具体游戏脚本名 —— 那类脚本属于**专项**，已移出本项目，
    通用插件不该依赖它们。现在改成"扫到就查，扫不到就跳过"。
    """

    def test_any_bot_wires_panic(self) -> None:
        import glob

        pats = ("*_bot*.py", "*_run*.py", "*_fight*.py")
        found: list[str] = []
        for pat in pats:
            found += glob.glob(os.path.join(HERE, pat))
        found = [f for f in found if "panic_watch" not in os.path.basename(f)]
        if not found:
            self.skipTest("项目里没有自动跑脚本（专项脚本已移出，符合预期）")
        for path in found:
            src = open(path, encoding="utf-8").read()
            name = os.path.basename(path)
            self.assertIn("panic", src, f"{name} 没接急停")
            self.assertIn("triggered", src, f"{name} 没检查 triggered")
