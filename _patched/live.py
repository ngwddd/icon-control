"""live.py — v0.4 新工具的实现层（采集/感知/闭环/数字/录制）

这一层只做三件事：把屏幕坐标换成帧坐标、把参数校验好、把结果压成模型能读的 JSON。
真正的活在各模块里：
    capture_daemon.py  常驻采集 + 环形缓冲 + 事件等待
    perceive.py        像素原语（1~3 ms）
    digits.py          数字模板匹配
    micro.py           微脚本解释器（端上闭环）
"""

from __future__ import annotations

import json
import os
import time

from computer_mcp import perceive
from computer_mcp.capture_daemon import CaptureDaemon

_DRAW = os.path.join(os.path.expanduser("~"), ".dsh", "tools", "desktop-mcp", "_draw")
_RECORD_ROOT = os.path.join(os.path.expanduser("~"), ".dsh", "tools", "desktop-mcp", "recordings")

# 最近一次 run_script 的 trace（给 trace 工具用）
_LAST_RUN: dict = {}
_RUN_HISTORY: list[dict] = []


def _daemon() -> CaptureDaemon:
    return CaptureDaemon.shared()


def _controllers():
    from pynput.keyboard import Controller as KB
    from pynput.mouse import Controller as MS
    return KB(), MS()


def _frame_box(region):
    """屏幕坐标 → 帧坐标（按采集缩放与监视器原点换算）。"""
    d = _daemon()
    from computer_mcp.micro import to_frame_box
    return to_frame_box(region, d.scale, getattr(d, "origin", (0, 0)))


def _ensure_frame():
    """没有守护或没有帧时，启动守护并等第一帧。"""
    d = _daemon()
    f = d.latest()
    if f is None or not d.status().get("running"):
        d.start()
        time.sleep(0.25)
        f = d.latest()
    return f


# ══════════════════════════ P0：采集 / 感知 ══════════════════════════
def tool_capture(args: dict) -> dict:
    d = _daemon()
    action = (args or {}).get("action", "status")
    if action == "start":
        if args.get("scale") is not None:
            d.scale = max(0.1, min(1.0, float(args["scale"])))
        if args.get("active_fps"):
            d.active_fps = max(1.0, min(60.0, float(args["active_fps"])))
        if args.get("idle_fps"):
            d.idle_fps = max(0.5, min(d.active_fps, float(args["idle_fps"])))
        if args.get("monitor"):
            d.monitor = int(args["monitor"])
        res = d.start()
        return {"success": True, **res}
    if action == "stop":
        return {"success": True, **d.stop()}
    return {"success": True, **d.status()}


def tool_sense(args: dict) -> dict:
    """一次拿到「上一帧之后变了什么」+ 指定指标。"""
    a = args or {}
    f = _ensure_frame()
    d = _daemon()
    if f is None:
        return {"success": False, "error": "拿不到帧（采集失败）"}

    since = a.get("since_frame")
    deltas = []
    if since is not None:
        for fr in d.frames_between(int(since))[-30:]:
            deltas.append({"frame": fr.idx, "diff": round(fr.diff, 2),
                           "bbox": fr.bbox, "window": fr.active_window[:40]})

    prims = {}
    for spec in a.get("primitives") or []:
        name = spec.get("name") or spec.get("kind") or "p"
        kind = spec.get("kind") or "prompt"
        box = _frame_box(spec.get("box"))
        kw = {k: v for k, v in spec.items() if k not in ("name", "kind", "box")}
        try:
            prims[name] = perceive.probe(kind, f.img, box, **kw)
        except Exception as exc:
            prims[name] = {"error": f"{type(exc).__name__}: {exc}"}

    regions = {}
    for spec in a.get("regions") or []:
        name = spec.get("name") or "r"
        box = _frame_box(spec.get("box"))
        regions[name] = perceive.diff_region(
            d.get(int(since)).img if since and d.get(int(since)) else None, f.img, box)

    return {"success": True,
            "frame": f.summary(),
            "daemon": {"running": d.status()["running"], "fps": d.status()["measured_fps"],
                       "scale": d.scale, "frames": d.status()["frames"]},
            "deltas": deltas,
            "primitives": prims,
            "regions": regions,
            "since": since}


