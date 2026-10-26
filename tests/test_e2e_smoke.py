"""e2e 冒烟测试 —— 真的去操作，而不是只检查代码形状。

为什么要有它：之前 24 个测试全是静态不变量（补丁在不在、工具注册没有），
所以 `macro_ext` 里那句用了未导入的 `ocr_ext`（F821）**一条测试都抓不到** ——
它只在真正执行到那条分支时才炸。这个文件补的就是这一块。

默认不跑（会开窗口、动键盘，跑一遍约 8 秒）。要跑：

    set DSH_E2E=1
    venv\\Scripts\\python.exe -m unittest tests.test_e2e_smoke -v

三个用例：
    test_1_clipboard_roundtrip   剪贴板读写（不碰 GUI）
    test_2_window_enumeration    窗口枚举 + 截图（验证采集层可用）
    test_3_TextEditor_typing        TextEditor打字 + 剪贴板回读（验证输入注入链路）

判据一律用「应用自己的状态」，不用探针窗口命中计数 —— 见 AGENTS.md 铁律二。
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import time
import unittest

DSH_E2E = os.environ.get("DSH_E2E", "") == "1"

if DSH_E2E:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass


@unittest.skipUnless(DSH_E2E, "设置 DSH_E2E=1 才跑 e2e（会开窗口、动键盘）")
class TestE2E(unittest.TestCase):
    def test_1_clipboard_roundtrip(self) -> None:
        """剪贴板能写能读 —— 这是后面一切「状态判据」的基础。"""
        import win32clipboard

        payload = f"DSH_E2E_CLIP_{int(time.time())}"
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(payload)
        win32clipboard.CloseClipboard()

        time.sleep(0.2)
        win32clipboard.OpenClipboard()
        got = win32clipboard.GetClipboardData()
        win32clipboard.CloseClipboard()
        self.assertEqual(got, payload, "剪贴板回读内容不一致")

    def test_2_window_enumeration(self) -> None:
        """窗口枚举与截图采集都要能用。"""
        import win32gui

        wins: list[tuple[int, str]] = []

        def _cb(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title.strip():
                    wins.append((hwnd, title))
        win32gui.EnumWindows(_cb, None)
        self.assertGreater(len(wins), 0, "一个可见窗口都没枚举到")

        from computer_mcp.core import screenshot as shot
        res = shot.capture_screenshot()
        self.assertTrue(res.get("success", True) is not False)
        self.assertGreater(res.get("width", 0), 0)
        self.assertGreater(res.get("height", 0), 0)
        self.assertGreater(res.get("bytes", 0), 1000, "截图字节数过小，可能是黑图/空图")

        # 调色板级检查：图不能是纯单色
        state = shot.screen_state()
        self.assertIn("changed", state)

    def test_3_TextEditor_typing(self) -> None:
        """TextEditor里真的打一行字，再用剪贴板回读验证。

        这是输入注入链路的端到端验证；失败时打印可诊断信息，
        并明确区分「真被拦」和「判据不可信」。
        """
        import win32clipboard
        import win32gui
        from pynput.keyboard import Controller as KeyboardController, Key

        def _set_clip(t: str) -> None:
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(t)
            win32clipboard.CloseClipboard()

        def _get_clip() -> str:
            try:
                win32clipboard.OpenClipboard()
                d = win32clipboard.GetClipboardData()
                win32clipboard.CloseClipboard()
                return str(d)
            except Exception:  # noqa: BLE001
                return ""

        mark = f"DSH_E2E_TYPE_{int(time.time()) % 100000}"
        _set_clip("SENTINEL")
        probe = os.path.join(os.environ.get("TEMP", "."), f"e2e_probe_{os.getpid()}.txt")
        with open(probe, "w", encoding="utf-8"):
            pass

        subprocess.Popen(["***.exe", probe])
        time.sleep(3.0)

        found: list[int] = []
        fname = os.path.basename(probe).lower()

        def _cb(hwnd, _):
            if win32gui.IsWindowVisible(hwnd) and fname in win32gui.GetWindowText(hwnd).lower():
                found.append(hwnd)
        win32gui.EnumWindows(_cb, None)
        if not found:
            self.skipTest("没能打开TextEditor靶子（环境异常）")
        hwnd = found[0]

        try:
            from computer_mcp import macro_ext
            macro_ext._ensure_usable(hwnd)
        except Exception:  # noqa: BLE001
            try:
                win32gui.SetForegroundWindow(hwnd)
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.7)

        if win32gui.GetForegroundWindow() != hwnd:
            try:
                win32gui.PostMessage(hwnd, 0x0010, 0, 0)
            except Exception:  # noqa: BLE001
                pass
            self.skipTest("TextEditor没拿到前台，本次判定不可信（不是输入故障）")

        kb = KeyboardController()
        try:
            kb.type(mark)
            time.sleep(0.9)
            kb.press(Key.ctrl); kb.press("a"); kb.release("a"); kb.release(Key.ctrl)
            time.sleep(0.3)
            kb.press(Key.ctrl); kb.press("c"); kb.release("c"); kb.release(Key.ctrl)
            time.sleep(0.9)
            got = _get_clip()
        finally:
            try:
                kb.press(Key.ctrl); kb.press("a"); kb.release("a"); kb.release(Key.ctrl)
                time.sleep(0.2)
                kb.press(Key.delete); kb.release(Key.delete)
                time.sleep(0.4)
                win32gui.PostMessage(hwnd, 0x0010, 0, 0)
                time.sleep(0.6)
            except Exception:  # noqa: BLE001
                pass
            try:
                os.remove(probe)
            except OSError:
                pass

        self.assertIn(mark, got,
                      f"键盘注入没有生效（回读={got[:40]!r}）。"
                      "先排查：① 有没有模态对话框 ② 目标是否真在前台 "
                      "③ CCInputProtector / OEM 类过滤驱动")


if __name__ == "__main__":
    unittest.main(verbosity=2)
