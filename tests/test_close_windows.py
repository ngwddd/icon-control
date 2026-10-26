"""收尾关窗能力的不变量测试（静态检查）。

用户 2026-10-25 要求：「每次做完任务，把那些窗口给我关了，别每次都要我手动关。」
这个文件守住两件事：
    1. appkit 有 close_windows（只关窗、不杀进程，避免误杀用户正在用的应用）
    2. 宏里能直接调这个动作，收尾不用另外写脚本
"""

from __future__ import annotations

import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401

import ast
import os
import unittest

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


def _read(name: str) -> str:
    with open(os.path.join(_pkg_dir(), name), encoding="utf-8") as fh:
        return fh.read()


class TestCloseWindows(unittest.TestCase):
    def test_appkit_api(self) -> None:
        src = _read("appkit.py")
        ast.parse(src)
        self.assertIn("def close_windows(", src, "appkit 缺 close_windows")
        self.assertIn("WM_CLOSE", src, "关窗要用 WM_CLOSE，不要直接杀进程")

    def test_only_closes_does_not_kill(self) -> None:
        src = _read("appkit.py")
        start = src.index("def close_windows(")
        end = src.index("def _main(", start) if "def _main(" in src[start:] else len(src)
        body = src[start:end]
        self.assertNotIn(".terminate()", body,
                         "close_windows 只能关窗口，不能杀进程（会误伤用户正在用的应用）")
        self.assertNotIn(".kill()", body, "close_windows 不能 kill 进程")

    def test_cli_subcommand(self) -> None:
        src = _read("appkit.py")
        self.assertIn('cmd == "close"', src, "appkit CLI 要有 close 子命令")

    def test_macro_action(self) -> None:
        src = _read("macro_ext.py")
        self.assertIn('"close_windows"', src, "宏里要能直接调用关窗")
        self.assertIn("close_windows(", src)


class TestTaskFinishDoc(unittest.TestCase):
    def test_rules_live_in_skill_not_agents_md(self) -> None:
        """v0.5.0 起桌面规则搬到 skill/desktop-operator/。

        这条不变量改成：规则本体必须在 skill 里，AGENTS.md 只保留指针（不能断链）。
        """
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        skill = os.path.join(repo, "skill", "desktop-operator", "SKILL.md")
        self.assertTrue(os.path.isfile(skill), f"skill 缺失：{skill}")
        with open(skill, encoding="utf-8") as fh:
            skill_text = fh.read()
        self.assertIn("收尾", skill_text)
        self.assertTrue(
            "close_windows" in skill_text or "关窗" in skill_text,
            "skill 里要写明「任务收尾必须关窗」",
        )
        self.assertIn("desktop-operator", skill_text)

        agents = os.path.join(os.path.expanduser("~"), ".dsh", "AGENTS.md")
        if os.path.isfile(agents):
            with open(agents, encoding="utf-8") as fh:
                content = fh.read()
            self.assertIn("desktop-operator", content,
                          "AGENTS.md 要指向 skill（规则已迁出，不能断链）")

if __name__ == "__main__":
    unittest.main()
