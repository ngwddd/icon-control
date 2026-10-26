"""navigator.py — 快慢双层导航（M1 世界状态 / M2 伺服 / M3 监督器）

问题（用户 2026-10-27 原话）：
    「你就做不到像那个实时屏幕共享的实时读取了。就是提高你的思考回馈路径。」

根因不是工具慢，是**模型在内环**：
    模型      0.2–0.5 次/秒决策（每次 2–5 s）
    人类/豆包  20–60 次/秒视觉伺服
这是 100 倍差距，把 sense() 从 10 ms 压到 1 ms 也救不了 —— 瓶颈是 token 生成。

解法：把闭环拆成快慢两层，模型只做外环。
    慢环（模型，0.1–0.5 Hz）：目标、策略、异常
    快环（本地代码，20–30 Hz）：world_state 感知 + servo 伺服 + supervisor 看门

三层各自的职责：
    M1 WorldState  画面 → 结构化文本（小地图网格 / HUD / 提示 / 电量）
    M2 Servo       目标格 → 动作（每帧算方位误差、持续修正，而不是"走一步看看变没变"）
    M3 Supervisor  跑计划，只在 4 种情况回调模型（达成 / 卡住 / 不确定 / 见到新东西）

设计约束（都是踩过的坑）：
    · 小地图是**规则网格**（实测列间距 10.5 px），用列投影自动求 pitch，不硬编码
    · 缩放帧会把 1px 字体笔画洗掉 → 状态抽取一律用**全分辨率**抓取
    · 朝向不靠"读罗盘"，靠**走一小步看地图上的位移方向**（自校准，无需游戏配合）
    · 快环只做移动/朝向/交互；战斗与危险判断升温给慢环
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from computer_mcp import perceive

# ── 格子分类（RGB 阈值，可按游戏换） ─────────────────────────────────
UNKNOWN, FLOOR, PLAYER, MARKER = " ", ".", "P", "X"


@dataclass
class MapConfig:
    """小地图的标定参数。region 是屏幕坐标；pitch=None 表示自动求。"""
    region: tuple | None = None
    pitch: float | None = None
    dark_max: int = 45            # 低于这个亮度 = 未探索/虚空
    floor_lo: int = 60            # 已探索地面的亮度区间
    floor_hi: int = 165
    green: tuple = ((0, 200, 120), 90)     # 玩家标记（颜色 + 容差）
    marker: tuple = ((232, 192, 64), 90)   # 目标标记（金/黄）


@dataclass
class WorldSnapshot:
    ts: float
    grid: list[str] = field(default_factory=list)
    pitch: float = 0.0
    origin: tuple = (0, 0)
    player: tuple | None = None          # (col, row) 地图格坐标
    markers: list = field(default_factory=list)
    prompt: bool = False
    battery: float | None = None
    hud: dict = field(default_factory=dict)
    error: str = ""

    def as_dict(self) -> dict:
        return {"ts": round(self.ts, 3),
                "grid": self.grid, "grid_size": [len(self.grid), len(self.grid[0]) if self.grid else 0],
                "player": self.player, "markers": self.markers,
                "prompt": self.prompt, "battery": self.battery,
                "hud": self.hud, "pitch": round(self.pitch, 2),
                "origin": list(self.origin), "error": self.error}

    def text(self) -> str:
        """给模型看的一页文本（几十 token，而不是一张图）。"""
        head = [f"player={self.player} markers={self.markers} "
                f"prompt={'Y' if self.prompt else 'N'}",
                f"battery={self.battery} hud={self.hud}"]
        rows = [f"{i:2}|{line}" for i, line in enumerate(self.grid)]
        return "\n".join(head + rows)


# ══════════════════════════ M1：世界状态 ══════════════════════════
class WorldState:
    """把画面压成结构化状态。调用方给屏幕坐标，内部一律全分辨率抓取。"""

    def __init__(self, grab, map_cfg: MapConfig | None = None,
                 prompt_box: tuple | None = None,
                 battery_box: tuple | None = None):
        self._grab = grab                      # grab(region) -> np.ndarray | None
        self.map_cfg = map_cfg or MapConfig()
        self.prompt_box = prompt_box
        self.battery_box = battery_box
        self._last: WorldSnapshot | None = None
        self._pitch_cache: float | None = None
        self._origin_cache: tuple | None = None

    # ---------- 小地图 ----------
    def _calibrate(self, mask: np.ndarray) -> tuple[float, tuple]:
        """用列/行投影自动求格子间距与原点（只做一次，之后缓存）。"""
        cols = np.where(mask.sum(axis=0) > 2)[0]
        rows = np.where(mask.sum(axis=1) > 2)[0]
        if len(cols) < 4 or len(rows) < 4:
            return 11.0, (int(cols.min()) if len(cols) else 0,
                          int(rows.min()) if len(rows) else 0)

        def centers(idx):
            out, s, p = [], idx[0], idx[0]
            for v in idx[1:]:
                if v - p > 1:
                    out.append((s + p) / 2.0)
                    s = v
                p = v
            out.append((s + p) / 2.0)
            return out

        cs = centers(cols)
        pitch = float(np.median(np.diff(cs))) if len(cs) > 1 else 11.0
        # 起点：让格子边界对齐第一个列段的左沿
        x0 = float(cols.min())
        y0 = float(rows.min())
        return max(4.0, pitch), (int(x0), int(y0))

    def _classify(self, patch: np.ndarray) -> str:
        avg = patch.reshape(-1, 3).astype(np.float32)
        # 取最亮的 3 个像素代表这一格（避开抗锯齿边缘）
        idx = np.argsort(avg.mean(axis=1))[-3:]
        r, g, b = avg[idx].mean(axis=0)
        lum = float((r + g + b) / 3.0)
        if g > 150 and r < 120 and b < 140:
            return PLAYER
        m_rgb, m_tol = self.map_cfg.marker
        if abs(r - m_rgb[0]) < m_tol and abs(g - m_rgb[1]) < m_tol and abs(b - m_rgb[2]) < m_tol:
            return MARKER
        if lum < self.map_cfg.dark_max:
            return UNKNOWN
        if self.map_cfg.floor_lo <= lum <= self.map_cfg.floor_hi:
            return FLOOR
        return "?" if lum > self.map_cfg.floor_hi else UNKNOWN

    def minimap(self) -> tuple[list[str], tuple | None, list, float, tuple]:
        region = self.map_cfg.region
        if not region:
            return [], None, [], 0.0, (0, 0)
        img = self._grab(region)
        if img is None or img.size == 0:
            return [], None, [], 0.0, (0, 0)
        lum = img.astype(np.float32).mean(axis=2)
        mask = lum > self.map_cfg.dark_max

        if self._pitch_cache is None or self.map_cfg.pitch is None:
            pitch, origin = self._calibrate(mask)
            if self.map_cfg.pitch:
                pitch = float(self.map_cfg.pitch)
            self._pitch_cache, self._origin_cache = pitch, origin
        pitch, origin = self._pitch_cache, self._origin_cache

        x0, y0 = origin
        ncols = max(1, int((img.shape[1] - x0) // pitch))
        nrows = max(1, int((img.shape[0] - y0) // pitch))
        grid, player, markers = [], None, []
        for j in range(nrows):
            line = []
            for i in range(ncols):
                cx = int(x0 + i * pitch + pitch / 2)
                cy = int(y0 + j * pitch + pitch / 2)
                if cy + 1 >= img.shape[0] or cx + 1 >= img.shape[1]:
                    line.append(UNKNOWN)
                    continue
                cell = self._classify(img[max(0, cy - 1):cy + 2, max(0, cx - 1):cx + 2])
                if cell == PLAYER and player is None:
                    player = (i, j)
                elif cell == MARKER:
                    markers.append([i, j])
                line.append(cell)
            grid.append("".join(line))
        return grid, player, markers, pitch, origin

    # ---------- HUD / 条形 ----------
    def _read_battery(self) -> float | None:
        if not self.battery_box:
            return None
        img = self._grab(self.battery_box)
        if img is None or img.size == 0:
            return None
        best = 0.0
        for color in ("gold", "yellow"):
            try:
                r = perceive.probe_bar(img, None, color=color, tol=90)
                best = max(best, float(r.get("fill", 0.0)))
            except Exception:
                continue
        return round(best, 2)

    def _prompt(self) -> bool:
        if not self.prompt_box:
            return False
        img = self._grab(self.prompt_box)
        if img is None or img.size == 0:
            return False
        return bool(perceive.probe_prompt(img, None, min_ratio=0.02).get("hit"))

    # ---------- 快照 ----------
    def snapshot(self) -> WorldSnapshot:
        t0 = time.time()
        snap = WorldSnapshot(ts=t0)
        try:
            grid, player, markers, pitch, origin = self.minimap()
            snap.grid, snap.player, snap.markers = grid, player, markers
            snap.pitch, snap.origin = pitch, origin
            snap.battery = self._read_battery()
            snap.prompt = self._prompt()
        except Exception as exc:
            snap.error = f"{type(exc).__name__}: {exc}"
        self._last = snap
        return snap

    def last(self) -> WorldSnapshot | None:
        return self._last


# ══════════════════════════ M2：伺服 ══════════════════════════
class Servo:
    """目标 → 动作，每帧算误差持续修正。

    朝向怎么来的：不读罗盘，**走一小步看地图上的位移方向**（自校准）。
    这样不需要游戏配合，任何有地图的游戏都能用。
    """

    def __init__(self, ws: WorldState, keyboard, mouse,
                 px_per_deg: float = 10.0, tap_ms: float = 140):
        self.ws = ws
        self.kb = keyboard
        self.ms = mouse
        self.px_per_deg = px_per_deg
        self.tap_ms = tap_ms
        self._heading: float | None = None
        self._heading_ts = 0.0
        self.trace: list[dict] = []

    # ---------- 基础动作 ----------
    def _press(self, key: str, ms: float) -> None:
        self.kb.press(key)
        time.sleep(max(0.01, ms / 1000.0))
        self.kb.release(key)

    def forward(self, ms: float | None = None) -> None:
        self._press("w", ms if ms is not None else self.tap_ms)

    def turn_px(self, px: int) -> None:
        self.ms.move(px, 0)

    def face_deg(self, deg: float) -> None:
        """转身指定角度（正=右）。用标定好的 px/deg。"""
        self.turn_px(int(round(deg * self.px_per_deg)))
        time.sleep(0.03)

    # ---------- 朝向自校准 ----------
    def estimate_heading(self, ttl: float = 6.0) -> float | None:
        """走一小步，用玩家标记在地图上的位移方向当朝向（弧度，0=右，逆时针为正）。"""
        if self._heading is not None and time.time() - self._heading_ts < ttl:
            return self._heading
        before = self.ws.snapshot()
        if not before.player:
            return None
        self.forward(self.tap_ms)
        time.sleep(0.12)
        after = self.ws.snapshot()
        if not after.player or after.player == before.player:
            return None                      # 被挡住，测不出来
        dc = after.player[0] - before.player[0]
        dr = after.player[1] - before.player[1]
        # 屏幕上 y 向下，地图行向下；朝向用数学角（上=90°）
        ang = float(np.degrees(np.arctan2(-dr, dc)))
        self._heading = ang
        self._heading_ts = time.time()
        self.trace.append({"t": round(time.time(), 2), "op": "estimate_heading",
                           "deg": round(ang, 1), "delta": [dc, dr]})
        return ang

    # ---------- 定向移动 ----------
    def bearing_to(self, cell: tuple, frm: tuple) -> float:
        dc = cell[0] - frm[0]
        dr = cell[1] - frm[1]
        return float(np.degrees(np.arctan2(-dr, dc)))

    def face_toward(self, cell: tuple, tol: float = 18.0) -> dict:
        """转向目标格。朝向未知时先自校准；转完返回误差。"""
        snap = self.ws.snapshot()
        if not snap.player:
            return {"ok": False, "reason": "地图上找不到玩家标记"}
        want = self.bearing_to(cell, snap.player)
        have = self._heading
        if have is None:
            have = self.estimate_heading()
        if have is None:
            return {"ok": False, "reason": "朝向标定失败（可能被墙挡住）", "want": want}
        diff = (want - have + 540) % 360 - 180       # 数学角：逆时针为正
        # 约定不一致：鼠标右移 = 视角顺时针 = 数学角**减小**。
        # 所以要把 diff 取负再交给 face_deg（正数=右转）。这个 bug 是单测抓出来的。
        self.face_deg(-diff)
        time.sleep(0.05)
        return {"ok": abs(diff) <= tol, "turned_deg": round(-diff, 1),
                "want": round(want, 1), "had": round(have, 1)}

    def approach(self, cell: tuple, max_steps: int = 40, tol_cells: float = 1.5,
                 step_ms: float | None = None, on_step=None) -> dict:
        """朝目标格走过去：每步重新读状态、修正朝向、前进。到不了就报卡住。"""
        history, stuck = [], 0
        best_dist, no_progress = float("inf"), 0
        for i in range(max_steps):
            snap = self.ws.snapshot()
            if not snap.player:
                return {"ok": False, "reason": "丢失玩家标记", "steps": i}
            d = float(np.hypot(cell[0] - snap.player[0], cell[1] - snap.player[1]))
            history.append({"i": i, "player": snap.player, "dist": round(d, 2),
                            "prompt": snap.prompt})
            if on_step:
                on_step(len(history) - 1, snap)
            if d <= tol_cells:
                self.trace.append({"op": "approach", "ok": True, "steps": i, "dist": round(d, 2)})
                return {"ok": True, "steps": i, "dist": round(d, 2), "history": history[-5:]}
            r = self.face_toward(cell)
            if not r.get("ok"):
                # 转不准就先自校准一次再试
                self._heading = None
                r2 = self.face_toward(cell)
                if not r2.get("ok"):
                    stuck += 1
            self.forward(step_ms or self.tap_ms)
            time.sleep(0.05)
            # 只统计「连续两次读到的玩家格完全相同」。早先写成 history[-1] == history[-3]，
            # 结果「转向 + 前进」交替时会被误判成卡住（单测抓出来的）。
            if len(history) >= 2 and history[-1]["player"] == history[-2]["player"]:
                stuck += 1
            else:
                stuck = 0
            if stuck >= 4:
                return {"ok": False, "reason": "连续无位移（贴墙或朝向错）",
                        "steps": i, "dist": round(d, 2), "history": history[-5:]}
            # 防振荡：实测会出现在对角相邻处 A↔B 来回晃（dist 恒为 1.41）。
            # 连续 6 步没有变得更近就退出，把控制权交回上层，别死循环。
            if d < best_dist - 0.05:
                best_dist, no_progress = d, 0
            else:
                no_progress += 1
                if no_progress >= 6:
                    return {"ok": False,
                            "reason": f"原地打转（最近只到 {round(best_dist, 2)} 格）",
                            "steps": i, "dist": round(d, 2), "history": history[-5:]}
        # 用 history 里的最后一个位置算距离：ws.last() 在"快照被替换"的场景下可能是 None
        last_player = history[-1]["player"] if history else cell
        return {"ok": False, "reason": "超过最大步数", "steps": max_steps,
                "dist": round(float(np.hypot(cell[0] - last_player[0],
                                             cell[1] - last_player[1])), 2),
                "history": history[-5:]}


# ══════════════════════════ M3：监督器 ══════════════════════════
class Supervisor:
    """跑计划，只在 4 种情况把控制权交回模型。

    为什么需要：模型 0.2–0.5 Hz，不能每个动作都等。这个类在本地按 20–30 Hz 推进，
    只在「达成 / 卡住 / 不确定 / 见到新东西」时返回，并附一页状态。
    """

    def __init__(self, ws: WorldState, servo: Servo, panic=None):
        self.ws = ws
        self.servo = servo
        self.panic = panic
        self.events: list[dict] = []

    def _emit(self, kind: str, **kw) -> dict:
        ev = {"kind": kind, **kw}
        self.events.append(ev)
        return ev

    def run(self, plan: list[dict], max_seconds: float = 90.0) -> dict:
        t0 = time.time()
        deadline = t0 + max_seconds
        done: list[dict] = []
        for step in plan or []:
            if time.time() > deadline:
                return {"ok": False, "reason": "计划超时", "done": done,
                        "state": self._page(), "events": self.events}
            if self.panic is not None and getattr(self.panic, "triggered", False):
                return {"ok": False, "reason": "急停触发", "done": done,
                        "state": self._page(), "events": self.events}

            kind = (step.get("kind") or "").lower()
            if kind == "goto":
                cell = tuple(step["cell"])
                r = self.servo.approach(cell, max_steps=int(step.get("max_steps", 40)),
                                        tol_cells=float(step.get("tol_cells", 1.5)))
                done.append({"kind": "goto", "cell": cell, "result": r})
                if not r.get("ok"):
                    # 卡住 → 交回模型（这就是 supervisor 的价值：只在此时叫他）
                    return {"ok": False, "reason": f"走不到 {cell}", "done": done,
                            "state": self._page(), "events": self.events}
            elif kind == "search":
                # 在当前位置附近按 E，直到提示消失或超时
                n = int(step.get("times", 3))
                for _ in range(n):
                    self.servo._press("e", float(step.get("hold_ms", 1500)))
                    snap = self.ws.snapshot()
                    if not snap.prompt:
                        break
                done.append({"kind": "search", "result": "ok"})
            elif kind == "face":
                r = self.servo.face_toward(tuple(step["cell"]))
                done.append({"kind": "face", "result": r})
            elif kind == "wait":
                time.sleep(float(step.get("ms", 300)) / 1000.0)
                done.append({"kind": "wait", "result": "ok"})
            elif kind == "key":
                self.servo._press(step.get("key", "e"), float(step.get("hold_ms", 200)))
                done.append({"kind": "key", "key": step.get("key"), "result": "ok"})
            else:
                done.append({"kind": kind, "result": "unknown_op"})

        return {"ok": True, "reason": "计划完成", "done": done,
                "state": self._page(), "seconds": round(time.time() - t0, 2),
                "events": self.events}

    def _page(self) -> dict:
        snap = self.ws.snapshot()
        return {"state": snap.as_dict(), "text": snap.text(),
                "trace": self.servo.trace[-12:]}
