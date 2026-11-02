"""Desktop ownership with physical takeover, fail-closed listener readiness and generations.
Injected events are filtered by Windows injection flags. quiet() remains a legacy
API; it never suppresses a real user event. claim() cannot override active takeover.
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
_generation = 0


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
    global _generation
    with _lock:
        _generation += 1
        STATE["last_user"] = _now()
        if STATE['owner'] != 'user':
            STATE["takeovers"] += 1
            STATE["owner"] = "user"
            STATE["since"] = _now()
            STATE["reason"] = reason
    from computer_mcp.input_guard import release_all
    release_all()


def claim(reason: str = "agent") -> dict:
    from computer_mcp import permission, panic
    if not permission.status().get('granted'):
        return dict(status(), ok=False, error='User authorization required')
    if panic.default().triggered or not panic.default().ready:
        return dict(status(), ok=False, error='Emergency listener unavailable or stopped')
    if not ensure_watcher():
        return dict(status(), ok=False, error='Takeover listeners did not start')
    if status()['owner'] == 'user':
        return dict(status(), ok=False, error='User owns control; claim cannot override takeover')
    with _lock:
        if status()['owner'] == 'user':
            return dict(status(), ok=False, error='User took over while claim was starting')
        STATE["owner"] = "ai"
        STATE["since"] = _now()
        STATE["reason"] = reason
    return status()


def release(reason: str = "agent released") -> dict:
    global _generation
    with _lock:
        _generation += 1
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
        with _lock:
            if now - max(STATE['since'],STATE['last_user']) >= IDLE_RESUME_S:
                _set('idle',f'用户闲置 {int(idle_s)}s，控制权已释放')
            owner = STATE['owner']
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
        'watcher': bool(_watchers['mouse'] and _watchers['keyboard'] and
                        all(w.is_alive() for w in _watchers.values())),
        'generation': _generation,
    }


def blocking_reason() -> str | None:
    """给闸门用：非 None 表示当前不该注入输入。"""
    if not ENABLED or not ensure_watcher():
        return 'Takeover monitoring unavailable; execution is blocked'
    st = status()
    if st["owner"] == "user":
        return (f"用户已接管控制权（{st['idle_s']}s 前），"
                f"再闲置 {max(0, round(st['idle_resume_s'] - st['idle_s']))}s 才恢复")
    return None


# ── 全局监听：只在第一次 claim 时启动 ────────────────────────────────
def ensure_watcher() -> bool:
    with _lock:
        return _ensure_watcher_locked()

def _ensure_watcher_locked() -> bool:
    """启动 pynput 全局监听（幂等）。拿不到权限就静默失败。"""
    global _started
    if not ENABLED:
        return False
    if _started:
        return all(w is not None and w.is_alive() for w in _watchers.values())
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
            note_physical('keyboard input')

        # Windows distinguishes injected from physical input. A time window
        # would also suppress a real user's hand while the agent is moving.
        def mouse_filter(msg, data):
            return not (data.flags & 0x01)

        def keyboard_filter(msg, data):
            return not (data.flags & 0x10)

        ml = ms.Listener(on_move=on_move, on_click=on_click, on_scroll=on_scroll,
                         win32_event_filter=mouse_filter)
        kl = kb.Listener(on_press=on_press, win32_event_filter=keyboard_filter)
        ml.daemon = True
        kl.daemon = True
        _watchers["mouse"], _watchers["keyboard"] = ml, kl
        for listener in (ml, kl):
            listener.start()
            ready = threading.Event()
            def wait_ready(current=listener, event=ready):
                current.wait()
                event.set()
            threading.Thread(target=wait_ready, daemon=True).start()
            if not ready.wait(2) or not listener.is_alive():
                raise RuntimeError('Listener readiness timeout')
        _started = True
        return True
    except Exception:                                   # noqa: BLE001
        stop_watcher()
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
