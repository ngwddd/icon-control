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
        self._lock = threading.Lock()
        self.triggered_at: float | None = None
        self.press_count = 0

    # ---------- 监听 ----------
    def start(self) -> None:
        if keyboard is None or self._listener is not None:
            return
        self._listener = keyboard.Listener(on_press=self._on_press)
        self._listener.daemon = True
        self._listener.start()
        if self.verbose:
            print("[panic] 急停开关已就绪：连按两下 ESC = 立即松手", flush=True)

    def _on_press(self, key) -> None:
        try:
            if key != keyboard.Key.esc:
                return
        except Exception:
            return
        now = time.time()
        with self._lock:
            self.press_count += 1
            self._press_times = [t for t in self._press_times if now - t <= self.window_s]
            self._press_times.append(now)
            if len(self._press_times) >= 2 and not self._event.is_set():
                self._event.set()
                self.triggered_at = now
                if self.verbose:
                    print("[panic] ✋ 收到「连按两下 ESC」—— 立即停止鼠标/键盘控制，等待指示", flush=True)

    # ---------- 查询 ----------
    @property
    def triggered(self) -> bool:
        return self._event.is_set()

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
            self.triggered_at = None
            self._event.clear()

    def stop(self) -> None:
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
