"""diag_input.py — 分清「哪一层输入被拦」，而不是笼统地说"自动化坏了"。

分三层独立测试：
    L1 光标移动      SetCursorPos           （不经过 SendInput）
    L2 鼠标点击      SendInput(MOUSE)       （经过 SendInput）
    L3 键盘输入      SendInput(KEY) + 观察效果

用法：
    venv\\Scripts\\python.exe diag_input.py            # 三层都测
    venv\\Scripts\\python.exe diag_input.py --target 即时通讯软件（***）

判定逻辑：
    移动 OK + 点击/按键 无效  -> SendInput 被系统级拦截
        （常见原因：安全软件"防模拟输入"、Windows BlockInput、
          驱动级反作弊、UIPI 提权向低权限转发被策略禁止）
    三层都无效                -> 进程没有桌面/输入权限（会话隔离）
    全都 OK                   -> 输入链路正常，问题在应用层（如 CEF 拒收）
"""

from __future__ import annotations

import argparse
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import win32con  # noqa: E402
import win32gui  # noqa: E402


def _safe_foreground(hwnd) -> None:
    """Windows 经常拒绝 SetForegroundWindow，这里吞掉异常（诊断脚本不该因它中断）。"""
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        try:
            import win32con as _wc
            win32gui.ShowWindow(hwnd, _wc.SW_SHOW)
            win32gui.BringWindowToTop(hwnd)
        except Exception:
            pass


def _mouse_move_ok() -> dict:
    """L1: SetCursorPos 是否生效（不经过 SendInput）。"""
    from pynput.mouse import Controller

    m = Controller()
    a, b = (300, 300), (700, 500)
    m.position = a
    time.sleep(0.15)
    real_a = win32gui.GetCursorPos()
    m.position = b
    time.sleep(0.15)
    real_b = win32gui.GetCursorPos()
    # 允许容差：人类可能在动鼠标，精确相等会把"人在动"误判成"被拦"
    def near(p, q, tol=25):
        return abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol

    ok = near(real_a, a) and near(real_b, b)
    return {"layer": "L1 光标移动(SetCursorPos)", "ok": ok,
            "detail": f"{real_a} -> {real_b} (容差 25px)"}


def _mouse_click_ok(target_title: str | None) -> dict:
    """L2: SendInput 点击 —— 用「点自己的测试窗口并观察状态」来判定。"""
    from pynput.mouse import Button, Controller

    # 用一个自建的 win32 窗口当靶子：点它，它会记录收到的 WM_LBUTTONDOWN
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                 ctypes.c_size_t, ctypes.c_ssize_t)
    hits = []

    # DefWindowProcW 的 LRESULT/LPARAM 是 64 位，必须显式声明类型，否则会 Overflow
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                      ctypes.c_size_t, ctypes.c_ssize_t]
    user32.DefWindowProcW.restype = ctypes.c_ssize_t

    def _proc(hwnd, msg, wp, lp):
        if msg == win32con.WM_LBUTTONDOWN:
            hits.append(1)
        return user32.DefWindowProcW(hwnd, msg, ctypes.c_size_t(wp), ctypes.c_ssize_t(lp))

    proc = WNDPROC(_proc)
    hinst = kernel32.GetModuleHandleW(None)

    class WNDCLASS(ctypes.Structure):
        _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                    ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                    ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

    cls = WNDCLASS()
    cls.lpfnWndProc = proc
    cls.hInstance = hinst
    cls.lpszClassName = "对话壳（***）_INPUT_PROBE"
    user32.RegisterClassW(ctypes.byref(cls))
    hwnd = user32.CreateWindowExW(0, "对话壳（***）_INPUT_PROBE", "对话壳（***） input probe",
                                  win32con.WS_OVERLAPPEDWINDOW | win32con.WS_VISIBLE,
                                  600, 300, 300, 200, None, None, hinst, None)
    if not hwnd:
        return {"layer": "L2 鼠标点击(SendInput)", "ok": None, "detail": "无法创建测试窗口"}

    # 用项目里那套「AttachThreadInput 强前台 + 校验」的办法，否则会假阴性
    try:
        from computer_mcp import macro_ext
        macro_ext._ensure_usable(hwnd)
    except Exception:
        _safe_foreground(hwnd)
    time.sleep(0.6)
    fg = win32gui.GetForegroundWindow()
    fg_ok = (fg == hwnd)
    # 确认点击落点确实在该窗口上
    # 探针窗口建在 (600,300) 300x200 -> 覆盖 (600,300)-(900,500)，必须点在窗口内部
    probe_pt = (700, 380)
    hit = win32gui.WindowFromPoint(probe_pt)
    same_window = (hit == hwnd)
    m = Controller()
    m.position = probe_pt
    time.sleep(0.25)
    m.click(Button.left, 1)
    time.sleep(0.6)
    user32.DestroyWindow(hwnd)
    if not (fg_ok or same_window):
        return {"layer": "L2 鼠标点击(SendInput)", "ok": None,
                "detail": f"无法让探针窗口获得焦点/命中（前台={fg}），本次判定不可信"}
    ok = len(hits) > 0
    return {"layer": "L2 鼠标点击(SendInput)", "ok": ok,
            "detail": f"测试窗口收到 {len(hits)} 次 WM_LBUTTONDOWN"}


