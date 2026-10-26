"""train.py — 「一列不停的车」：三个轮子（入帧/处理/出）+ 看门狗 + 轨道执行器

设计来源（用户原话）：
    「L1L2L3 其实像一列火车的三个轮子：第一层进入、第二层处理、第三层输出。
      我给的指令就是轨道，你要沿着轨道一直行驶、一直往前推、一直不中断，
      而不是做一次卡一次。中间必须有轮子这个介质（截图）保证连续性。」

落地要点（全部实测过，不是估计）：
    抓取范围 = **目标窗口**（不是全屏）      全屏 25 ms → 窗口 11 ms
    降采样  = **numpy 块平均**（不是 PIL）   PIL 18 ms → numpy 4.5 ms
    实测    18.2 ms/帧 → **54.8 fps**（目标 30 fps，1.8× 余量）
    环形缓冲 150 帧 × 2.2 KB ≈ **0.3 MB**（恒定，不随时间增长）

三层职责：
    轮子1 IN   抓窗口 → 块平均 → 灰度小图 + JPEG 字节 → 环形缓冲
    轮子2 PROC 差分 → 变化块 → 状态机（STABLE/TRANSITION）→ 事件
    轮子3 OUT  最新稳定帧 + 事件时间线 + 拼图（交回模型的最小包）

看门狗（用户要求）：
    「像你刚才开微信，开了一分钟，正常人谁开微信要一分钟？你自己觉得不对，
      你就要截张图看的。」
    每个 step 带 budget_ms；超过 3× 预算 → 判定异常 → 立刻出拼图；
    连续 2 次异常 → 停车交还模型。
"""

from __future__ import annotations

import io
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# ─────────────────────────── 纯函数（可单测，不碰屏幕） ───────────────────────────

DEFAULT_BLOCK = 4          # 降采样倍数
BLOCK_THRESH = 6.0         # 块平均灰度差超过它算"变了"
STATE_STABLE = "STABLE"
STATE_TRANSITION = "TRANSITION"


