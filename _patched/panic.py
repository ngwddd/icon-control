"""panic.py — 全局急停开关（用户 2026-10-25 要求）

规则（用户原话）：
    「我连按两下 ESC，你就要取消对应鼠标的控制，然后等待我的发落。」

实现要点：
  · 用 pynput 的**全局键盘监听**（不抢焦点、不注入，只读按键），游戏全屏时也能收到。
  · 窗口期内按到第 2 次 ESC 就置位 `triggered`，此后**所有自动化循环必须立刻退出**。
  · 单次 ESC 不触发（游戏菜单常用 ESC，不能误杀）。
  · 一旦触发就**粘住**（不会自动复位）—— 必须由人或新进程显式 `reset()`，
    避免"响了一下又继续点鼠标"这种最坏情况。

用法（任何自动化脚本）：
    from computer_mcp import panic

    p = panic.PanicSwitch()          # 构造即开始监听
    while running:
        if p.triggered:              # 每一轮循环都必须检查
            break                    # 立刻停手，什么都不点
        ...
    p.stop()                         # 收尾时卸载监听
"""

from __future__ import annotations

import threading
import sys
import time

try:
    from pynput import keyboard
except Exception:                     # pragma: no cover - 没装 pynput 时退化
    keyboard = None


class PanicSwitch:
    """连按两次 ESC → triggered 置位（粘住），自动化必须立即停手。"""

    def __init__(self, window_s: float = 1.5, verbose: bool = True) -> None:
        self.window_s = float(window_s)
        self.verbose = verbose
        self._event = threading.Event()
        self._press_times: list[float] = []
        self._listener = None
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self.triggered_at: float | None = None
        self.triggered_at_wall = None
        self.durable_saved = False
        self.press_count = 0
        self._esc_down = False

    # ---------- 监听 ----------
    def start(self) -> None:
        if keyboard is None or self._listener is not None:
            return
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release,
                                          win32_event_filter=lambda msg, data: not (data.flags & 0x10))
        self._listener.daemon = True
        self._listener.start()
        listener = self._listener
        def await_ready():
            try:
                listener.wait()
                if listener.is_alive():
                    self._ready.set()
            except Exception:
                pass
        threading.Thread(target=await_ready, daemon=True, name='icon-panic-ready').start()
        if not self._ready.wait(2):
            self.stop()
            return
        self._log("[panic] 急停开关已就绪：连按两下 ESC = 立即松手")

    def _log(self,message):
        if self.verbose:
            try:print(message,flush=True,file=sys.stderr)
            except Exception:pass

    def _on_press(self, key) -> None:
        try:
            if key != keyboard.Key.esc:
                return
        except Exception:
            return
        if self._esc_down:
            return
        self._esc_down = True
        now = time.monotonic()
        with self._lock:
            self.press_count += 1
            self._press_times = [t for t in self._press_times if now - t <= self.window_s]
            self._press_times.append(now)
            if len(self._press_times) >= 2 and not self._event.is_set():
                self._event.set()
                self.triggered_at = now
                from computer_mcp import input_guard
                input_guard.release_all()  # Release before any disk or IPC operation.
                from computer_mcp import security
                try:
                    self.triggered_at_wall = security.latch_stop()
                    self.durable_saved = True
                except Exception:
                    self.triggered_at_wall = time.time()
                    self.durable_saved = False
                from computer_mcp import control
                control.release('emergency stop')
                from computer_mcp import input_guard
                input_guard.release_all()
                self._log("[panic] 收到「连按两下 ESC」—— 立即停止鼠标/键盘控制，等待指示")

    # ---------- 查询 ----------
    @property
    def triggered(self) -> bool:
        return self._event.is_set()

    @property
    def ready(self) -> bool:
        return bool(self._ready.is_set() and self._listener and self._listener.is_alive())

    def _on_release(self, key):
        if keyboard and key == keyboard.Key.esc:
            self._esc_down = False

    def check(self) -> bool:
        """便捷调用：返回是否已触发（等价于 .triggered）。"""
        return self._event.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        """阻塞等待触发（给"只等急停"的监控进程用）。"""
        return self._event.wait(timeout)

    def reset(self) -> None:
        """显式复位 —— 只有人确认之后才该调用。"""
        with self._lock:
            self._press_times.clear()
            self._esc_down = False
            self.triggered_at = None
            self.triggered_at_wall = None
            self.durable_saved = False
            self._event.clear()

    def stop(self) -> None:
        self._ready.clear()
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None


_DEFAULT: PanicSwitch | None = None


def default() -> PanicSwitch:
    """进程级单例：脚本里直接 `panic.default().triggered` 即可。"""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = PanicSwitch()
        _DEFAULT.start()
    return _DEFAULT
