"""capture_daemon.py — 常驻采集守护（v0.4 架构第一层）

为什么要有它：
    以前每次"看一眼"都是「mss 抓全屏 → 转 numpy → 传图/OCR」，一次 60~180 ms，
    而且模型每做一个动作就要重来一遍。豆包那种实时感来自**持续采集 + 端上算差异**，
    agent 只看"变了什么"，不看整张图。

设计要点：
    · 一个后台线程按 fps 连续抓屏，缩放到较小尺寸（默认 0.25）放进环形缓冲
    · 每帧和上一帧比：算平均差异 + 变化矩形（脏区），存哈希
    · 自适应帧率：画面静止时降到 idle fps（省 CPU），一有变化立刻回到 active
    · wait(predicate) 用帧循环实现"事件等待"，替代"sleep + 再截图"的轮询
    · 抓屏只在守护线程里做；工具层拿到的都是**内存快照**（<1 ms）

安全：
    · 只读屏幕，不注入、不改任何窗口
    · 黑名单窗口标题命中时**停止缓存帧**（避免把密码框之类留在内存里）
    · stop() 会把缓冲清空
"""

from __future__ import annotations

import ctypes
import hashlib
import threading
import time
from collections import deque
from dataclasses import dataclass

import numpy as np

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

DEFAULT_SCALE = 0.25          # 2560x1440 → 640x360
DEFAULT_ACTIVE_FPS = 12.0
DEFAULT_IDLE_FPS = 3.0
DEFAULT_MAX_FRAMES = 120      # 640x360x3 = 691KB → 120 帧约 83MB 上界；实际用 scale 0.25 时是 172KB/帧 ≈ 20MB
DIFF_THRESHOLD = 1.2          # 平均绝对差 > 这个值算"变了"

# 命中这些标题时不缓存（隐私护栏）
PRIVATE_TITLES = (
    "密码", "password", "登录", "login", "凭据", "credential",
    "1password", "bitwarden", "keepass", "authenticator",
)


@dataclass
class Frame:
    idx: int
    ts: float
    img: np.ndarray                 # HxWx3 uint8（已缩放）
    diff: float = 0.0               # 与上一帧的平均绝对差
    bbox: tuple | None = None       # 脏区 (x, y, w, h)，图像坐标
    changed_ratio: float = 0.0      # 脏区面积占全帧比例
    gray_hash: int = 0
    active_window: str = ""
    skipped: bool = False           # True = 命中隐私黑名单，本帧不保存像素

    def summary(self) -> dict:
        return {"idx": self.idx, "ts": round(self.ts, 3),
                "shape": list(self.img.shape[:2]) if not self.skipped else None,
                "diff": round(self.diff, 2), "bbox": self.bbox,
                "changed_ratio": round(self.changed_ratio, 4),
                "active_window": self.active_window, "skipped": self.skipped}


def _active_window_title() -> str:
    try:
        import win32gui
        h = win32gui.GetForegroundWindow()
        return win32gui.GetWindowText(h) or ""
    except Exception:
        return ""


def _is_private(title: str) -> bool:
    t = (title or "").lower()
    return any(k.lower() in t for k in PRIVATE_TITLES)


def _dirty(prev: np.ndarray, cur: np.ndarray, cell: int = 8) -> tuple[float, tuple | None, float]:
    """算平均差异 + 脏区（在 1/cell 分辨率上算，再放大回原坐标）。"""
    d = np.abs(cur.astype(np.int16) - prev.astype(np.int16)).mean(axis=2)
    mean_diff = float(d.mean())
    h, w = d.shape
    sh, sw = h // cell, w // cell
    if sh == 0 or sw == 0:
        return mean_diff, None, 0.0
    small = d[:sh * cell, :sw * cell].reshape(sh, cell, sw, cell).mean(axis=(1, 3))
    ys, xs = np.where(small > DIFF_THRESHOLD * 2)
    if len(xs) == 0:
        return mean_diff, None, 0.0
    x0, x1 = int(xs.min()) * cell, int((xs.max() + 1) * cell)
    y0, y1 = int(ys.min()) * cell, int((ys.max() + 1) * cell)
    ratio = ((x1 - x0) * (y1 - y0)) / float(h * w)
    return mean_diff, (x0, y0, x1 - x0, y1 - y0), ratio