def tool_watch(args: dict) -> dict:
    """阻塞到条件成立或超时（替代 sleep + 再截图那种轮询）。"""
    a = args or {}
    cond = a.get("cond") or a.get("condition") or {}
    timeout = int(a.get("timeout_ms", 3000))
    d = _ensure_frame() and _daemon()
    from computer_mcp.micro import eval_cond

    t0 = time.time()
    def _pred(fr):
        try:
            return eval_cond(cond, fr.img, fr.img, d.scale, getattr(d, "origin", (0, 0)))
        except Exception:
            return False

    hit, fr = d.wait(_pred, timeout)
    return {"success": True, "hit": bool(hit), "elapsed_ms": int((time.time() - t0) * 1000),
            "frame": fr.summary() if fr else None, "cond": cond}


def tool_probe(args: dict) -> dict:
    """单个像素原语（最快的一条路，1~3 ms）。"""
    a = args or {}
    kind = a.get("kind") or "prompt"
    f = _ensure_frame()
    if f is None:
        return {"success": False, "error": "拿不到帧"}
    box = _frame_box(a.get("box"))
    kw = {k: v for k, v in a.items() if k not in ("kind", "box")}
    try:
        res = perceive.probe(kind, f.img, box, **kw)
    except Exception as exc:
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"success": True, "kind": kind, "frame": f.idx, "result": res}


def tool_snapshot(args: dict) -> dict:
    """按需抓一张（可裁区域、可缩放），存盘并返回路径 —— 不往对话里塞 base64。"""
    a = args or {}
    import mss
    from PIL import Image
    os.makedirs(_DRAW, exist_ok=True)
    region = a.get("region")
    scale = float(a.get("scale", 1.0))
    with mss.mss() as sct:
        mon = sct.monitors[1]
        box = {"left": mon["left"], "top": mon["top"], "width": mon["width"], "height": mon["height"]}
        if region:
            x, y, w, h = perceive.norm_box(region)
            box = {"left": x, "top": y, "width": w, "height": h}
        shot = sct.grab(box)
    im = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    if scale != 1.0:
        im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS)
    path = os.path.join(_DRAW, f"snap_{int(time.time()*1000)}.png")
    im.save(path)
    # 写完就按策略裁剪，别让 _draw 无限长大
    try:
        from computer_mcp import retention
        pruned = retention.sweep()
    except Exception:
        pruned = {}
    return {"success": True, "path": path, "size": list(im.size),
            "bytes": os.path.getsize(path), "region": region,
            "pruned": pruned.get("removed_count", 0)}


# ══════════════════════════ P1：闭环执行 ══════════════════════════
def tool_run_script(args: dict) -> dict:
    """端上跑一段微脚本（40 步循环 → 1 次调用）。"""
    global _LAST_RUN
    a = args or {}
    ops = a.get("ops") or a.get("steps") or []
    if not isinstance(ops, list) or not ops:
        return {"success": False, "error": "ops 必须是非空数组"}
    d = _ensure_frame() and _daemon()
    kb, ms = _controllers()
    from computer_mcp.micro import Runner

    runner = Runner(d, kb, ms, d.scale, getattr(d, "origin", (0, 0)),
                    max_seconds=float(a.get("max_seconds", 60)))
    runner.run(ops)
    res = runner.result()
    res["success"] = True
    _LAST_RUN = res
    _RUN_HISTORY.append({k: res[k] for k in ("steps", "seconds", "stopped", "stop_reason")})
    return res


def tool_act_until(args: dict) -> dict:
    """重复一个动作直到条件成立（"一直走到出现提示为止"）。"""
    a = args or {}
    cond = a.get("cond") or {}
    action = a.get("action") or {"op": "key", "key": "w", "hold_ms": 400}
    ops = [{"op": "until", "cond": cond, "timeout_ms": int(a.get("max_ms", 8000)),
            "do": [action]}]
    return tool_run_script({"ops": ops, "max_seconds": float(a.get("max_ms", 8000)) / 1000 + 5})


