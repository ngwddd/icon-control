"""micro.py — 端上闭环脚本解释器（v0.4 / P1）

为什么需要：
    以前"走一步 → 截图 → 判断 → 走下一步"要一次模型往返（秒级）。
    40 步就是 40 次往返，而游戏只给 2 分 44 秒 —— 时间全花在通信上。
    这个解释器让**整段循环在本地跑完**，模型只发一次意图、收一份 trace。

支持的 op（JSON 友好）：

    {"op":"key",   "key":"w", "hold_ms":500}          # 按一下/按住
    {"op":"press", "keys":["shift","w"], "hold_ms":300}
    {"op":"turn",  "px":430}                          # 鼠标相对位移（视角）
    {"op":"move",  "x":100,"y":200}                   # 鼠标绝对定位
    {"op":"click", "button":"left"}
    {"op":"sleep", "ms":120}
    {"op":"loop",  "times":40, "do":[...]}            # 循环
    {"op":"until", "timeout_ms":8000, "cond":{...}, "do":[...], "poll_ms":30}
    {"op":"if",    "cond":{...}, "then":[...], "else":[...]}
    {"op":"log",   "text":"..."}

cond（条件）格式：
    {"kind":"prompt",   "box":[x,y,w,h], "min_ratio":0.004}
    {"kind":"bar",      "box":[...], "color":"green", "op":"gt", "value":0.2}
    {"kind":"digits",   "box":[...], "op":"lt", "value":30}
    {"kind":"openness", "box":[...], "op":"gt", "value":28}
    {"kind":"color",    "box":[...], "color":"red"}
    {"kind":"diff",     "box":[...], "op":"lt", "value":1.0}   # 与上一步的帧比

box 用**屏幕坐标**；解释器会按采集缩放自动换算（这点最容易错，写在 to_frame_box）。
"""

from __future__ import annotations

import time

from computer_mcp import perceive

MAX_STEPS = 4000
MAX_SECONDS = 120.0


