"""vision_state 工具集的不变量测试（2026-10-25 加的通用视觉状态能力）。

守六件事：
    1. `computer_mcp/vision_state.py` 存在且 API 齐全
    2. 10 个新工具都注册在 `list_tools()` 里
    3. 10 个工具都有分发分支（名字出现在 call_tool 的 if/elif 链里）
    4. `macro_ext.py` 有 7 个新宏动作
    5. 名字清洗 / 空名拒绝 / 存储目录布局
    6. `_patched/` 与 venv 安装副本字节一致（防补丁漂移）

这些测试不需要显示器、不点鼠标、不读屏幕。
"""

from __future__ import annotations

import ast
import asyncio
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

import sys

# 系统 Python 里常常没有装 computer_mcp（只在 venv 里）——先尝试把 venv 的
# site-packages 挂上去，仍然导入不了就跳过依赖它的用例，而不是报错。
if os.path.isdir(os.path.join(HERE, "venv", "Lib", "site-packages")):
    sys.path.insert(0, os.path.join(HERE, "venv", "Lib", "site-packages"))

try:
    from computer_mcp import vision_state as _vs_probe
    HAVE_VS = _vs_probe is not None    # 探测可导入性：引用一下
except Exception:
    HAVE_VS = False

try:
    import cv2 as _cv2
    HAVE_CV2 = _cv2 is not None        # 探测可导入性：引用一下
except Exception:
    HAVE_CV2 = False

NEED_VS = unittest.skipUnless(HAVE_VS, "当前解释器导不进 computer_mcp.vision_state")
_ = HAVE_CV2

NEW_TOOLS = [
    "capture_template", "match_template", "wait_template", "click_template",
    "set_baseline", "diff_baseline", "wait_baseline_change",
    "sample_stable", "hover_probe", "vision_list",
]
NEW_ACTIONS = ["capture_template", "assert_template", "set_baseline", "assert_baseline",
               "wait_template", "sample_stable", "hover_probe"]


def _pkg() -> str:
    try:
        import computer_mcp  # noqa: F401
        return os.path.dirname(computer_mcp.__file__)
    except Exception:
        cand = os.path.join(HERE, "venv", "Lib", "site-packages", "computer_mcp")
        if os.path.isdir(cand):
            return cand
        raise unittest.SkipTest("找不到 computer_mcp 安装副本")


class TestVisionModule(unittest.TestCase):
    def test_module_and_api(self) -> None:
        p = os.path.join(_pkg(), "vision_state.py")
        self.assertTrue(os.path.isfile(p), "缺 computer_mcp/vision_state.py")
        src = open(p, encoding="utf-8").read()
        ast.parse(src)
        for fn in ("capture_template", "match_template", "wait_template", "click_template",
                   "set_baseline", "diff_baseline", "wait_baseline_change",
                   "sample_stable", "hover_probe", "list_templates", "delete_template", "stats"):
            self.assertIn(f"def {fn}(", src, f"vision_state 缺 {fn}")

    def test_gray_handles_grab_tuple(self) -> None:
        """_grab 返回 (img, ox, oy) —— 这个坑踩过一次，测试守住。"""
        src = open(os.path.join(_pkg(), "vision_state.py"), encoding="utf-8").read()
        self.assertIn("img, ox, oy = ocr_ext._grab", src)

    @NEED_VS
    def test_name_sanitising(self) -> None:
        from computer_mcp import vision_state as vs
        self.assertEqual(vs._safe_name('a/b:c*?"'), "a_b_c___")
        with self.assertRaises(ValueError):
            vs._safe_name("   ")

    @NEED_VS
    def test_stats_shape(self) -> None:
        from computer_mcp import vision_state as vs
        s = vs.stats()
        for k in ("elapsed_s", "calls", "failures", "retries", "by_op", "failure_rate"):
            self.assertIn(k, s)


class TestToolsRegistered(unittest.TestCase):
    @NEED_VS
    def test_all_new_tools_listed(self) -> None:
        import computer_mcp.mcp as m
        tools = asyncio.run(m.list_tools())
        names = {t.name for t in tools}
        missing = [n for n in NEW_TOOLS if n not in names]
        self.assertEqual(missing, [], f"这些新工具没注册: {missing}")
        self.assertGreaterEqual(len(names), 50, f"工具总数异常偏少: {len(names)}")

    def test_all_new_tools_dispatched(self) -> None:
        src = open(os.path.join(_pkg(), "mcp.py"), encoding="utf-8").read()
        missing = [n for n in NEW_TOOLS if f'name == "{n}"' not in src]
        self.assertEqual(missing, [], f"这些工具没有分发分支: {missing}")


class TestMacroActions(unittest.TestCase):
    def test_actions_present(self) -> None:
        src = open(os.path.join(_pkg(), "macro_ext.py"), encoding="utf-8").read()
        for a in NEW_ACTIONS:
            self.assertIn(f'"{a}"', src, f"macro_ext 缺动作 {a}")

    def test_vision_import_is_lazy(self) -> None:
        """宏里用迟到导入，避免没装 cv2 的环境在 import 阶段就炸。"""
        src = open(os.path.join(_pkg(), "macro_ext.py"), encoding="utf-8").read()
        idx = src.find('elif action in ("capture_template"')
        self.assertGreater(idx, 0)
        segment = src[idx:idx + 400]
        self.assertIn("from computer_mcp import vision_state", segment)


class TestPatchedInSync(unittest.TestCase):
    def test_copies_match(self) -> None:
        pkg = _pkg()
        for f in ("vision_state.py", "mcp.py", "macro_ext.py"):
            a = os.path.join(pkg, f)
            b = os.path.join(HERE, "_patched", f)
            self.assertTrue(os.path.isfile(b), f"缺 _patched/{f}")
            self.assertEqual(open(a, "rb").read(), open(b, "rb").read(),
                             f"{f} 漂移了（改完 venv 里的必须同步回 _patched）")


if __name__ == "__main__":
    unittest.main()