def tool_frame_mark(args: dict) -> dict:
    f = _ensure_frame()
    d = _daemon()
    if f is None:
        return {"success": False, "error": "拿不到帧"}
    d._marks = getattr(d, "_marks", {})
    name = (args or {}).get("name") or f"m{f.idx}"
    d._marks[name] = f.idx
    return {"success": True, "mark": name, "frame": f.idx}


def tool_frame_diff(args: dict) -> dict:
    """按帧号比两张帧（判断"这一步有没有生效"）。"""
    a = args or {}
    d = _daemon()
    fa = d.get(int(a.get("from_frame", 0)))
    fb = d.get(int(a.get("to_frame", 0))) or d.latest()
    if fa is None or fb is None:
        return {"success": False, "error": "帧号不在缓冲里（缓冲默认 120 帧）"}
    box = _frame_box(a.get("region"))
    res = perceive.diff_region(fa.img, fb.img, box)
    return {"success": True, "from": fa.idx, "to": fb.idx, **res}


def tool_trace(args: dict) -> dict:
    a = args or {}
    if a.get("history"):
        return {"success": True, "history": _RUN_HISTORY[-20:]}
    return {"success": True, "last": _LAST_RUN}


# ══════════════════════════ P2：数字 / 录制 ══════════════════════════
def tool_glyph(args: dict) -> dict:
    from computer_mcp import digits
    a = args or {}
    action = a.get("action", "list")
    if action in ("list", "status"):
        return {"success": True, **digits.learned()}
    if action == "clear":
        return {"success": True, **digits.clear_learned()}
    if action == "learn":
        f = _ensure_frame()
        if f is None:
            return {"success": False, "error": "拿不到帧"}
        box = _frame_box(a.get("box"))
        res = digits.learn(str(a.get("label", "?")), f.img, box,
                           thr=int(a.get("thr", 140)))
        return {"success": bool(res.get("ok")), **res}
    return {"success": False, "error": f"未知 action：{action}"}


def tool_read_digits(args: dict) -> dict:
    """读数字。默认**按屏幕坐标全分辨率抓取**（缩放帧上的字形太小，5x7 会抹平）。"""
    from computer_mcp import digits
    a = args or {}
    box = a.get("box")
    if not box:
        return {"success": False, "error": "缺少 box"}
    full = bool(a.get("full_res", True))
    if full:
        img = _grab_region(box)
        if img is None:
            return {"success": False, "error": "全分辨率抓取失败"}
        res = digits.read_digits(img, None, thr=int(a.get("thr", 140)),
                                 min_conf=float(a.get("min_conf", 0.55)))
        return {"success": True, "mode": "full_res", **res}
    f = _ensure_frame()
    if f is None:
        return {"success": False, "error": "拿不到帧"}
    res = digits.read_digits(f.img, _frame_box(box), thr=int(a.get("thr", 140)),
                             min_conf=float(a.get("min_conf", 0.55)))
    return {"success": True, "mode": "daemon", "frame": f.idx, **res}


def _grab_region(region) -> "np.ndarray | None":
    """按屏幕坐标抓一块**全分辨率**图（读数字/读小字时用，daemon 的缩放帧不够）。"""
    import mss
    import numpy as np
    from PIL import Image
    x, y, w, h = perceive.norm_box(region)
    try:
        with mss.mss() as sct:
            shot = sct.grab({"left": int(x), "top": int(y), "width": int(w), "height": int(h)})
        return np.asarray(Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX"),
                          dtype=np.uint8)
    except Exception:
        return None


