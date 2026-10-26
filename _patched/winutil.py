"""winutil.py — 窗口健壮性小工具（通用，跟具体应用无关）

为什么单独抽出来（2026-10-27 实测教训）：

    ① **窗口句柄会被应用重建**
       Unity / Electron / CEF 类应用在切全屏、恢复最小化、重建渲染表面时，
       会把原来的 HWND 销毁再新建。之后所有 GetWindowRect / ClientToScreen
       都会抛 `(1400, '无效的窗口句柄')`，而动作本身"看起来执行了"。
       → 所以每次用句柄前都要能**自愈重找**。

    ② **自绘 UI 的点击会丢包**
       实测同一个按钮：间隔 0.32s 点 12 次只生效 6 次；改成 0.55~0.75s 全部生效。
       → 点击要能"慢一点 + 验证效果 + 失败重试"。

    ③ **前台与落点必须现场校验**
       窗口句柄有效、窗口也"可见"，但被别的窗口盖住时，
       点击会落到遮盖窗口上 —— 而截图、差异、看门狗一切正常。
       → 动手前先 `ensure_front()`，并用 WindowFromPoint 验证落点。
"""

from __future__ import annotations

import time

import win32con
import win32gui
import win32process


def is_alive(hwnd: int) -> bool:
    """句柄还指向一个真实窗口吗（不抛异常）。"""
    if not hwnd:
        return False
    try:
        return bool(win32gui.IsWindow(hwnd))
    except Exception:
        return False


def win_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """(left, top, width, height)；句柄失效返回 None（不抛异常）。"""
    if not is_alive(hwnd):
        return None
    try:
        l, t, r, b = win32gui.GetWindowRect(hwnd)
    except Exception:
        return None
    if r - l <= 0 or b - t <= 0:
        return None
    return (l, t, r - l, b - t)


def pid_of(hwnd: int) -> int:
    """进程号；无效句柄返回 0。

    坑：pywin32 对 hwnd=0 调 GetWindowThreadProcessId 会返回**垃圾值**
    （实测 -840758880），不是 0 —— 所以必须先判句柄有效。
    """
    if not hwnd or not is_alive(hwnd):
        return 0
    try:
        pid = int(win32process.GetWindowThreadProcessId(hwnd)[1])
        return pid if pid > 0 else 0
    except Exception:
        return 0


def find_window(title_contains: str = "", pid: int = 0,
                min_w: int = 200, min_h: int = 150,
                visible_only: bool = True) -> int:
    """按标题子串 / 进程号找窗口；找不到返回 0。"""
    found = []

    def cb(h, _):
        try:
            if visible_only and not win32gui.IsWindowVisible(h):
                return
            if title_contains and title_contains not in win32gui.GetWindowText(h):
                return
            if pid and pid_of(h) != pid:
                return
            r = win_rect(h)
            if not r or r[2] < min_w or r[3] < min_h:
                return
            found.append(h)
        except Exception:
            pass

    win32gui.EnumWindows(cb, None)
    return found[0] if found else 0


def heal(hwnd: int, title_contains: str = "", pid: int = 0) -> int:
    """句柄失效就按标题/进程重找一次；返回可用的句柄（0=找不到）。"""
    if is_alive(hwnd):
        return hwnd
    use_pid = pid if (pid and pid > 0) else pid_of(hwnd)
    # 没有"标题"也没有"进程号"就没法安全地重找 —— 空条件会命中第一个窗口，那是错的
    if not title_contains and use_pid <= 0:
        return 0
    return find_window(title_contains, use_pid if use_pid > 0 else 0)


def activate(hwnd: int) -> bool:
    """把窗口拉到前台并置顶；返回是否真的到了前台。"""
    if not is_alive(hwnd):
        return False
    try:
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                              win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
        if win32gui.GetForegroundWindow() == hwnd:
            return True
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            from computer_mcp import appkit

            appkit.activate(hwnd)
        time.sleep(0.25)
        return win32gui.GetForegroundWindow() == hwnd
    except Exception:
        return False


def point_owner(x: int, y: int) -> int:
    """屏幕坐标下落点属于哪个顶层窗口（用于判断是否被盖住）。"""
    import ctypes
    from ctypes import wintypes

    try:
        h = ctypes.windll.user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
        return int(ctypes.windll.user32.GetAncestor(h, 2) or 0)
    except Exception:
        return 0


def ensure_front(hwnd: int, probe: tuple[int, int] | None = None,
                 title_contains: str = "") -> tuple[int, bool]:
    """确认窗口在前台且（给点时）落点属于它。返回 (可用句柄, 是否就绪)。

    句柄失效会先尝试自愈重找；`probe` 是屏幕绝对坐标。
    """
    hwnd = heal(hwnd, title_contains)
    if not hwnd:
        return 0, False
    ok = activate(hwnd)
    if probe is not None:
        ok = point_owner(*probe) == hwnd
        if not ok:
            activate(hwnd)
            ok = point_owner(*probe) == hwnd
    return hwnd, ok