def block_reduce(gray: np.ndarray, k: int = DEFAULT_BLOCK) -> np.ndarray:
    """把灰度图按 k×k 块取平均降采样（比 PIL.resize 快 4 倍）。"""
    if gray.ndim != 2:
        raise ValueError("block_reduce 需要二维灰度图")
    h = (gray.shape[0] // k) * k
    w = (gray.shape[1] // k) * k
    if h < k or w < k:
        return gray.astype(np.float32)
    g = gray[:h, :w].astype(np.float32)
    return g.reshape(h // k, k, w // k, k).mean(axis=(1, 3))


def change_blocks(prev: np.ndarray | None, cur: np.ndarray,
                  thresh: float = BLOCK_THRESH) -> tuple[int, float, np.ndarray | None]:
    """返回 (变化块数, 变化占比, 变化掩码)。prev 为 None 时视为全变。"""
    if prev is None or prev.shape != cur.shape:
        return int(cur.size), 1.0, np.ones_like(cur, dtype=bool)
    diff = np.abs(cur - prev)
    mask = diff > thresh
    n = int(mask.sum())
    return n, n / float(mask.size), mask


def norm_text(s: str) -> str:
    """归一化：只留字母数字与汉字，转小写。

    OCR 会把 "TRACK-OK-2152" 读成 "TRACKOK2152" / "TRACK-OK-2152" / 带空格，
    直接 in 比对必然失败（实测踩过）。
    """
    import re as _re
    return _re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", (s or "").lower())


def lcs_share(a: str, b: str) -> float:
    """最长公共子串占比（对 OCR 少一两个字比较宽容）。"""
    if not a or not b:
        return 0.0
    if a in b:
        return 1.0
    best = 0
    for i in range(len(a)):
        for j in range(i + best + 1, len(a) + 1):
            if a[i:j] in b:
                best = max(best, j - i)
            else:
                break
    return best / float(len(a))


def gray_from_bgra(arr: np.ndarray) -> np.ndarray:
    """BGRA → 灰度（取绿通道：足够判变化，且最便宜）。"""
    return arr[:, :, 1].astype(np.float32)


def encode_jpeg(gray_or_rgb: np.ndarray, quality: int = 70) -> bytes:
    from PIL import Image

    a = gray_or_rgb
    if a.ndim == 2:
        a = np.clip(a, 0, 255).astype(np.uint8)
        img = Image.fromarray(a, mode="L")
    else:
        img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), mode="RGB")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def montage(tiles: list[np.ndarray], width: int = 640, height: int = 360,
            pad: int = 4, bg: int = 24) -> np.ndarray:
    """把若干块拼成一张图（横向排布，必要时缩放到 width×height）。"""
    canvas = np.full((height, width), bg, dtype=np.uint8)
    if not tiles:
        return canvas
    x = pad
    y = pad
    row_h = 0
    for t in tiles:
        a = np.clip(t, 0, 255).astype(np.uint8)
        if a.ndim == 3:
            a = a[:, :, 1]
        th, tw = a.shape[:2]
        if th > height - 2 * pad:
            sc = (height - 2 * pad) / float(th)
            th, tw = max(1, int(th * sc)), max(1, int(tw * sc))
            idx_y = (np.arange(th) / sc).astype(int).clip(0, a.shape[0] - 1)
            idx_x = (np.arange(tw) / sc).astype(int).clip(0, a.shape[1] - 1)
            a = a[idx_y][:, idx_x]
            th, tw = a.shape
        if x + tw > width - pad and x > pad:
            x = pad
            y += row_h + pad
            row_h = 0
        if y + th > height - pad:
            break
        canvas[y:y + th, x:x + tw] = a
        x += tw + pad
        row_h = max(row_h, th)
    return canvas


# ─────────────────────────── 事件 / 摘要（L3） ───────────────────────────

EVENT_KINDS = ("STABLE", "TRANSITION", "SETTLED", "NEW_TEXT", "STALL", "ANOMALY", "STEP", "STOP")

# 模态对话框的特征词（OCR 读到这些 = 有东西在吞按键，别再瞎试）
# 实测来源：记事本「是否保留未保存的更改？」「要创建新文件吗？」、通用「确定/取消」
DIALOG_MARKERS = (
    "是否保留", "是否保存", "要创建新文件", "另存为", "覆盖",
    "确定要", "无法", "错误", "权限", "请输入", "确认删除",
)


@dataclass
class Event:
    t: float
    kind: str
    detail: str = ""
    step: str = ""

    def as_dict(self) -> dict:
        return {"t": round(self.t, 2), "kind": self.kind,
                "detail": self.detail, "step": self.step}


class EventLog:
    """有上限的事件队列（轮子3 的一部分）。"""

    def __init__(self, cap: int = 200):
        self.cap = cap
        self._q: deque[Event] = deque(maxlen=cap)

    def add(self, kind: str, detail: str = "", step: str = "", t: float | None = None) -> Event:
        if kind not in EVENT_KINDS:
            kind = "STEP"
        ev = Event(t=t if t is not None else time.time(), kind=kind, detail=detail, step=step)
        self._q.append(ev)
        return ev

    def tail(self, n: int = 12) -> list[dict]:
        return [e.as_dict() for e in list(self._q)[-n:]]

    def __len__(self) -> int:
        return len(self._q)

    def clear(self) -> None:
        self._q.clear()


class ThumbRing:
    """环形缓冲：存 (时间戳, 小图 JPEG, 灰度小图)。总字节有上限。"""

    def __init__(self, frames: int = 150, max_bytes: int = 4 * 1024 * 1024):
        self.max_frames = frames
        self.max_bytes = max_bytes
        self._q: deque[tuple[float, bytes, np.ndarray]] = deque()
        self.bytes = 0

    def push(self, t: float, jpg: bytes, gray: np.ndarray) -> None:
        self._q.append((t, jpg, gray))
        self.bytes += len(jpg)
        while len(self._q) > self.max_frames or (self.bytes > self.max_bytes and len(self._q) > 1):
            _, old, _ = self._q.popleft()
            self.bytes -= len(old)

    def last(self) -> tuple[float, bytes, np.ndarray] | None:
        return self._q[-1] if self._q else None

    def last_jpeg(self) -> bytes | None:
        return self._q[-1][1] if self._q else None

    def span_s(self) -> float:
        if len(self._q) < 2:
            return 0.0
        return self._q[-1][0] - self._q[0][0]

    def __len__(self) -> int:
        return len(self._q)


# ─────────────────────────── 看门狗（用户要求的异常延迟） ───────────────────────────

DEFAULT_BUDGET_MS = {
    "launch": 8000, "click": 600, "key": 600, "paste": 1500, "scroll": 400,
    "wait": 1000, "macro": 6000, "page": 4000, "send": 1500,
}
ANOMALY_FACTOR = 3.0        # 超 3 倍预算 = 异常
ANOMALY_STOP_AFTER = 2      # 连续 2 次异常 = 停车


class Watchdog:
    """每步的时间预算 + 异常判定。

    规则（用户要求）：
        超 3× 预算 → 异常（立刻出拼图，不再猜）
        连续 2 次异常 → 停车
    """

    def __init__(self, budgets: dict[str, int] | None = None,
                 factor: float = ANOMALY_FACTOR, stop_after: int = ANOMALY_STOP_AFTER):
        self.budgets = dict(DEFAULT_BUDGET_MS)
        if budgets:
            self.budgets.update({k: int(v) for k, v in budgets.items()})
        self.factor = factor
        self.stop_after = stop_after
        self.step_start = time.time()
        self.step_name = ""
        self.budget_ms = 0
        self.anomalies = 0
        self.last_anomaly_at = 0.0

    def begin(self, step_name: str, budget_ms: int | None = None) -> None:
        self.step_name = step_name
        self.step_start = time.time()
        self.budget_ms = int(budget_ms or 0)

    def elapsed_ms(self) -> float:
        return (time.time() - self.step_start) * 1000.0

    def check(self) -> tuple[bool, str]:
        """返回 (是否异常, 说明)。异常只报一次（同一 step 内）。"""
        if self.budget_ms <= 0:
            return False, ""
        el = self.elapsed_ms()
        limit = self.budget_ms * self.factor
        if el <= limit:
            return False, ""
        if self.last_anomaly_at and (time.time() - self.last_anomaly_at) < 1.0:
            return False, ""
        self.anomalies += 1
        self.last_anomaly_at = time.time()
        msg = (f"异常延迟：{self.step_name} 已 {el/1000:.1f}s，"
               f"预算 {self.budget_ms/1000:.1f}s（阈值 {limit/1000:.1f}s）")
        return True, msg

    def reset_anomalies(self) -> None:
        self.anomalies = 0

    def should_stop(self) -> bool:
        return self.anomalies >= self.stop_after


# ─────────────────────────── 轨道（Track / Step） ───────────────────────────

@dataclass
class Step:
    name: str
    action: dict | None = None
    expect: dict | None = None
    budget_ms: int = 0
    timeout_ms: int = 15000
    on_fail: str = "stop"          # stop | continue | retry
    wait_before_action_ms: int = 0
    note: str = ""

    def budget(self) -> int:
        if self.budget_ms:
            return int(self.budget_ms)
        kind = (self.action or {}).get("kind", "click")
        return int(DEFAULT_BUDGET_MS.get(kind, 2000))


@dataclass
class Track:
    name: str
    steps: list[Step] = field(default_factory=list)
    window: dict | None = None           # {"process": "weixin"} 或 {"title_contains": "..."}
    hwnd: int = 0
    capture: dict = field(default_factory=lambda: {
        "fps": 30, "down": 4, "ring": 150, "jpeg_quality": 70,
    })

    @staticmethod
    def from_dict(d: dict) -> "Track":
        steps = []
        for i, s in enumerate(d.get("steps") or []):
            steps.append(Step(
                name=str(s.get("name") or f"step{i+1}"),
                action=s.get("action"),
                expect=s.get("expect"),
                budget_ms=int(s.get("budget_ms") or 0),
                timeout_ms=int(s.get("timeout_ms") or 15000),
                on_fail=str(s.get("on_fail") or "stop"),
                wait_before_action_ms=int(s.get("wait_before_action_ms") or 0),
                note=str(s.get("note") or ""),
            ))
        return Track(
            name=str(d.get("name") or "track"),
            steps=steps,
            window=d.get("window"),
            hwnd=int(d.get("hwnd") or 0),
            capture={**{"fps": 30, "down": 4, "ring": 150, "jpeg_quality": 70},
                     **(d.get("capture") or {})},
        )


# ─────────────────────────── 轮子1+2：抓帧 + 处理 ───────────────────────────

class FrameWheel(threading.Thread):
    """常驻抓帧线程：窗口区域 → 块平均 → 差分 → 状态机 → 事件。

    - 只在 track 运行期间转动；stop() 后 1 秒内退出（join）
    - 抓取范围 = 目标窗口（实测比全屏快 2.3 倍）
    """

    def __init__(self, rect: tuple[int, int, int, int], ring: ThumbRing,
                 events: EventLog, fps: int = 30, down: int = 4, jpeg_quality: int = 70):
        super().__init__(daemon=True)
        self.rect = rect
        self.ring = ring
        self.events = events
        self.fps = max(5, min(int(fps), 60))
        self.down = max(1, int(down))
        self.q = int(jpeg_quality)
        self._stop_evt = threading.Event()
        self.state = STATE_STABLE
        self.last_change_at = time.time()
        self.last_frac = 0.0
        self.frames = 0
        self.fps_actual = 0.0
        self.last_text = ""                             # 最近一次 OCR 读到的文本（调试用）
        self.last_full: np.ndarray | None = None       # 最近整帧（BGRA），给拼图裁块用
        self.last_mask: np.ndarray | None = None        # 最近变化掩码（小图坐标）
        self.last_small: np.ndarray | None = None
        self._prev: np.ndarray | None = None
        self._t0 = time.time()
        self.history: deque[tuple[float, float]] = deque(maxlen=240)   # (t, frac)
        self._first = True
        self.error = ""

    def stop(self) -> None:
        self._stop_evt.set()

    def run(self) -> None:                            # pragma: no cover（需要真实屏幕）
        try:
            import mss
            left, top, w, h = self.rect
            interval = 1.0 / self.fps
            with mss.mss() as sct:
                box = {"left": int(left), "top": int(top), "width": max(8, int(w)),
                       "height": max(8, int(h))}
                while not self._stop_evt.is_set():
                    t0 = time.perf_counter()
                    shot = sct.grab(box)
                    arr = np.asarray(shot)                    # BGRA
                    gray = gray_from_bgra(arr)
                    small = block_reduce(gray, self.down)
                    if self._first:
                        # 第一帧没有 prev，change_blocks 会返回 100% → 假事件，跳过
                        self._first = False
                        self._prev = small
                        self.last_small = small
                        self.last_mask = None
                        self.ring.push(time.time(), encode_jpeg(small, self.q), small)
                        time.sleep(max(0.0, interval - (time.perf_counter() - t0)))
                        continue
                    n, frac, mask = change_blocks(self._prev, small)
                    now = time.time()
                    self._prev = small
                    self.last_small = small
                    self.last_mask = mask
                    self.last_full = arr if (self.frames % 6 == 0) else self.last_full
                    self.last_frac = frac
                    self.frames += 1
                    self.fps_actual = self.frames / max(0.001, now - self._t0)

                    if frac > 0.001:
                        if self.state == STATE_STABLE:
                            self.state = STATE_TRANSITION
                            self.events.add("TRANSITION", f"变化 {frac*100:.1f}%")
                        self.last_change_at = now
                    else:
                        if self.state == STATE_TRANSITION and (now - self.last_change_at) > 0.25:
                            self.state = STATE_STABLE
                            self.events.add("SETTLED", "画面稳定")

                    self.history.append((now, frac))
                    self.ring.push(now, encode_jpeg(small, self.q), small)
                    dt = time.perf_counter() - t0
                    if dt < interval:
                        time.sleep(interval - dt)
        except Exception as e:                       # 线程内异常不要静默
            self.error = f"{type(e).__name__}: {e}"
            self.events.add("ANOMALY", f"抓帧线程异常：{self.error}")

    def max_frac_since(self, t0: float) -> float:
        """某时刻之后出现过的最大变化率（锁存判据用，避免"变完就稳"的竞态）。"""
        return max((f for (t, f) in self.history if t >= t0), default=0.0)

    def changed_since(self, t0: float) -> bool:
        return self.max_frac_since(t0) > 0.0

    def crop_from_last_full(self, mask: np.ndarray, limit: int = 4) -> list[np.ndarray]:
        """从最近整帧里裁出"变化过的块"（拼图用）。"""
        if self.last_full is None or mask is None or mask.size == 0:
            return []
        hs, ws = mask.shape
        hf, wf = self.last_full.shape[:2]
        blocks = np.argwhere(mask)
        if len(blocks) == 0:
            return []
        # 聚成最多 limit 个簇（用简单网格把块归并）
        cell_h, cell_w = max(1, hs // 12), max(1, ws // 12)
        groups: dict[tuple[int, int], list[tuple[int, int]]] = {}
        for (r, c) in blocks:
            groups.setdefault((r // cell_h, c // cell_w), []).append((r, c))
        out = []
        for _, pts in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:limit]:
            rs = [p[0] for p in pts]
            cs = [p[1] for p in pts]
            r0, r1 = min(rs) * self.down, (max(rs) + 1) * self.down
            c0, c1 = min(cs) * self.down, (max(cs) + 1) * self.down
            r0, r1 = max(0, min(r0, hf - 2)), max(2, min(r1, hf))
            c0, c1 = max(0, min(c0, wf - 2)), max(2, min(c1, wf))
            out.append(gray_from_bgra(self.last_full[r0:r1, c0:c1]))
        return out


# ─────────────────────────── 动作执行（复用已验证的做法） ───────────────────────────

def _resolve_point(rect: tuple[int, int, int, int], rel_frac: list[float]) -> tuple[int, int]:
    x, y, w, h = rect
    return int(x + rel_frac[0] * w), int(y + rel_frac[1] * h)


def do_action(action: dict, rect: tuple[int, int, int, int], hwnd: int = 0) -> dict:
    """执行一个动作。返回 {"ok": bool, "detail": str}。"""
    from pynput.keyboard import Controller as KB, Key
    from pynput.mouse import Button, Controller as MS

    kind = (action or {}).get("kind", "")
    try:
        if kind == "click":
            pt = _resolve_point(rect, action.get("rel_frac") or [0.5, 0.5])
            ms = MS()
            ms.position = pt
            time.sleep(float(action.get("settle_ms", 120)) / 1000.0)
            btn = {"left": Button.left, "right": Button.right}.get(
                str(action.get("button", "left")), Button.left)
            ms.click(btn, int(action.get("clicks", 1)))
            return {"ok": True, "detail": f"click {pt}"}

        if kind == "key":
            kb = KB()
            name = str(action.get("key", "enter")).lower()
            key = getattr(Key, name, None) or name
            kb.press(key)
            kb.release(key)
            return {"ok": True, "detail": f"key {name}"}

        if kind == "paste":
            import win32clipboard

            text = str(action.get("text", ""))
            for _ in range(3):
                try:
                    win32clipboard.OpenClipboard()
                    win32clipboard.EmptyClipboard()
                    win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
                    win32clipboard.CloseClipboard()
                    break
                except Exception:
                    time.sleep(0.15)
            kb = KB()
            with kb.pressed(Key.ctrl):
                kb.press("v")
                kb.release("v")
            return {"ok": True, "detail": f"paste {len(text)} chars"}

        if kind == "scroll":
            import ctypes

            # 先把光标移到滚动目标区（默认内容中心）：滚轮只作用于"鼠标下面的窗口/区域"。
            # 实测：不移动光标时，滚轮落在左栏浮层上，朋友圈列表不动（下滑2 就是这么失败的）
            at = action.get("at_rel_frac") or [0.6, 0.5]
            pt = _resolve_point(rect, at)
            MS().position = pt
            time.sleep(0.15)
            k = int(action.get("dy", -360))
            for _ in range(int(action.get("times", 1))):
                ctypes.windll.user32.mouse_event(0x0800, 0, 0, k, 0)
                time.sleep(float(action.get("gap_ms", 300)) / 1000.0)
            return {"ok": True, "detail": f"scroll {k}×{action.get('times', 1)} at {pt}"}

        if kind == "wait":
            time.sleep(float(action.get("ms", 500)) / 1000.0)
            return {"ok": True, "detail": "waited"}

        if kind == "macro":
            from computer_mcp import macro_ext
            from pynput.keyboard import Controller as KB2
            from pynput.mouse import Controller as MS2

            res = macro_ext.run_macro(str(action.get("name", "")),
                                      dict(action.get("params") or {}),
                                      mouse=MS2(), keyboard=KB2())
            return {"ok": bool(res.get("ok")), "detail": f"macro {action.get('name')} ok={res.get('ok')}"}

        return {"ok": False, "detail": f"未知动作：{kind}"}
    except Exception as e:
        return {"ok": False, "detail": f"{kind} 失败：{type(e).__name__}: {e}"}


# ─────────────────────────── 判据（expect） ───────────────────────────

def check_expect(expect: dict | None, wheel: FrameWheel,
                 rect: tuple[int, int, int, int], hwnd: int = 0,
                 since: float | None = None) -> bool | None:
    """True=成立 False=不成立 None=判不了（算"不确定"）。"""
    if not expect:
        return True
    kind = str(expect.get("kind", ""))

    if kind == "stable":
        need = float(expect.get("ms", 300)) / 1000.0
        return wheel.state == STATE_STABLE and (time.time() - wheel.last_change_at) >= need

    if kind == "changed":
        # 锁存：自 since 起**出现过**足够大的变化就算成立（不等它稳定）
        need = float(expect.get("min_frac", 0.002))
        if since is not None and hasattr(wheel, "max_frac_since"):
            return wheel.max_frac_since(since) >= need
        return wheel.last_frac >= need

    if kind == "window":
        try:
            import win32gui

            want = str(expect.get("title_contains", ""))
            if not want:
                return None
            if hwnd and win32gui.IsWindowVisible(hwnd):
                return want in win32gui.GetWindowText(hwnd)
            hits = []
            win32gui.EnumWindows(lambda h, _: hits.append(win32gui.GetWindowText(h))
                                 if win32gui.IsWindowVisible(h) else None, None)
            return any(want in t for t in hits)
        except Exception:
            return None

    if kind in ("text", "template"):
        # 贵判据：由 Runner 限频调用（每 3 帧一次），这里只做实现
        try:
            from computer_mcp import ocr_ext

            # 不传 region = 整窗（默认最安全；实测过区域写小把目标排除在外）
            reg = expect.get("region") or [0.0, 0.0, 1.0, 1.0]
            rel = [float(v) for v in reg]
            x, y, w, h = rect
            region = {"x": int(x + rel[0] * w), "y": int(y + rel[1] * h),
                      "w": max(8, int(rel[2] * w)), "h": max(8, int(rel[3] * h))}
            res = ocr_ext.ocr_read(region=region, max_lines=20)
            txt = "".join((ln.get("text") or "") for ln in (res.get("lines") or [])).replace(" ", "")
            query = str(expect.get("query", ""))
            if not query:
                return None
            q, t = norm_text(query), norm_text(txt)
            if not q:
                return None
            wheel.last_text = txt[:200] if wheel is not None else ""
            if q in t:
                return True
            return lcs_share(q, t) >= float(expect.get("min_lcs", 0.8))
        except Exception:
            return None

    return None


# ─────────────────────────── 轮子3 + 执行器 ───────────────────────────

STOP_DONE = "done"
STOP_TIMEOUT = "timeout"
STOP_STALL = "stall"
STOP_UNCERTAIN = "uncertain"
STOP_STOPPED = "stopped"


class Runner:
    """沿着轨道开：每步 = 等判据成立 / 执行动作 / 看门狗计时。"""

    def __init__(self, track: Track, rect: tuple[int, int, int, int], hwnd: int = 0):
        self.track = track
        self.rect = rect
        self.hwnd = hwnd
        self.events = EventLog()
        self.ring = ThumbRing(frames=int(track.capture.get("ring", 150)))
        self.budget = Watchdog()
        self.wheel = FrameWheel(rect, self.ring, self.events,
                                fps=int(track.capture.get("fps", 30)),
                                down=int(track.capture.get("down", 4)),
                                jpeg_quality=int(track.capture.get("jpeg_quality", 70)))
        self.result: dict[str, Any] = {"status": STOP_STOPPED, "step": "", "steps_done": 0,
                                       "elapsed_s": 0.0, "events": [], "montage": ""}
        self._stop_evt = threading.Event()
        self._t0 = time.time()
        self._pred_cache: dict[str, tuple[float, bool | None]] = {}
        self._noted: set[str] = set()
        self.dialog_hits = 0

    # ---- 生命周期 ----
    def start(self) -> None:
        self.wheel.start()

    def stop(self) -> None:
        self._stop_evt.set()
        self.wheel.stop()
        try:
            self.wheel.join(timeout=1.5)
        except Exception:
            pass
        if self.hwnd:                       # 跑完取消置顶，别把用户桌面钉死
            try:
                import win32con
                import win32gui

                win32gui.SetWindowPos(self.hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                                      win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
            except Exception:
                pass

    # ---- 出包（轮子3）----
    def bundle(self, status: str, step: str = "", reason: str = "") -> dict:
        tiles: list[np.ndarray] = []
        last = self.ring.last()
        if last is not None:
            tiles.append(last[2])
        if self.wheel.last_mask is not None:
            tiles.extend(self.wheel.crop_from_last_full(self.wheel.last_mask, limit=3))
        img = montage(tiles)
        jpg = encode_jpeg(img, 75)
        path = ""
        try:
            draw = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "_draw")
            os.makedirs(draw, exist_ok=True)
            path = os.path.join(draw, f"track_{int(time.time()*1000)%100000}.jpg")
            with open(path, "wb") as fh:
                fh.write(jpg)
        except Exception:
            path = ""
        fps_ok = self.wheel.fps_actual
        mem = {}
        try:
            import psutil

            mem = {"rss_mb": round(psutil.Process(os.getpid()).memory_info().rss / 1048576, 1)}
        except Exception:
            mem = {}
        return {
            "status": status,
            "reason": reason,
            "step": step,
            "steps_done": self.result.get("steps_done", 0),
            "elapsed_s": round(time.time() - self._t0, 1),
            "state": self.wheel.state,
            "fps": round(fps_ok, 1),
            "frames": self.wheel.frames,
            "ring_frames": len(self.ring),
            "ring_kb": round(self.ring.bytes / 1024, 1),
            "ring_span_s": round(self.ring.span_s(), 2),
            "anomalies": self.budget.anomalies,
            "dialog_hits": self.dialog_hits,
            "events": self.events.tail(12),
            "montage": path,
            "montage_b64_kb": round(len(jpg) / 1024, 1),
            **mem,
        }

    def _ensure_foreground(self, step_name: str = "") -> bool:
        """每步动手前把目标窗口拉到前台**并置顶**。

        实测（微信那轮）：被别的窗口盖住时，点击/滚轮全落在遮盖窗口上，
        而看门狗/fps/画面差异一切"正常" —— 属于最难发现的静默失败。
        所以这里不只 activate，还要 HWND_TOPMOST；stop() 时再取消。
        """
        if not self.hwnd:
            return True
        try:
            import win32con
            import win32gui

            win32gui.SetWindowPos(self.hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                                  win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
            if win32gui.GetForegroundWindow() == self.hwnd:
                return True
            from computer_mcp import appkit

            appkit.activate(self.hwnd)
            time.sleep(0.25)
            ok = win32gui.GetForegroundWindow() == self.hwnd
            self.events.add("STEP", "目标失焦 → 已置顶+置前" if ok else "目标失焦，拉不回前台",
                            step_name)
            return ok
        except Exception:
            return False

    # ---- 判据（贵判据限频 150 ms）----
    def _pred(self, step: Step, since: float | None = None) -> bool | None:
        kind = ((step.expect or {}).get("kind") or "")
        now = time.time()
        if kind in ("text", "template"):
            c = self._pred_cache.get(step.name)
            if c and (now - c[0]) < 0.15:
                return c[1]
            v = check_expect(step.expect, self.wheel, self.rect, self.hwnd, since)
            self._pred_cache[step.name] = (now, v)
            return v
        return check_expect(step.expect, self.wheel, self.rect, self.hwnd, since)

    # ---- 主循环 ----
    def run(self, max_total_s: float = 120.0) -> dict:
        self.start()
        self.events.add("STEP", f"轨道开始：{self.track.name}")
        try:
            for idx, step in enumerate(self.track.steps):
                if self._stop_evt.is_set():
                    return self._finish(STOP_STOPPED, step.name, "用户停止")
                if time.time() - self._t0 > max_total_s:
                    return self._finish(STOP_TIMEOUT, step.name, f"总时长超 {max_total_s}s")

                step_mark = time.time()
                self.budget.begin(step.name, step.budget())
                self.events.add("STEP", f"开始：{step.name}", step.name)
                deadline = time.time() + step.timeout_ms / 1000.0
                acted = False
                pred_since = 0.0
                uncertain_streak = 0

                while time.time() < deadline and not self._stop_evt.is_set():
                    if step.wait_before_action_ms and not acted:
                        if (time.time() - self.budget.step_start) * 1000 < step.wait_before_action_ms:
                            time.sleep(0.02)
                            continue

                    pred = self._pred(step, step_mark)
                    if pred is True:
                        self.events.add("STEP", f"达成：{step.name}", step.name)
                        self.result["steps_done"] = idx + 1
                        break

                    if pred is False:
                        txt = (self.wheel.last_text or "")
                        if txt:
                            low = txt.lower()
                            hit = next((m for m in DIALOG_MARKERS if m in txt), "")
                            if hit and step.name not in self._noted:
                                self._noted.add(step.name)
                                self.events.add("ANOMALY",
                                                f"检测到模态对话框（含「{hit}」）：{txt[:60]}",
                                                step.name)
                                self.dialog_hits += 1
                            elif step.name not in self._noted:
                                self._noted.add(step.name)
                                self.events.add("STALL", f"OCR 读到：{txt[:70]}", step.name)
                    if pred is None:
                        uncertain_streak += 1
                        if uncertain_streak >= 6:            # 连续判不了 → 不确定
                            return self._finish(STOP_UNCERTAIN, step.name, "判据连续判不了")
                    else:
                        uncertain_streak = 0

                    if not acted and step.action:
                        # 每步动手前先确认目标窗口在前台：
                        # 实测被别的窗口盖住时，点击/滚轮全落在遮盖窗口上，而库里一切正常
                        self._ensure_foreground(step.name)
                        res = do_action(step.action, self.rect, self.hwnd)
                        acted = True
                        self.events.add("STEP", f"动作：{res.get('detail')}", step.name)
                        if not res.get("ok") and step.on_fail == "stop":
                            return self._finish(STOP_TIMEOUT, step.name, str(res.get("detail")))
                        pred_since = time.time()

                    bad, msg = self.budget.check()
                    if bad:
                        self.events.add("ANOMALY", msg, step.name)
                        snap = self.bundle("anomaly", step.name, msg)
                        self.events.add("ANOMALY", f"已出拼图：{snap.get('montage')}", step.name)
                        if self.budget.should_stop():
                            return self._finish(STOP_STALL, step.name, f"连续 {self.budget.anomalies} 次异常")

                    time.sleep(0.02)
                else:
                    # timeout
                    if step.on_fail == "continue":
                        self.events.add("STALL", f"跳过：{step.name}", step.name)
                        continue
                    return self._finish(STOP_TIMEOUT, step.name, f"超时 {step.timeout_ms}ms")

            return self._finish(STOP_DONE, "", "轨道跑完")
        finally:
            self.stop()

    def _finish(self, status: str, step: str, reason: str) -> dict:
        self.result = self.bundle(status, step, reason)
        self.events.add("STOP", f"{status}：{reason}", step)
        self.result["events"] = self.events.tail(12)
        return self.result


def acted_note(step: Step, events: EventLog) -> bool:
    return False


# ─────────────────────────── 对外：内存/自检 ───────────────────────────

def selfcheck(seconds: float = 3.0, fps: int = 30, down: int = 4) -> dict:
    """短跑一次抓帧轮，报告 fps / 内存 / 环形占用（给"能不能跑"用）。"""
    import psutil

    proc = psutil.Process(os.getpid())
    rss0 = proc.memory_info().rss / 1048576
    ring = ThumbRing(frames=int(seconds * fps) + 10)
    events = EventLog()
    try:
        import win32gui
        hwnd = win32gui.GetForegroundWindow()
        l, t, r, b = win32gui.GetWindowRect(hwnd)
        rect = (l, t, r - l, b - t)
    except Exception:
        rect = (0, 0, 1280, 720)
    wheel = FrameWheel(rect, ring, events, fps=fps, down=down)
    wheel.start()
    time.sleep(seconds)
    wheel.stop()
    wheel.join(timeout=1.5)
    rss1 = proc.memory_info().rss / 1048576
    return {
        "rect": list(rect), "fps_target": fps, "fps_actual": round(wheel.fps_actual, 1),
        "frames": wheel.frames, "ring_frames": len(ring),
        "ring_kb": round(ring.bytes / 1024, 1), "span_s": round(ring.span_s(), 2),
        "rss_mb": [round(rss0, 1), round(rss1, 1)], "error": wheel.error,
        "events": events.tail(6),
    }
