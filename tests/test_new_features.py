"""新能力的不变量测试（不点鼠标、不读屏幕，纯静态检查）。

覆盖 2026-10-25 加的东西：
    · recipes/ 配方库结构完整
    · doctor.py 存在且可编译
    · macro_ext 新动作（clipboard_set/get、paste、assert_title/file/text）已注册
    · 宏引擎的 retry / repeat / 记忆库自动更新逻辑还在（防被后续补丁冲掉）
    · e2e 冒烟文件存在且默认跳过
"""

from __future__ import annotations

import ast
import json
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pkg_dir() -> str:
    """找到 computer_mcp 安装目录。

    系统 Python（跑 unittest 的那个）里没有装 computer_mcp —— 它只装在 venv 里，
    所以这里先试 import，失败就回退到 venv 的 site-packages 路径。
    """
    try:
        import computer_mcp  # noqa: F401
        return os.path.dirname(computer_mcp.__file__)
    except Exception:
        cand = os.path.join(HERE, "venv", "Lib", "site-packages", "computer_mcp")
        if os.path.isdir(cand):
            return cand
        raise


def _macro_src() -> str:
    with open(os.path.join(_pkg_dir(), "macro_ext.py"), encoding="utf-8") as fh:
        return fh.read()


class TestRecipes(unittest.TestCase):
    def test_recipes_present_and_valid(self) -> None:
        base = os.path.join(HERE, "recipes")
        self.assertTrue(os.path.isdir(base), "recipes/ 目录不存在")
        names = ["app-01", "app-02", "app-05", "app-06", "TextEditor"]
        for name in names:
            path = os.path.join(base, f"{name}.json")
            self.assertTrue(os.path.isfile(path), f"缺少配方 {name}.json")
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertIn("app", data, f"{name}.json 缺 app")
            self.assertIn("window", data, f"{name}.json 缺 window")
            self.assertIsInstance(data["window"], dict)
        self.assertTrue(os.path.isfile(os.path.join(base, "README.md")))


class TestDoctor(unittest.TestCase):
    def test_doctor_compiles(self) -> None:
        path = os.path.join(HERE, "doctor.py")
        self.assertTrue(os.path.isfile(path), "doctor.py 不存在")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        ast.parse(src)   # 语法必须过
        # 六个检查函数都要在
        for fn in ("check_identity", "check_display", "check_input",
                   "check_drivers", "check_patch", "check_memory"):
            self.assertIn(f"def {fn}(", src, f"doctor.py 缺 {fn}")
        # 判据必须是「TextEditor + 剪贴板回读」，不许用探针窗口计数
        self.assertIn("doctor_probe", src)
        self.assertNotIn("WM_LBUTTONDOWN", src, "doctor 不该再用探针窗口命中计数")


class TestMacroNewActions(unittest.TestCase):
    def test_new_actions_registered(self) -> None:
        src = _macro_src()
        for act in ("clipboard_set", "clipboard_get", "paste",
                    "assert_title", "assert_file", "assert_text"):
            self.assertIn(f'"{act}"', src, f"macro_ext 缺动作 {act}")

    def test_retry_and_repeat_logic(self) -> None:
        src = _macro_src()
        self.assertIn('step.get("retry", 1)', src, "retry 逻辑丢了")
        self.assertIn('get("repeat", 1)', src, "repeat 逻辑丢了")
        self.assertIn("queue.insert(0, (i, step))", src, "重投逻辑丢了")

    def test_memory_autoupdate(self) -> None:
        src = _macro_src()
        self.assertIn("memory_updated", src, "记忆库自动更新的标记丢了")
        self.assertIn("anchor_mem as _am_upd", src, "记忆库自动更新调用丢了")

    def test_single_definition_of_run_macro(self) -> None:
        src = _macro_src()
        self.assertEqual(src.count("def run_macro("), 1,
                         "run_macro 被定义了多次（后定义的会覆盖前一个）")


class TestE2EExists(unittest.TestCase):
    def test_e2e_file_default_skipped(self) -> None:
        path = os.path.join(HERE, "tests", "test_e2e_smoke.py")
        self.assertTrue(os.path.isfile(path), "缺 e2e 冒烟测试文件")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("DSH_E2E", src, "e2e 必须由 DSH_E2E=1 控制，默认跳过")
        self.assertIn("skipUnless", src)


if __name__ == "__main__":
    unittest.main()
