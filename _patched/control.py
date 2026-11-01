"""control.py — 桌面控制权归属（Z0 治理，P0-1）

为什么要有这个：`permission` 只管「用户是否允许 agent 动鼠标」，是**一次性开关**；
但真实使用中用户随时会想「别动了，我来」。Windows-MCP 的做法是：AI 操作时屏幕
边缘发光，**物理鼠标一动就把控制权还给用户**，闲置 10 秒后恢复给 AI。

本模块提供同样的语义：
    owner = "ai"    代理持有控制权
    owner = "user"  用户接管（期间输入类工具一律被拒）
    owner = "idle"  谁都没动，等待下一个动作

关键难点：pynput 的全局监听器**也会看到我们自己注入的事件**。所以注入前后要
开一个「静默窗」（默认 250 ms），窗内的输入事件不算用户接管，否则 AI 每点一下
都会把自己锁死。

对外：
    status()          读状态（给 control_status 工具）
    claim(reason)     申请控制权
    release(reason)   主动交还
    blocking_reason() 给 permission 闸门用：返回 None 表示放行
    quiet(ms)         注入静默窗（注入类工具在调用前后用）
"""

from __future__ import annotations

import os
import threading
import time

STATE = {
    "owner": "idle",
    "since": time.time(),
    "last_user": 0.0,
    "last_inject": 0.0,
    "takeovers": 0,
    "reason": "",
}

# 用户接管后多久自动恢复（秒）。Windows-MCP 用 10 秒。
IDLE_RESUME_S = float(os.environ.get("DSH_CONTROL_IDLE_S", "10"))
# 注入静默窗（秒）：我们自己注入的事件不算用户输入
QUIET_S = float(os.environ.get("DSH_CONTROL_QUIET_S", "0.25"))
# 总开关
ENABLED = os.environ.get("DSH_CONTROL", "on").strip().lower() not in {"0", "off", "false", "no"}

_lock = threading.RLock()
_watchers = {"mouse": None, "keyboard": None}
_started = False


def enabled() -> bool:
    return ENABLED


def _now() -> float:
    return time.time()


def _set(owner: str, reason: str = "") -> None:
    with _lock:
        STATE["owner"] = owner
        STATE["since"] = _now()
        STATE["reason"] = reason


def quiet(ms: float | None = None) -> float:
    """标记「刚注入了输入」，返回静默窗长度（秒）。"""
    with _lock:
        STATE["last_inject"] = _now()
    return (ms / 1000.0) if ms else QUIET_S


def _in_quiet() -> bool:
    return (_now() - STATE["last_inject"]) < QUIET_S


def note_physical(reason: str = "physical input") -> None:
    """记录一次真实用户输入：若当前由 AI 持有，立刻交还。"""
    if not ENABLED:
        return
    if _in_quiet():
        return
    with _lock:
        STATE["last_user"] = _now()
        if STATE["owner"] == "ai":
            STATE["takeovers"] += 1
            STATE["owner"] = "user"
            STATE["since"] = _now()
            STATE["reason"] = reason


def claim(reason: str = "agent") -> dict:
    ensure_watcher()
    with _lock:
        STATE["owner"] = "ai"
        STATE["since"] = _now()
        STATE["reason"] = reason
    return status()


def release(reason: str = "agent released") -> dict:
    with _lock:
        STATE["owner"] = "user" if STATE["last_user"] else "idle"
        STATE["since"] = _now()
        STATE["reason"] = reason
        STATE["last_user"] = _now()
    return status()


def status() -> dict:
    now = _now()
    with _lock:
        owner = STATE["owner"]
        idle_s = now - max(STATE["since"], STATE["last_user"])
        takeovers = STATE["takeovers"]
        reason = STATE["reason"]
    # 用户接管后闲置够久 → 自动回到 idle，允许 AI 再次申请
    if owner == "user" and idle_s >= IDLE_RESUME_S:
        _set("idle", f"用户闲置 {int(idle_s)}s，控制权已释放")
        owner = "idle"
        with _lock:
            idle_s = now - max(STATE["since"], STATE["last_user"])
            reason = STATE["reason"]
    return {
        "ok": True,
        "owner": owner,
        "takeover": owner == "user",
        "idle_s": round(idle_s, 1),
        "takeovers": takeovers,
        "idle_resume_s": IDLE_RESUME_S,
        "enabled": ENABLED,
        "reason": reason,
        "watcher": bool(_watchers["mouse"] or _watchers["keyboard"]),
    }


def blocking_reason() -> str | None:
    """给闸门用：非 None 表示当前不该注入输入。"""
    if not ENABLED:
        return None
    st = status()
    if st["owner"] == "user":
        return (f"用户已接管控制权（{st['idle_s']}s 前），"
                f"再闲置 {max(0, round(st['idle_resume_s'] - st['idle_s']))}s 才恢复")
    return None


# ── 全局监听：只在第一次 claim 时启动 ────────────────────────────────
def ensure_watcher() -> bool:
    """启动 pynput 全局监听（幂等）。拿不到权限就静默失败。"""
    global _started
    if _started or not ENABLED:
        return bool(_watchers["mouse"] or _watchers["keyboard"])
    _started = True
    try:
        from pynput import keyboard as kb
        from pynput import mouse as ms

        def on_move(x, y):
            note_physical("mouse move")

        def on_click(x, y, button, pressed):
            if pressed:
                note_physical("mouse click")

        def on_scroll(x, y, dx, dy):
            note_physical("mouse scroll")

        def on_press(key):
            try:
                if _is_takeover_combo():
                    note_physical("takeover hotkey")
            except Exception:                           # noqa: BLE001
                pass

        ml = ms.Listener(on_move=on_move, on_click=on_click, on_scroll=on_scroll)
        kl = kb.Listener(on_press=on_press)
        ml.daemon = True
        kl.daemon = True
        ml.start()
        kl.start()
        _watchers["mouse"], _watchers["keyboard"] = ml, kl
        return True
    except Exception:                                   # noqa: BLE001
        return False


def stop_watcher() -> None:
    global _started
    for k, lst in _watchers.items():
        try:
            if lst is not None:
                lst.stop()
        except Exception:                               # noqa: BLE001
            pass
        _watchers[k] = None
    _started = False


def _is_takeover_combo() -> bool:
    """Ctrl+Alt+Shift+Backspace（与 Windows-MCP 一致）。"""
    try:
        import ctypes

        VK = (0x11, 0x12, 0x10, 0x08)               # ctrl alt shift backspace
        return all(ctypes.windll.user32.GetAsyncKeyState(v) & 0x8000 for v in VK)
    except Exception:                                   # noqa: BLE001
        return False