class CaptureDaemon:
    """常驻采集。start() 后一直在后台跑，直到 stop()。"""

    _instance: "CaptureDaemon | None" = None
    _instance_lock = threading.Lock()

    @classmethod
    def shared(cls) -> "CaptureDaemon":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self, scale: float = DEFAULT_SCALE, active_fps: float = DEFAULT_ACTIVE_FPS,
                 idle_fps: float = DEFAULT_IDLE_FPS, max_frames: int = DEFAULT_MAX_FRAMES,
                 monitor: int = 1):
        self.scale = max(0.1, min(1.0, scale))
        self.active_fps = max(1.0, min(60.0, active_fps))
        self.idle_fps = max(0.5, min(self.active_fps, idle_fps))
        self.max_frames = max(10, min(600, max_frames))
        self.monitor = monitor
        self._frames: deque[Frame] = deque(maxlen=self.max_frames)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._idx = 0
        self._last_shape: tuple | None = None
        self.origin: tuple[int, int] = (0, 0)
        self.frames_captured = 0
        self.frames_skipped = 0
        self.last_error = ""

    # ---------- 生命周期 ----------
    def start(self) -> dict:
        if self._thread and self._thread.is_alive():
            return {"ok": True, "already": True, **self.status()}
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="capture-daemon", daemon=True)
        self._thread.start()
        time.sleep(0.35)                      # 等第一帧
        return {"ok": True, "already": False, **self.status()}

    def stop(self) -> dict:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        with self._lock:
            self._frames.clear()
        return {"ok": True, "stopped": True}

    def status(self) -> dict:
        with self._lock:
            n = len(self._frames)
            last = self._frames[-1] if n else None
            span = (last.ts - self._frames[0].ts) if n >= 2 else 0.0
        running = bool(self._thread and self._thread.is_alive())
        fps = (n - 1) / span if span > 0 else 0.0
        return {
            "running": running, "frames": n, "max_frames": self.max_frames,
            "scale": self.scale, "measured_fps": round(fps, 1),
            "active_fps": self.active_fps, "idle_fps": self.idle_fps,
            "captured": self.frames_captured, "skipped_private": self.frames_skipped,
            "last": last.summary() if last else None,
            "error": self.last_error,
        }

    # ---------- 读取 ----------
    def latest(self) -> Frame | None:
        with self._lock:
            return self._frames[-1] if self._frames else None

    def get(self, idx: int) -> Frame | None:
        with self._lock:
            for f in reversed(self._frames):
                if f.idx == idx:
                    return f
        return None

    def frames_between(self, since_idx: int) -> list[Frame]:
        with self._lock:
            return [f for f in self._frames if f.idx > since_idx]

    def wait(self, predicate, timeout_ms: int = 2000) -> tuple[bool, Frame | None]:
        """阻塞到 predicate(frame) 为真，或超时。返回 (hit, frame)。"""
        deadline = time.time() + max(50, timeout_ms) / 1000.0
        seen = None
        while time.time() < deadline:
            f = self.latest()
            if f is not None and f is not seen:
                seen = f
                try:
                    if predicate(f):
                        return True, f
                except Exception as exc:      # 判据写错不该把循环打死
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    return False, f
            time.sleep(0.012)
        return False, self.latest()

    # ---------- 线程 ----------
    def _loop(self) -> None:
        import mss
        prev: np.ndarray | None = None
        try:
            with mss.mss() as sct:
                mon = sct.monitors[self.monitor]
                self.origin = (int(mon.get('left', 0)), int(mon.get('top', 0)))
                while not self._stop.is_set():
                    t0 = time.time()
                    try:
                        shot = sct.grab(mon)
                        arr = np.asarray(shot, dtype=np.uint8)[:, :, :3]
                        if self.scale != 1.0:
                            step = max(1, int(round(1 / self.scale)))
                            arr = arr[::step, ::step]
                        self._last_shape = arr.shape[:2]
                        title = _active_window_title()
                        private = _is_private(title)
                        frame = Frame(idx=self._idx, ts=t0, img=arr,
                                      active_window=title, skipped=private)
                        if prev is not None and prev.shape == arr.shape and not private:
                            diff, bbox, ratio = _dirty(prev, arr)
                            frame.diff, frame.bbox, frame.changed_ratio = diff, bbox, ratio
                        frame.gray_hash = int(hashlib.blake2b(
                            np.ascontiguousarray(arr[::4, ::4]).tobytes(), digest_size=8).hexdigest(), 16)
                        with self._lock:
                            self._frames.append(frame)
                        self._idx += 1
                        self.frames_captured += 1
                        if private:
                            self.frames_skipped += 1
                        prev = arr
                    except Exception as exc:
                        self.last_error = f"{type(exc).__name__}: {exc}"
                        time.sleep(0.2)

                    # 自适应帧率：刚变过就快，静止就慢
                    changed = frame.diff > DIFF_THRESHOLD
                    target = self.active_fps if changed else self.idle_fps
                    dt = time.time() - t0
                    time.sleep(max(0.0, 1.0 / target - dt))
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
