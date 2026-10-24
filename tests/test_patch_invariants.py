"""Regression tests for the desktop-automation MCP patch.

These are *invariant* tests: they do not move the mouse or read the screen.
They only assert that the things we deliberately changed are still in place,
so that reinstalling/upgrading `computer-mcp` cannot silently undo them
(the failure mode we actually hit: a duplicated `_grab` definition quietly
overrode the fixed one).

Runs under any Python 3.11+ with the standard library only:
    python -m unittest discover -s tests -p "test_*.py"
"""

from __future__ import annotations

import ast
import json
import pathlib
import re
import sys
import unittest

HERE = pathlib.Path(__file__).resolve()
PROJECT = HERE.parents[1]                     # ...\desktop-mcp
PKG = PROJECT / "venv" / "Lib" / "site-packages" / "computer_mcp"
MACROS = PROJECT / "macros"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _defined_names(path: pathlib.Path) -> list[str]:
    tree = ast.parse(_read(path))
    return [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


class TestProjectLayout(unittest.TestCase):
    def test_own_scripts_exist(self):
        for name in ("desk.py", "clean.py", "app_facts.md", "_tray_walk.py"):
            self.assertTrue((PROJECT / name).is_file(), f"缺少 {name}")

    def test_patched_package_is_present(self):
        self.assertTrue(PKG.is_dir(), f"找不到打过补丁的包：{PKG}")
        for name in ("ui_ext.py", "macro_ext.py", "ocr_ext.py", "mcp.py", "cli.py"):
            self.assertTrue((PKG / name).is_file(), f"缺少补丁文件 {name}")


class TestCapturePatch(unittest.TestCase):
    """core/screenshot.py: 缩放 + JPEG + 变化检测。"""

    def setUp(self):
        self.src = _read(PKG / "core" / "screenshot.py")

    def test_config_keys(self):
        for key in ("scale", "quality", "format", "mask_bottom", "diff_threshold"):
            self.assertIn(f'"{key}"', self.src, f"缺少配置项 {key}")

    def test_diff_functions(self):
        names = _defined_names(PKG / "core" / "screenshot.py")
        for fn in ("_mean_abs_diff", "_small_gray", "_update_diff", "screen_state", "wait_for_change"):
            self.assertIn(fn, names, f"缺少函数 {fn}")

    def test_returns_change_info(self):
        for key in ("changed", "diff", "source_width", "hash"):
            self.assertIn(f'"{key}":', self.src, f"截图返回里缺少 {key}")

    def test_taskbar_is_masked(self):
        self.assertIn("mask_bottom", self.src)
        self.assertIn("crop(", self.src, "变化检测应当裁掉任务栏再比对")


class TestExtensionModules(unittest.TestCase):
    def test_ui_ext_helpers(self):
        names = _defined_names(PKG / "ui_ext.py")
        for fn in ("ui_tree", "ui_find", "ui_click", "ui_invoke", "ui_set_text",
                   "run_batch", "resolve_key"):
            self.assertIn(fn, names, f"ui_ext 缺少 {fn}")

    def test_macro_ext_helpers(self):
        names = _defined_names(PKG / "macro_ext.py")
        for fn in ("run_macro", "macro_list", "macro_save", "_find_window",
                   "_ensure_usable", "_force_foreground", "_resolve_point", "_resolve_region"):
            self.assertIn(fn, names, f"macro_ext 缺少 {fn}")

    def test_ocr_ext_helpers(self):
        names = _defined_names(PKG / "ocr_ext.py")
        for fn in ("ocr_read", "find_text", "click_text", "_print_window",
                   "_grab", "_looks_blank", "_norm", "_lcs_len"):
            self.assertIn(fn, names, f"ocr_ext 缺少 {fn}")

    def test_anchor_memory_module(self):
        """记忆库：归一化坐标 + 多视觉原型 + 计数器。"""
        names = _defined_names(PKG / "anchor_mem.py")
        for fn in ("learn", "locate", "verify", "confirm", "list_all", "forget", "stats", "ahash"):
            self.assertIn(fn, names, f"anchor_mem 缺少 {fn}")
        src = _read(PKG / "anchor_mem.py")
        self.assertIn("prototypes", src, "缺少多原型存储（外观随状态变）")
        self.assertIn("dx_right", src, "缺少右下角偏移（抗缩放）")
        # 宏里必须有 anchor_click 分支
        self.assertIn('action == "anchor_click"', _read(PKG / "macro_ext.py"))

    def test_click_coordinates_use_window_rect(self):
        """点击必须和 OCR/PrintWindow 用同一坐标系（窗口矩形），否则系统性偏边框。"""
        src = _read(PKG / "macro_ext.py")
        names = _defined_names(PKG / "macro_ext.py")
        self.assertIn("window_metrics", names, "缺少校准函数 window_metrics")
        self.assertIn("_refresh_geometry", names, "缺少几何刷新 _refresh_geometry")
        self.assertIn('"rect_x"', src, "_find_window 没有返回窗口矩形几何")
        # 换算函数里必须优先用 rect_*
        for fn in ("_resolve_point", "_resolve_region"):
            tree = ast.parse(src)
            node = next((n for n in ast.walk(tree)
                         if isinstance(n, ast.FunctionDef) and n.name == fn), None)
            self.assertIsNotNone(node, f"缺少 {fn}")
            body = ast.get_source_segment(src, node) or ""
            self.assertIn("rect_x", body, f"{fn} 没有使用 rect_x（会退回客户区，偏边框）")

    def test_page_reconcile_actions_exist(self):
        """三阶段对账：page_check / ensure_page + 指纹函数。"""
        src = _read(PKG / "macro_ext.py")
        self.assertIn('action in ("page_check", "ensure_page")', src,
                      "macro_ext 缺少 page_check / ensure_page 分支")
        self.assertIn("def _fingerprint(", src, "macro_ext 缺少 _fingerprint")
        names = _defined_names(PKG / "macro_ext.py")
        self.assertIn("_fingerprint", names)

    def test_no_duplicate_grab_definition(self):
        """曾经因为两个 _grab 定义，后一个悄悄覆盖了修复版。"""
        src = _read(PKG / "ocr_ext.py")
        self.assertEqual(len(re.findall(r"^def _grab\(", src, re.M)), 1,
                         "ocr_ext.py 里 _grab 被定义了不止一次")


class TestToolRegistration(unittest.TestCase):
    """mcp.py 必须把 16 个新增工具都注册上，否则 MCP 里看不到。"""

    NEW_TOOLS = [
        "screen_state", "wait_for_change", "capture_config",
        "batch", "ui_tree", "ui_find", "ui_click", "ui_invoke", "ui_set_text",
        "macro_list", "macro_save", "macro_run",
        "ocr_read", "find_text", "click_text",
    ]

    def setUp(self):
        self.src = _read(PKG / "mcp.py")

    def test_every_new_tool_registered(self):
        missing = [t for t in self.NEW_TOOLS if f'name="{t}"' not in self.src]
        self.assertEqual(missing, [], f"未注册的工具：{missing}")

    def test_every_new_tool_dispatched(self):
        """每个工具都要么有 `elif name == "x"`，要么在某个 `name in (...)` 元组里。"""
        missing = []
        for tool in self.NEW_TOOLS:
            if f'name == "{tool}"' in self.src:
                continue
            if f'in ("{tool}"' in self.src or f'("{tool}",' in self.src or f', "{tool}")' in self.src:
                continue
            missing.append(tool)
        self.assertEqual(missing, [], f"注册了但没有分发：{missing}")

    def test_stdout_patch_kept(self):
        """cli.py 曾经把启动横幅打到 stdout，破坏 JSON-RPC。"""
        lines = [ln for ln in _read(PKG / "cli.py").splitlines() if "stdio mode" in ln]
        self.assertTrue(lines, "cli.py 里找不到 stdio 启动横幅，测试需要更新")
        bad = [ln.strip() for ln in lines if "file=sys.stderr" not in ln]
        self.assertEqual(bad, [], "启动横幅会打到 stdout，破坏 JSON-RPC")


class TestMacros(unittest.TestCase):
    def _macros(self):
        if not MACROS.is_dir():
            return {}
        out = {}
        for p in MACROS.glob("*.json"):
            out[p.name] = json.loads(_read(p))
        return out

    def test_macros_are_valid_json(self):
        for name, spec in self._macros().items():
            self.assertIn("name", spec, f"{name} 缺少 name")
            self.assertIsInstance(spec.get("steps"), list, f"{name} 缺少 steps")
            self.assertGreater(len(spec["steps"]), 0, f"{name} 步骤为空")

    def test_macros_declare_their_placeholders(self):
        for name, spec in self._macros().items():
            used = set(re.findall(r"\$\{(\w+)\}", json.dumps(spec, ensure_ascii=False)))
            declared = set((spec.get("defaults") or {}).keys())
            undeclared = used - declared - {"text"}
            self.assertEqual(undeclared, set(),
                             f"{name} 用了未声明默认值的占位符 {undeclared}")

    def test_send_macro_uses_enter_not_send_button(self):
        """实测：点「发送」按钮无效，必须用回车。"""
        spec = self._macros().get("app-01_send.json")
        if not spec:
            self.skipTest("没有 app-01_send 宏")
        actions = [s.get("action") for s in spec["steps"]]
        self.assertIn("key", actions, "发送宏应当用 key=enter，而不是点发送按钮")
        keys = [s.get("key") for s in spec["steps"] if s.get("action") == "key"]
        self.assertIn("enter", keys)


class TestCleanScript(unittest.TestCase):
    """clean.py 必须既能清垃圾，又绝不能误删资产。"""

    def setUp(self):
        sys.path.insert(0, str(PROJECT))
        try:
            import importlib

            self.clean = importlib.import_module("clean")
        finally:
            sys.path.pop(0)

    def test_assets_are_never_matched(self):
        for name in ("desk.py", "clean.py", "_tray_walk.py", "reapply.py",
                     "ui_ext.py", "macro_ext.py", "ocr_ext.py", "cli.py"):
            self.assertIn(name.upper(), {k.upper() for k in self.clean.KEEP_NAMES},
                          f"{name} 可能被清理脚本删掉")

    def test_temp_scratch_patterns_match(self):
        pats = self.clean.TEMP_PATTERNS
        for name in ("t_wallet0.py", "patch_key.py", "run_tight.json", "desk_err.txt"):
            self.assertTrue(any(re.match(p, name) for p in pats),
                            f"{name} 应该被识别为本次任务的临时文件")

    def test_user_files_are_not_matched(self):
        pats = self.clean.TEMP_PATTERNS + self.clean.TOOL_PATTERNS
        for name in ("app_facts.md", "app-01_send.json", "报告.docx", "invoice.pdf"):
            self.assertFalse(any(re.match(p, name) for p in pats),
                             f"{name} 不应被当成垃圾")


class TestPatchDrift(unittest.TestCase):
    """_patched/ 是补丁的数据源（reapply.py 从这里覆盖安装）。
    两边不一致意味着「改了 venv 但忘了同步」。"""

    PAIRS = {
        "core_screenshot.py": ("core", "screenshot.py"),
        "mcp.py": (None, "mcp.py"),
        "cli.py": (None, "cli.py"),
        "ui_ext.py": (None, "ui_ext.py"),
        "macro_ext.py": (None, "macro_ext.py"),
        "ocr_ext.py": (None, "ocr_ext.py"),
        "anchor_mem.py": (None, "anchor_mem.py"),
    }

    def _installed(self, sub, name):
        return (PKG / sub / name) if sub else (PKG / name)

    def test_patched_copy_matches_installed(self):
        drift = []
        for src_name, (sub, name) in self.PAIRS.items():
            a = PROJECT / "_patched" / src_name
            b = self._installed(sub, name)
            if not a.is_file():
                drift.append(f"{src_name}: _patched 里缺失")
            elif not b.is_file():
                drift.append(f"{src_name}: 安装副本缺失")
            elif a.read_bytes() != b.read_bytes():
                drift.append(f"{src_name}: 与安装副本不一致（需同步或重打补丁）")
        self.assertEqual(drift, [], "; ".join(drift))

    def test_reapply_knows_every_patch_file(self):
        src = _read(PROJECT / "_patched" / "reapply.py")
        missing = [n for n in self.PAIRS if f'"{n}"' not in src]
        self.assertEqual(missing, [], f"reapply.py 的 FILES 列表缺少：{missing}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