def tool_hud(args: dict) -> dict:
    """自动定位 HUD：**按全分辨率抓取**再按颜色扫行。

    为什么不用守护的缩放帧：块平均会把 1px 的字体笔画和背景混成一半亮度
    （纯青 (0,255,255) 变成 (0,127,127)），颜色根本匹配不上。
    HUD 区域很小，抓一次 25 ms，正确性优先。

    返回每行的屏幕坐标 box，可直接喂给 read_digits / probe。
    """
    a = args or {}
    f = _ensure_frame()
    if f is None:
        return {"success": False, "error": "拿不到帧"}
    d = _daemon()
    search = a.get("box")
    if search is None:
        return {"success": False, "error": "需要 box=[x,y,w,h]（HUD 所在区域，屏幕坐标）"}
    img = _grab_region(search)
    if img is None:
        return {"success": False, "error": "全分辨率抓取失败"}
    ox, oy = perceive.norm_box(search)[:2]
    out = {}
    for spec in (a.get("colors") or [{"name": "cyan", "color": "cyan"},
                                     {"name": "yellow", "color": "yellow"}]):
        rows = perceive.locate_rows(img, None, color=spec.get("color", "cyan"),
                                    tol=int(spec.get("tol", 70)),
                                    min_px=int(spec.get("min_px", 6)))
        out[spec.get("name", spec.get("color"))] = [
            {"box": [ox + r["box"][0], oy + r["box"][1], r["box"][2], r["box"][3]],
             "y0": oy + r["y0"], "y1": oy + r["y1"]} for r in rows]
    return {"success": True, "frame": f.idx, "mode": "full_res", "rows": out}


def tool_record(args: dict) -> dict:
    """把最近缓冲里的帧 + 事件落盘（回放/证据）。"""
    a = args or {}
    action = a.get("action", "stop")
    d = _daemon()
    if action == "start":
        d._recording = True
        return {"success": True, "recording": True, "note": "开始录制（帧写入缓冲，stop 时落盘）"}
    if action == "stop":
        d._recording = False
        frames = list(d._frames)
        if not frames:
            return {"success": False, "error": "缓冲里没有帧"}
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out = os.path.join(_RECORD_ROOT, stamp)
        os.makedirs(out, exist_ok=True)
        from PIL import Image
        manifest = {"started": frames[0].ts, "frames": [], "trace": _LAST_RUN.get("trace", [])}
        for fr in frames[-120:]:
            # JPEG 而不是 PNG：同样的帧，体积小一个数量级（实测 17 帧 PNG 9.4 MB → JPEG 约 0.3 MB）
            name = f"f{fr.idx:05d}.jpg"
            try:
                Image.fromarray(fr.img).save(os.path.join(out, name), quality=80)
                manifest["frames"].append({"idx": fr.idx, "file": name,
                                           "diff": round(fr.diff, 2),
                                           "window": fr.active_window[:40]})
            except Exception:
                continue
        with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=1)
        try:
            from computer_mcp import retention
            pruned = retention.sweep()
        except Exception:
            pruned = {}
        return {"success": True, "dir": out, "frames": len(manifest["frames"]),
                "bytes": sum(os.path.getsize(os.path.join(out, f))
                             for f in os.listdir(out)),
                "pruned_old": pruned.get("removed_count", 0)}
    return {"success": False, "error": "action 只支持 start/stop"}


def tool_housekeeping(args: dict) -> dict:
    """看用量 / 清扫。默认只报告，不删。"""
    from computer_mcp import retention
    a = args or {}
    action = a.get("action", "status")
    dry = bool(a.get("dry_run", action == "status"))
    if action == "status":
        return {"success": True, **retention.usage()}
    if action == "sweep":
        res = retention.sweep_all(dry_run=dry)
        res["success"] = True
        return res
    return {"success": False, "error": f"未知 action：{action}（status / sweep）"}


# ══════════════════════════ M1/M2/M3：导航三层 ══════════════════════════
_WS_CACHE: dict = {}