def _keyboard_ok() -> dict:
    """L3: 用「系统文本编辑器打字 + Ctrl+A/Ctrl+C + 剪贴板回读」判定，这是唯一可靠的判据。

    为什么不用自建探针窗口：
      探针窗口常常抢不到前台（被其它窗口盖住），点击/按键落到别人身上，
      于是把"输入正常"误报成"被拦截"。用应用自身状态做判据就没有这个坑。
    """
    import subprocess
    import win32clipboard
    from pynput.keyboard import Controller, Key

    def _set_clip(t):
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(t)
        win32clipboard.CloseClipboard()

    def _get_clip():
        try:
            win32clipboard.OpenClipboard()
            d = win32clipboard.GetClipboardData()
            win32clipboard.CloseClipboard()
            return d
        except Exception:
            return ""

    mark = "对话壳（***）_INPUT_PROBE_OK"
    _set_clip("SENTINEL")

    # 用一个已存在的空文件打开系统文本编辑器，避免「找不到文件」模态框吞按键
    f = os.path.join(os.environ.get("TEMP", "."), "dsh_input_probe.txt")
    try:
        with open(f, "w", encoding="utf-8"):
            pass
    except OSError:
        pass
    subprocess.Popen(["***.exe", f])
    time.sleep(3.0)

    cands = []
    def _cb(h, _):
        if not win32gui.IsWindowVisible(h):
            return
        t = win32gui.GetWindowText(h)
        if "dsh_input_probe" in t.lower() or "系统文本编辑器" in t or "系统文本编辑器" in t:
            cands.append(h)
    win32gui.EnumWindows(_cb, None)
    if not cands:
        return {"layer": "L3 键盘输入(SendInput)", "ok": None, "detail": "没找到系统文本编辑器窗口"}
    hwnd = cands[0]

    fg_ok = False
    try:
        from computer_mcp import macro_ext
        macro_ext._ensure_usable(hwnd)
        time.sleep(0.7)
        fg_ok = (win32gui.GetForegroundWindow() == hwnd)
    except Exception:
        try:
            win32gui.SetForegroundWindow(hwnd)
            fg_ok = (win32gui.GetForegroundWindow() == hwnd)
        except Exception:
            pass

    kb = Controller()
    kb.type(mark)
    time.sleep(0.8)
    kb.press(Key.ctrl); kb.press("a"); kb.release("a"); kb.release(Key.ctrl)
    time.sleep(0.3)
    kb.press(Key.ctrl); kb.press("c"); kb.release("c"); kb.release(Key.ctrl)
    time.sleep(0.9)
    got = str(_get_clip())
    ok = mark in got

    # 收拾：清空内容并关闭，不写盘
    try:
        kb.press(Key.ctrl); kb.press("a"); kb.release("a"); kb.release(Key.ctrl)
        time.sleep(0.2)
        kb.press(Key.delete); kb.release(Key.delete)
        time.sleep(0.4)
        win32gui.PostMessage(hwnd, 0x0010, 0, 0)   # WM_CLOSE
        time.sleep(0.8)
    except Exception:
        pass

    detail = f"前台={'是' if fg_ok else '否'}，回读={got[:32]!r}"
    if not fg_ok:
        return {"layer": "L3 键盘输入(SendInput)", "ok": None,
                "detail": f"系统文本编辑器没拿到前台，判定不可信（{detail}）"}
    return {"layer": "L3 键盘输入(SendInput)", "ok": ok,
            "detail": "系统文本编辑器里打进去的字被成功回读" if ok else detail}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", help="额外测试某个窗口标题（可选）")
    args = ap.parse_args()

    print("=== 输入链路三层诊断 ===")
    results = [_mouse_move_ok(), _keyboard_ok()]
    for r in results:
        mark = {True: "OK", False: "**被拦**", None: "无法判定"}[r["ok"]]
        print(f"  {r['layer']:26} {mark:10} {r['detail']}")

    mv, kb = results[0]["ok"], results[1]["ok"]
    clk = kb
    print("\n=== 结论 ===")
    if mv and not clk and not kb:
        print("  SendInput 被系统级拦截（光标能移动，但点击/按键不生效）")
        print("  常见原因：安全软件『防模拟输入/系统加固』、Windows BlockInput、")
        print("            反作弊驱动、或组策略禁止注入。")
        print("  处理：查安全软件的拦截日志并给 python.exe / 游戏或目标程序加白名单。")
        return 2
    if not mv and not clk and not kb:
        print("  三层全废：进程可能没有桌面输入权限（会话隔离 / 以服务身份运行）。")
        return 3
    if mv and clk and kb:
        print("  输入链路正常。如果某个应用仍无反应，那是该应用自己拒收（CEF/自绘 UI），")
        print("  这时改用鼠标点击 + 记忆库坐标，不要依赖键盘输入。")
        return 0
    print("  部分可用，见上面每行的明细。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
