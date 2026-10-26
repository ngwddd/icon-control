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
    """按顺序执行指令流，返回 {"ok","done","failed","log"}。

    约定：
        · 每条指令都可带 `expect`（后置条件）与 `on_fail`（stop|continue）
        · `assert` 只判不动作
        · `branch` 的条件成立就跑 then，否则 else（都是指令列表）
    """
    if rect is None:
        if not hwnd:
            return {"ok": False, "done": 0, "failed": "既没有 hwnd 也没有 rect",
                    "log": []}
        import win32gui

        l, t, r, b = win32gui.GetWindowRect(hwnd)
        rect = (l, t, r - l, b - t)

    log: list[str] = []
    ok_all = True
    done = 0

    for ins in instructions:
        op = ins.get("op")
        line = ins.get("_line", "?")
        try:
            exp = expand({k: v for k, v in ins.items() if k != "op"}, facts)
        except KeyError as e:
            return {"ok": False, "done": done,
                    "failed": f"第 {line} 行引用了未定义的名字：{e}", "log": log}

        expect = exp.pop("expect", None)
        on_fail = exp.pop("on_fail", "stop")

        if op == "focus":
            hit = train._find_window(str(exp.get("title", "")), same_pid=None)
            if hit:
                fh, fr = hit
                rect = (fr[0], fr[1], fr[2] - fr[0], fr[3] - fr[1])
                hwnd = fh
                log.append(f"L{line} focus → {fh} {exp.get('title')}")
            else:
                log.append(f"L{line} focus 未找到 {exp.get('title')}（沿用当前）")
            done += 1
            continue

        if op == "assert":
            cond = exp.get("expect") or expect
            # 断言也轮询：OCR 对小字要 1-2 次才读准（"流"曾被读成"氵夼"）
            deadline = time.time() + float(ins.get("timeout_ms", 3000)) / 1000.0
            v = None
            while time.time() < deadline:
                v = train.check_expect(cond, wheel, rect, hwnd)
                if v is True:
                    break
                time.sleep(0.25)
            log.append(f"L{line} assert {exp.get('expect') or expect} → {v}")
            if v is not True:
                ok_all = False
                if stop_on_fail:
                    return {"ok": False, "done": done,
                            "failed": f"第 {line} 行断言不成立", "log": log}
            else:
                done += 1
            continue

        if op in ("branch", "photo"):
            # branch 里可以放子指令；photo 交给 train 的 bundle（这里只记日志）
            log.append(f"L{line} {op}（暂未实现子流程，先记录）")
            done += 1
            continue

        action = _as_action(dict(exp, op=op))
        mark = time.time()          # ★ 动作时刻：后置条件的"自那时起"基准，不能每轮重置
        res = train.do_action(action, rect, hwnd)
        log.append(f"L{line} {op}: {res.get('detail')}")
        if not res.get("ok"):
            ok_all = False
            if on_fail == "stop" and stop_on_fail:
                return {"ok": False, "done": done,
                        "failed": f"第 {line} 行动作失败：{res.get('detail')}",
                        "log": log}
        if expect:
            # **轮询**直到超时（一次性检查会漏：朋友圈要 1-2 秒才加载出来）
            deadline = time.time() + float(ins.get("timeout_ms", 8000)) / 1000.0
            v = None
            while time.time() < deadline:
                v = train.check_expect(expect, wheel, rect, hwnd, mark)
                if v is True:
                    break
                time.sleep(0.12)
            log.append(f"L{line} expect {expect} → {v}")
            if v is not True:
                ok_all = False
                if on_fail == "stop" and stop_on_fail:
                    return {"ok": False, "done": done,
                            "failed": f"第 {line} 行后置条件不成立", "log": log}
        done += 1

    return {"ok": ok_all, "done": done, "failed": "", "log": log}


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
        time.sleep(0.3)
    try:
        return _run_with_wheel(instructions, facts, hwnd, rect, stop_on_fail, wheel)
    finally:
        if own and wheel is not None:
            try:
                wheel.stop()
            except Exception:
                pass