def _world_state(args: dict):
    """按配置构建（并缓存）WorldState —— pitch 标定要跨调用保留。"""
    from computer_mcp import navigator

    a = args or {}
    key = (tuple(a.get("map_region") or ()), tuple(a.get("prompt_box") or ()),
           tuple(a.get("battery_box") or ()))
    if key in _WS_CACHE:
        return _WS_CACHE[key]
    cfg = navigator.MapConfig(region=a.get("map_region"),
                             pitch=a.get("pitch"),
                             dark_max=int(a.get("dark_max", 45)))
    ws = navigator.WorldState(_grab_region, map_cfg=cfg,
                              prompt_box=a.get("prompt_box"),
                              battery_box=a.get("battery_box"))
    _WS_CACHE[key] = ws
    return ws


def _servo(args: dict):
    from computer_mcp import navigator
    ws = _world_state(args)
    kb, ms = _controllers()
    s = navigator.Servo(ws, kb, ms,
                        px_per_deg=float((args or {}).get("px_per_deg", 10.0)),
                        tap_ms=float((args or {}).get("tap_ms", 140)))
    return s


def tool_world_state(args: dict) -> dict:
    """M1：把画面压成结构化状态（小地图网格 + 玩家/目标 + 提示 + 电量）。

    auto 模式（默认）：没给 map_region 时**自动识别**小地图区域，
    不再需要按游戏手填坐标。
    """
    a = dict(args or {})
    # ① 先用"标定档案"：这是通用路径（看一眼 → 记住 → 复用）
    if a.get("hwnd") and not a.get("map_region"):
        from computer_mcp import layout_mem
        import win32gui as _wg
        try:
            _h = int(a["hwnd"])
            _cx, _cy, _cw, _ch = _client_canvas(_h)
            _prof = layout_mem.find_profile(_wg.GetWindowText(_h), (_cw, _ch))
            if _prof:
                _boxes = layout_mem.resolve(_prof, (_cx, _cy, _cw, _ch))
                a.setdefault("map_region", _boxes.get("map"))
                a.setdefault("prompt_box", _boxes.get("prompt"))
                a.setdefault("battery_box", _boxes.get("bar"))
                a["_profile"] = _prof.get("stem")
        except Exception:
            pass
    # auto 默认**关闭**：通用布局探测器（screen_model）目前在真实画面上还不准
    # （实测：内容区、文字行、网格、进度条四项全错）。要试就显式 auto=true。
    # 现在可靠的路子仍是"一次性标定 + 记忆"（见 AGENTS.md）。
    if a.get("auto") and not a.get("map_region") and a.get("hwnd"):
        reg = _auto_map_region(a)
        if reg:
            a["map_region"] = reg
    ws = _world_state(a)
    snap = ws.snapshot()
    return {"success": not snap.error, "state": snap.as_dict(),
            "text": snap.text(), "error": snap.error}


def tool_servo(args: dict) -> dict:
    """M2：单条伺服动作。op=calibrate|face|approach|forward|turn。"""
    a = args or {}
    op = (a.get("op") or "calibrate").lower()
    s = _servo(a)
    if op == "calibrate":
        return {"success": True, "heading_deg": s.estimate_heading(ttl=0)}
    if op == "face":
        r = s.face_toward(tuple(a["cell"]))
        return {"success": bool(r.get("ok")), **r}
    if op == "approach":
        r = s.approach(tuple(a["cell"]), max_steps=int(a.get("max_steps", 40)),
                       tol_cells=float(a.get("tol_cells", 1.0)))
        return {"success": bool(r.get("ok")), **r}
    if op == "forward":
        s.forward(float(a.get("ms", 140)))
        return {"success": True}
    if op == "turn":
        s.turn_px(int(a.get("px", 0)))
        return {"success": True}
    if op == "explore":
        r = s.explore(a["view_box"], a["prompt_box"],
                      seconds=float(a.get("seconds", 20)),
                      verbose=True)
        return {"success": True, **r}
    return {"success": False, "error": f"未知 op：{op}"}


def tool_navigate(args: dict) -> dict:
    """M3：跑一段计划（goto/search/face/wait/key），只在卡住或达成时返回。"""
    from computer_mcp import navigator
    a = args or {}
    plan = a.get("plan") or a.get("goals") or []
    if not plan:
        return {"success": False, "error": "plan 不能为空"}
    s = _servo(a)
    sup = navigator.Supervisor(_world_state(a), s)
    r = sup.run(plan, max_seconds=float(a.get("max_seconds", 90)))
    return {"success": bool(r.get("ok")), **r}


