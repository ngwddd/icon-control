"""program.py — 指令流：一行一条指令，facts 里放"不变量"

这是把"每次即兴"变成"写一次剧本"的最小实现：

    facts.json        不变量（坐标、区域、窗口签名）——量一次，带 measured_at
    program.jsonl    指令流，一行一条，可读、可 diff、可重放

指令格式（每行一个 JSON）：

    {"op":"focus","title":"文件传输助手"}                  # 换目标窗口
    {"op":"click","at":"@wx.rail.discover"}                # 软选择器优先，坐标兜底
    {"op":"click","find":{"text":"朋友圈"},"at":"@wx.fly.moments"}
    {"op":"scroll","dy":-360,"at":[0.62,0.55]}
    {"op":"paste","text":"$MSG"}                           # $NAME 从 facts 取
    {"op":"send","text":"$MSG","title":"文件传输助手", ...}  # 四段验证的发送
    {"op":"assert","expect":{"kind":"text","query":"clicks=1"}}
    {"op":"branch","if":{"kind":"text","query":"保留"},"then":[...],"else":[...]}
    {"op":"photo","name":"after_send"}

`@name` 从 facts 取值，`$name` 从 facts 取字符串；没定义就原样保留并报错。

为什么要有它（而不是继续写 Python）：
    · 指令能像代码一样 review / diff / 回滚
    · 出错时**停在哪一行一目了然**，那一行就是缺陷
    · 同一份剧本换个窗口尺寸/换个账号还能跑
"""

from __future__ import annotations

import json
import os
import re
import time
from computer_mcp import execution as _execution
from typing import Any

from computer_mcp import train

_REF = re.compile(r"^[@$]([A-Za-z0-9_.\-]+)$")


# ─────────────────────────── facts ───────────────────────────

def load_facts(path: str) -> dict:
    """读 facts.json：不变量 + measured_at。读不到就返回空（调用方自己判断）。"""
    if not path or not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _lookup(facts: dict, name: str) -> Any:
    cur: Any = facts
    for part in name.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            raise KeyError(name)
    return cur


def expand(value: Any, facts: dict) -> Any:
    """把 "@a.b" / "$a.b" 展开成 facts 里的值（递归处理 list/dict）。

    · `@name` 原样取（可以是列表、数字、坐标对）
    · `$name` 取字符串（用于文本）
    · 找不到就**抛 KeyError**：宁可停下，也不要用错的坐标继续跑
    """
    if isinstance(value, str):
        m = _REF.match(value.strip())
        if m:
            return _lookup(facts, m.group(1))
        # 字符串内嵌 $NAME（例如 "验证 $stamp"）
        if "$" in value:

            def sub(mo: re.Match) -> str:
                return str(_lookup(facts, mo.group(1)))

            return re.sub(r"\$([A-Za-z0-9_.\-]+)", sub, value)
        return value
    if isinstance(value, list):
        return [expand(v, facts) for v in value]
    if isinstance(value, dict):
        return {k: expand(v, facts) for k, v in value.items()}
    return value


# ─────────────────────────── program ───────────────────────────

def load_program(path: str) -> list[dict]:
    """读 program.jsonl：一行一条；空行和 # 注释跳过。"""
    out: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                ins = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"第 {lineno} 行不是合法 JSON：{e}") from e
            if not isinstance(ins, dict) or "op" not in ins:
                raise ValueError(f"第 {lineno} 行缺少 op 字段")
            ins["_line"] = lineno
            out.append(ins)
    return out


def _as_action(ins: dict) -> dict:
    """把一条指令翻译成 train.do_action 认识的动作。"""
    op = ins.get("op")
    if op == "click":
        act = {"kind": "click"}
        for k in ("find", "rel_frac", "settle_ms", "button", "clicks"):
            if k in ins:
                act[k] = ins[k]
        if "at" in ins and "rel_frac" not in act:
            act["rel_frac"] = ins["at"]
        return act
    if op == "scroll":
        return {"kind": "scroll", "dy": ins.get("dy", -360),
                "times": ins.get("times", 1),
                "at_rel_frac": ins.get("at") or [0.6, 0.5]}
    if op == "paste":
        return {"kind": "paste", "text": ins.get("text", "")}
    if op == "key":
        return {"kind": "key", "key": ins.get("key", "enter")}
    if op == "wait":
        return {"kind": "wait", "ms": ins.get("ms", 300)}
    if op == "send":
        return dict(ins, kind="send", op=None)
    return {}


def _run_with_wheel(instructions: list[dict], facts: dict, hwnd: int = 0,
                    rect: tuple[int, int, int, int] | None = None,
                    stop_on_fail: bool = True, wheel=None) -> dict:
    from computer_mcp.tasks import Task
    if rect is None:
        if not hwnd:
            return dict(ok=False, state="failed", verified=False, done=0,
                        failed="A target window or rectangle is required", log=[])
        import win32gui
        l, t, r, b = win32gui.GetWindowRect(hwnd)
        rect = (l, t, r-l, b-t)
    return Task(instructions, facts, hwnd, rect, stop_on_fail, wheel).run()


def run(instructions: list[dict], facts: dict, hwnd: int = 0,
        rect: tuple[int, int, int, int] | None = None,
        stop_on_fail: bool = True) -> dict:
    """执行指令流；自己没有帧环就临时起一个（changed/stable 判据需要它）。"""
    own = False
    wheel = None
    if rect is None and hwnd:
        import win32gui

        l, t, r, b = win32gui.GetWindowRect(hwnd)
        rect = (l, t, r - l, b - t)
    if rect is not None:
        # FrameWheel(rect, ring, events, ...)：第二个参数是 ThumbRing，不是 hwnd
        ring = train.ThumbRing()
        wheel = train.FrameWheel(rect, ring, train.EventLog())
        wheel.start()
        own = True
        _execution.sleep(0.3)
    try:
        return _run_with_wheel(instructions, facts, hwnd, rect, stop_on_fail, wheel)
    finally:
        if own and wheel is not None:
            try:
                wheel.stop()
            except Exception:
                pass