def to_frame_box(box, scale: float, origin=(0, 0)):
    """屏幕坐标 → 采集帧坐标。scale 是采集缩放（0.25 表示缩小 4 倍）。"""
    if box is None:
        return None
    step = max(1, int(round(1.0 / max(0.05, scale))))
    x, y, w, h = perceive.norm_box(box)
    ox, oy = origin
    return ((x - ox) // step, (y - oy) // step,
            max(1, w // step), max(1, h // step))


def eval_cond(cond: dict, frame, prev_frame=None, scale: float = 1.0,
              origin=(0, 0)) -> bool:
    """判断一个条件。frame 是采集帧的 numpy 图。"""
    if frame is None:
        return False
    box = to_frame_box(cond.get("box"), scale, origin)
    kind = (cond.get("kind") or "").lower()

    if kind == "prompt":
        r = perceive.probe_prompt(frame, box, thr=int(cond.get("thr", 150)),
                                  min_ratio=float(cond.get("min_ratio", 0.004)))
        return bool(r.get("hit"))

    if kind in ("bar", "openness", "color", "digits"):
        r = perceive.probe(kind, frame, box,
                           color=cond.get("color", "green"),
                           tol=int(cond.get("tol", 60)))
        if "hit" in r and kind == "color":
            return bool(r["hit"])
        key = {"bar": "fill", "openness": "score", "digits": None}.get(kind)
        if kind == "digits":
            try:
                val = float(str(r.get("text") or "").strip() or "nan")
            except ValueError:
                return False
        else:
            val = float(r.get(key, 0.0))
        op = cond.get("op", "gt")
        want = float(cond.get("value", 0.0))
        return {"gt": val > want, "gte": val >= want,
                "lt": val < want, "lte": val <= want,
                "eq": abs(val - want) < 1e-6}.get(op, False)

    if kind == "diff":
        if prev_frame is None:
            return False
        d = perceive.diff_region(prev_frame, frame, box)
        op = cond.get("op", "lt")
        want = float(cond.get("value", 1.0))
        val = float(d.get("mean", 0.0))
        return {"gt": val > want, "gte": val >= want,
                "lt": val < want, "lte": val <= want}.get(op, False)

    return False


class Runner:
    """执行一段微脚本，返回 trace。"""

    def __init__(self, daemon, keyboard, mouse, scale: float, origin=(0, 0),
                 max_seconds: float = MAX_SECONDS):
        self.d = daemon
        self.kb = keyboard
        self.ms = mouse
        self.scale = scale
        self.origin = origin
        self.deadline = time.time() + min(MAX_SECONDS, max_seconds)
        self.trace: list[dict] = []
        self.steps = 0
        self.stopped = False
        self.stop_reason = ""
        self._t0 = time.time()

    # ---------- 工具 ----------
    def frame(self):
        f = self.d.latest()
        return f.img if f else None

    def log(self, text: str, **kw) -> None:
        row = {"t": round(time.time() - self._t0, 3), "op": "log", "text": text}
        row.update(kw)
        self.trace.append(row)

    def _budget(self) -> bool:
        self.steps += 1
        if self.steps > MAX_STEPS:
            self.stopped, self.stop_reason = True, "超过最大步数"
            return False
        if time.time() > self.deadline:
            self.stopped, self.stop_reason = True, "超过最大时长"
            return False
        return True

    def _press(self, keys, hold_ms: float) -> None:
        keys = keys if isinstance(keys, list) else [keys]
        for k in keys:
            self.kb.press(k)
        time.sleep(max(0.0, hold_ms / 1000.0))
        for k in reversed(keys):
            self.kb.release(k)

    # ---------- 执行 ----------
    def run(self, ops: list, depth: int = 0) -> None:
        if depth > 8:
            self.stopped, self.stop_reason = True, "嵌套过深"
            return
        for op in ops or []:
            if self.stopped or not self._budget():
                return
            kind = (op.get("op") or "").lower()

            if kind in ("key",):
                hold = float(op.get("hold_ms", 120))
                self._press(op.get("key", "space"), hold)
                self.trace.append({"t": round(time.time() - self._t0, 3), "op": "key",
                                   "key": op.get("key"), "hold_ms": hold})
            elif kind in ("press",):
                hold = float(op.get("hold_ms", 120))
                self._press(op.get("keys", ["space"]), hold)
                self.trace.append({"t": round(time.time() - self._t0, 3), "op": "press",
                                   "keys": op.get("keys"), "hold_ms": hold})
            elif kind == "turn":
                px = int(op.get("px", 0))
                self.ms.move(px, 0)
                self.trace.append({"t": round(time.time() - self._t0, 3), "op": "turn", "px": px})
            elif kind == "move":
                self.ms.position = (int(op.get("x", 0)), int(op.get("y", 0)))
            elif kind == "click":
                self.ms.click(getattr(__import__("pynput.mouse", fromlist=["Button"]).Button,
                                      op.get("button", "left")))
            elif kind == "sleep":
                time.sleep(max(0, int(op.get("ms", 100))) / 1000.0)
            elif kind == "log":
                self.log(str(op.get("text", "")))
            elif kind == "loop":
                for _ in range(int(op.get("times", 1))):
                    if self.stopped:
                        break
                    self.run(op.get("do") or [], depth + 1)
            elif kind == "if":
                ok = eval_cond(op.get("cond") or {}, self.frame(),
                               self.frame(), self.scale, self.origin)
                self.log(f"if → {ok}")
                self.run(op.get("then") if ok else (op.get("else") or []), depth + 1)
            elif kind == "until":
                self._until(op, depth)
            else:
                self.log(f"未知 op：{kind}")

    def _until(self, op: dict, depth: int) -> None:
        """重复 do 直到 cond 成立 / 超时。这是"闭环"的核心。"""
        timeout = float(op.get("timeout_ms", 5000)) / 1000.0
        poll = max(0.01, float(op.get("poll_ms", 30)) / 1000.0)
        cond = op.get("cond") or {}
        body = op.get("do") or []
        t_end = min(time.time() + timeout, self.deadline)
        iters = 0
        while time.time() < t_end and not self.stopped:
            iters += 1
            cur = self.frame()
            if eval_cond(cond, cur, cur, self.scale, self.origin):
                self.log(f"until 命中（第 {iters} 次）", cond=cond)
                return
            if body:
                self.run(body, depth + 1)
            else:
                time.sleep(poll)
        self.log(f"until 超时（{iters} 次）", cond=cond)

    # ---------- 结果 ----------
    def result(self) -> dict:
        f = self.d.latest()
        return {"steps": self.steps, "seconds": round(time.time() - self._t0, 2),
                "stopped": self.stopped, "stop_reason": self.stop_reason,
                "frame": f.summary() if f else None,
                "trace": self.trace[-80:]}