# ══════════════════════════ 通用布局识别（v0.7）══════════════════════════
def tool_screen_layout(args: dict) -> dict:
    """通用布局：内容区 / HUD 文字行 / 网格面板 / 进度条。

    不需要任何应用常量 —— 全靠像素结构（周期性、长宽比、饱和度、行投影）。
    坐标同时给像素和归一化值（rel，相对内容区 0~1），窗口缩放不影响。
    """
    a = args or {}
    from computer_mcp import screen_model

    region = a.get("region")
    if region:
        img = _grab_region(region)
    else:
        hwnd = int(a.get("hwnd") or 0)
        if not hwnd:
            return {"success": False, "error": "需要 hwnd 或 region"}
        r = __import__("win32gui").GetWindowRect(hwnd)
        img = _grab_region([r[0], r[1], r[2] - r[0], r[3] - r[1]])
    if img is None:
        return {"success": False, "error": "抓取失败"}
    st = screen_model.state(img)
    st["success"] = True
    return st


def _auto_map_region(args: dict) -> list[int] | None:
    """用通用布局识别自动找小地图区域（优先 lattice，其次找最像的文本块）。"""
    from computer_mcp import screen_model
    import win32gui

    hwnd = int((args or {}).get("hwnd") or 0)
    if not hwnd:
        return None
    r = win32gui.GetWindowRect(hwnd)
    img = _grab_region([r[0], r[1], r[2] - r[0], r[3] - r[1]])
    if img is None:
        return None
    st = screen_model.state(img)
    lattices = st.get("lattices") or []
    if not lattices:
        return None
    best = max(lattices, key=lambda d: d["score"])
    ox, oy = r[0], r[1]
    x, y, w, h = best["box"]
    return [ox + x, oy + y, w, h]


# ══════════════════════════ 布局标定与记忆（v0.8）══════════════════════════
def _client_canvas(hwnd: int):
    """客户区作为"内容画布"：返回 (屏幕原点 x, y, 宽, 高)。"""
    import win32gui
    x, y = win32gui.ClientToScreen(hwnd, (0, 0))
    l, t, r, b = win32gui.GetClientRect(hwnd)
    return (x, y, r - l, b - t)


def tool_layout_mem(args: dict) -> dict:
    """布局档案：save / list / resolve / delete。

    坐标一律**归一化**（相对客户区 0~1）。窗口缩放后 resolve 会自动换算，
    所以同一个档案在任何窗口尺寸下都能用。
    """
    from computer_mcp import layout_mem
    import win32gui

    a = args or {}
    action = (a.get("action") or "list").lower()

    if action == "list":
        return {"success": True, **layout_mem.list_profiles()}

    if action == "delete":
        r = layout_mem.delete_profile(a.get("name") or "")
        return {"success": bool(r.get("ok")), **r}

    hwnd = int(a.get("hwnd") or 0)
    if not hwnd:
        return {"success": False, "error": "需要 hwnd"}

    title = win32gui.GetWindowText(hwnd)
    cx, cy, cw, ch = _client_canvas(hwnd)

    if action == "save":
        regions = a.get("regions") or {}
        r = layout_mem.save_profile(title, (cw, ch), regions, meta=a.get("meta"),
                                    name=a.get("name"))
        return {"success": bool(r.get("ok")), "title": title,
                "canvas": [cw, ch], **r}

    if action == "resolve":
        prof = layout_mem.find_profile(title, (cw, ch))
        if not prof:
            return {"success": False, "error": f"没有匹配的档案：{title!r}",
                    "canvas": [cw, ch]}
        boxes = layout_mem.resolve(prof, (cx, cy, cw, ch))
        return {"success": True, "title": title, "key": prof.get("stem"),
                "canvas": [cw, ch], "boxes": boxes}
    return {"success": False, "error": f"未知 action：{action}"}
