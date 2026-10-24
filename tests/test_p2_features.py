"""P2 能力的不变量测试（静态检查，不点鼠标）。

覆盖 2026-10-25 第二轮升级：
    · appkit：启动（Explorer shell）/ 等窗口 / 干净退出
    · anchor_mem：区域与列表项记忆（learn_region / locate_region / learn_item / locate_item）
    · ocr_ext：upscale / boost 参数（小字增强）
    · macro_ext：region_mem 引用、learn_region/learn_item、launch/wait_window/exit_app
    · recipes/***.json：把「必须走 shell 启动」这条坑固化下来
"""

from __future__ import annotations

import ast
import json
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


class TestAppKit(unittest.TestCase):
    def test_module_and_api(self) -> None:
        src = _read("appkit.py")
        ast.parse(src)
        for fn in ("find_shortcut", "shortcut_target", "launch",
                   "find_windows", "wait_window", "exit_app"):
            self.assertIn(f"def {fn}(", src, f"appkit 缺 {fn}")

    def test_launch_uses_explorer_shell(self) -> None:
        src = _read("appkit.py")
        self.assertIn("explorer.exe", src,
                      "launch 必须走 Explorer shell —— 直接 CreateProcess 会让部分应用静默秒退")

    def test_exit_documents_tray_residue(self) -> None:
        src = _read("appkit.py")
        self.assertIn("关窗不等于退出", src,
                      "exit_app 必须记住「关窗 ≠ 退出」，托盘驻留要显式结束进程")


class TestAnchorRegions(unittest.TestCase):
    def test_api_present(self) -> None:
        src = _read("anchor_mem.py")
        for fn in ("learn_region", "locate_region", "learn_item", "locate_item"):
            self.assertIn(f"def {fn}(", src, f"anchor_mem 缺 {fn}")
        self.assertIn("row_h", src, "列表项要有行高推算")
        self.assertIn("_now(", src)

    def test_region_uses_two_clues(self) -> None:
        src = _read("anchor_mem.py")
        self.assertIn('"nsize"', src, "区域要存归一化尺寸")
        self.assertIn('"corner"', src, "区域要存右下角偏移")


class TestOcrUpscale(unittest.TestCase):
    def test_signature_has_upscale(self) -> None:
        src = _read("ocr_ext.py")
        self.assertIn("upscale: float = 1.0", src, "ocr_read/find_text 要有 upscale")
        self.assertIn("boost: bool = False", src, "ocr_read/find_text 要有 boost")
        self.assertIn("def _enhance(", src, "要有增强函数")
        # 坐标必须换算回原始尺度，否则点击会偏移
        self.assertIn("min(xs) / _scale", src, "x 坐标必须除以缩放比")


class TestMacroP2(unittest.TestCase):
    def test_region_mem_and_ocr_flags(self) -> None:
        src = _read("macro_ext.py")
        self.assertIn("region_mem", src, "步骤要能引用记忆库里的区域")
        self.assertIn('step.get("upscale"', src, "宏步骤要能传 upscale")
        self.assertIn('step.get("boost"', src, "宏步骤要能传 boost")

    def test_new_actions(self) -> None:
        src = _read("macro_ext.py")
        for act in ("launch", "wait_window", "exit_app", "learn_region", "learn_item"):
            self.assertIn(f'"{act}"', src, f"macro_ext 缺动作 {act}")

    def test_allow_missing_window(self) -> None:
        src = _read("macro_ext.py")
        self.assertIn("allow_missing_window", src,
                      "允许宏先 launch/wait_window 再拿窗口")


class Test视频客户端（***）Recipe(unittest.TestCase):
    def test_launch_pitfall_recorded(self) -> None:
        p = os.path.join(HERE, "recipes", "***.json")
        self.assertTrue(os.path.isfile(p), "缺 recipes/***.json")
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
        launch = data.get("launch") or {}
        self.assertIn("explorer", json.dumps(launch, ensure_ascii=False).lower(),
                      "配方里必须写清「用 explorer shell 启动」")
        self.assertTrue(any("秒退" in x or "静默" in x for x in data.get("pitfalls", [])),
                        "配方里必须记录「直接启动会静默秒退」这个坑")


if __name__ == "__main__":
    unittest.main()
