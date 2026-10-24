"""vision_state.py — 通用视觉状态判据（给自绘 UI / 游戏 / Electron 这类 UIA 瞎眼的目标用）

来源：2026-10-25 打恐怖生存游戏（***）那一轮踩出来的通用需求。**不含任何游戏专属逻辑**，
只做四件任何"看不清控件"的界面都需要的事：

  ① **模板自学**：`capture_template(name, region)` 把屏幕上一块图案存成模板，
     `match_template(name)` 用灰度模板匹配找它 —— 不需要 OCR，不需要 UIA，
     自绘 UI（Electron/CEF/游戏）也能稳定判断"某个东西在不在"。
  ② **基线差异**：`set_baseline(name, region)` 记下一块区域的"正常样子"，
     `diff_baseline(name)` 返回它现在偏离多少（0~255）——
     比"我觉得变了"可靠，且比全屏 diff 精准。
  ③ **稳定采样**：`sample_stable(region)` 连采两次，两次一致才算数 ——
     防"动画还没走完就判状态"（这个坑在游戏里让我反复开关同一个开关）。
  ④ **悬停探针**：`hover_probe(x, y, region)` 悬停 → 等 → 比较 → 移开，
     专门对付"鼠标移上去才出现"的菜单/按钮（很多客户端和游戏都是这样）。

另外带一个轻量的**运行统计**（`stats()`）：调用数、失败数、重试数、耗时，
用来在长流程里盯"体检指标"——指标长期不动就是坏了，别硬跑完。

存储位置：
    <工具目录>/vision/templates/<name>.png   + <name>.json（记录来源区域/尺寸/时间）
    <工具目录>/vision/baselines/<name>.png   + <name>.json

坐标约定：所有返回的 x/y 都是**屏幕绝对坐标**；传 region 时是 {x,y,w,h}。
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any

import cv2
import numpy as np
from PIL import Image

try:                                   # 复用 OCR 模块里的抓图（含 PrintWindow 被遮挡也能抓）
    from computer_mcp import ocr_ext
except Exception:                      # pragma: no cover
    ocr_ext = None                     # type: ignore

HERE = os.path.dirname(os.path.abspath(__file__))
# 默认存到**工具根目录**下的 vision/（不要放进 venv，重装依赖会连模板一起丢）
STORE = os.environ.get("对话壳（***）_VISION_STORE") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE)))), "vision")
TPL_DIR = os.path.join(STORE, "templates")
BAS_DIR = os.path.join(STORE, "baselines")

_STATS: dict[str, Any] = {
    "started": time.time(),
    "calls": 0,
    "failures": 0,
    "retries": 0,
    "by_op": {},
}


# ---------------------------------------------------------------- 基础工具
def _ensure_dirs() -> None:
    os.makedirs(TPL_DIR, exist_ok=True)
    os.makedirs(BAS_DIR, exist_ok=True)


def _bump(op: str, ok: bool = True, retry: bool = False) -> None:
    _STATS["calls"] = int(_STATS["calls"]) + 1
    if not ok:
        _STATS["failures"] = int(_STATS["failures"]) + 1
    if retry:
        _STATS["retries"] = int(_STATS["retries"]) + 1
    per = _STATS["by_op"].setdefault(op, {"n": 0, "fail": 0})
    per["n"] += 1
    if not ok:
        per["fail"] += 1


def stats(reset: bool = False) -> dict:
    """运行统计：调用数 / 失败数 / 重试数 / 各操作分布 / 运行时长。"""
    out = {
        "elapsed_s": round(time.time() - float(_STATS["started"]), 1),
        "calls": _STATS["calls"],
        "failures": _STATS["failures"],
        "retries": _STATS["retries"],
        "by_op": dict(_STATS["by_op"]),
        "failure_rate": round(_STATS["failures"] / max(1, _STATS["calls"]), 3),
    }
    if reset:
        _STATS.update({"started": time.time(), "calls": 0, "failures": 0, "retries": 0, "by_op": {}})
    return out


def _gray(region: dict[str, int] | None = None, hwnd: int | None = None) -> np.ndarray:
    """抓图并转灰度。有 hwnd 时优先抓窗口自己的位图（被遮挡也能用）。

    注意 `ocr_ext._grab` 返回 (image, origin_x, origin_y)：
      · 带 hwnd 时给的是**整个窗口**的位图（origin 是窗口左上角）
      · 不带 hwnd 时给的是**已经裁好的 region**
    两种情况都要把结果对齐到 region，否则模板和基线会错位。
    """
    img = None
    ox = oy = 0
    if ocr_ext is not None:
        img, ox, oy = ocr_ext._grab(hwnd=hwnd, region=(region if not hwnd else None))
    if img is None:                    # pragma: no cover
        import mss
        with mss.mss() as sct:
            box = region or {"x": 0, "y": 0, "w": 1920, "h": 1080}
            shot = sct.grab({"left": box["x"], "top": box["y"],
                             "width": box["w"], "height": box["h"]})
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        ox, oy = (region or {}).get("x", 0), (region or {}).get("y", 0)

    if region:
        left = max(0, int(region["x"]) - int(ox))
        top = max(0, int(region["y"]) - int(oy))
        right = min(img.width, left + int(region["w"]))
        bottom = min(img.height, top + int(region["h"]))
        if right > left and bottom > top and (left, top, right, bottom) != (0, 0, img.width, img.height):
            img = img.crop((left, top, right, bottom))

    if img.mode != "RGB":
        img = img.convert("RGB")
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)


def _norm_region(region: Any) -> dict[str, int] | None:
    if not region:
        return None
    if isinstance(region, dict):
        return {"x": int(region.get("x", 0)), "y": int(region.get("y", 0)),
                "w": int(region.get("w", region.get("width", 0))),
                "h": int(region.get("h", region.get("height", 0)))}
    if isinstance(region, (list, tuple)) and len(region) == 4:
        return {"x": int(region[0]), "y": int(region[1]), "w": int(region[2]), "h": int(region[3])}
    return None


def _safe_name(name: str) -> str:
    bad = '<>:"/\\|?*'
    out = "".join("_" if c in bad else c for c in str(name)).strip()
    if not out:
        raise ValueError("name 不能为空")
    return out


# ---------------------------------------------------------------- ① 模板
def capture_template(name: str, region: Any = None, hwnd: int | None = None,
                     overwrite: bool = True) -> dict:
    """把屏幕上的一块区域存成模板，之后用 match_template 找它。

    region 建议**只框住那个图案本身**（不要带整块背景），匹配会稳很多。
    """
    op = "capture_template"
    try:
        nm = _safe_name(name)
        reg = _norm_region(region)
        if reg is None:
            _bump(op, False)
            return {"success": False, "error": "必须给 region（x,y,w,h）"}
        _ensure_dirs()
        path = os.path.join(TPL_DIR, f"{nm}.png")
        if os.path.exists(path) and not overwrite:
            _bump(op, False)
            return {"success": False, "error": f"模板 {nm} 已存在（overwrite=false）"}

        g = _gray(reg, hwnd)
        if g.size == 0 or g.shape[0] < 3 or g.shape[1] < 3:
            _bump(op, False)
            return {"success": False, "error": "抓到的区域太小或为空"}
        std = float(g.std())
        if std < 3.0:
            _bump(op, False)
            return {"success": False, "error": f"该区域几乎没有细节（std={std:.1f}），不适合当模板"}

        cv2.imwrite(path, g)
        meta = {"name": nm, "region": reg, "hwnd": hwnd, "size": [int(g.shape[1]), int(g.shape[0])],
                "std": round(std, 2), "created": time.strftime("%Y-%m-%d %H:%M:%S")}
        with open(os.path.join(TPL_DIR, f"{nm}.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)
        _bump(op)
        return {"success": True, "action": op, **meta, "path": path}
    except Exception as exc:
        _bump(op, False)
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


def _load_template(name: str) -> tuple[np.ndarray | None, dict]:
    nm = _safe_name(name)
    p = os.path.join(TPL_DIR, f"{nm}.png")
    if not os.path.isfile(p):
        return None, {}
    tpl = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
    meta = {}
    mp = os.path.join(TPL_DIR, f"{nm}.json")
    if os.path.isfile(mp):
        try:
            meta = json.load(open(mp, encoding="utf-8"))
        except Exception:
            meta = {}
    return tpl, meta


def match_template(name: str, region: Any = None, hwnd: int | None = None,
                   confidence: float = 0.8) -> dict:
    """在屏幕（或指定区域/窗口）里找模板，返回是否命中、置信度、屏幕绝对坐标。"""
    op = "match_template"
    try:
        tpl, meta = _load_template(name)
        if tpl is None:
            _bump(op, False)
            return {"success": False, "error": f"没有模板 {name}，先用 capture_template 存一个"}
        reg = _norm_region(region)
        g = _gray(reg, hwnd)
        if g.shape[0] < tpl.shape[0] or g.shape[1] < tpl.shape[1]:
            _bump(op, False)
            return {"success": False, "error": "搜索区域比模板还小"}
        r = cv2.matchTemplate(g, tpl, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(r)
        ox = reg["x"] if reg else 0
        oy = reg["y"] if reg else 0
        found = float(mx) >= float(confidence)
        _bump(op, True)
        return {
            "success": True, "action": op, "name": name, "found": found,
            "score": round(float(mx), 4), "confidence": confidence,
            "x": int(ox + loc[0]), "y": int(oy + loc[1]),
            "w": int(tpl.shape[1]), "h": int(tpl.shape[0]),
            "center": [int(ox + loc[0] + tpl.shape[1] / 2), int(oy + loc[1] + tpl.shape[0] / 2)],
        }
    except Exception as exc:
        _bump(op, False)
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


def wait_template(name: str, timeout_ms: int = 5000, poll_ms: int = 120,
                  appear: bool = True, confidence: float = 0.8,
                  region: Any = None, hwnd: int | None = None) -> dict:
    """等模板出现（appear=True）或消失（appear=False）。事件驱动，比模型轮询省。"""
    op = "wait_template"
    t0 = time.time()
    last = 0.0
    tries = 0
    while (time.time() - t0) * 1000 < timeout_ms:
        tries += 1
        r = match_template(name, region=region, hwnd=hwnd, confidence=confidence)
        if r.get("success"):
            last = r.get("score", 0.0)
            if bool(r.get("found")) == bool(appear):
                _bump(op, True)
                return {"success": True, "action": op, "matched": True,
                        "elapsed_ms": int((time.time() - t0) * 1000), "tries": tries,
                        "score": last, "target_appear": appear, "where": r}
        time.sleep(max(30, poll_ms) / 1000.0)
    _bump(op, False)
    return {"success": True, "action": op, "matched": False,
            "elapsed_ms": int((time.time() - t0) * 1000), "tries": tries,
            "score": last, "target_appear": appear}


def click_template(name: str, mouse: Any = None, button: str = "left",
                   confidence: float = 0.8, region: Any = None, hwnd: int | None = None,
                   settle_ms: int = 150, offset: Any = None) -> dict:
    """找到模板位置并点它的中心（offset 可给 [dx,dy] 微调）。"""
    op = "click_template"
    r = match_template(name, region=region, hwnd=hwnd, confidence=confidence)
    if not r.get("success") or not r.get("found"):
        _bump(op, False)
        return {"success": False, "error": "没找到模板", "match": r}
    cx, cy = r["center"]
    if offset:
        cx += int(offset[0]); cy += int(offset[1])
    if mouse is None:
        from pynput.mouse import Button as MB, Controller as MC
        mouse = MC()
        _btn = MB.left
    else:
        from pynput.mouse import Button as MB
        _btn = {"left": MB.left, "right": MB.right, "middle": MB.middle}.get(button, MB.left)
    mouse.position = (int(cx), int(cy))
    time.sleep(0.04)
    mouse.press(_btn)
    time.sleep(0.06)
    mouse.release(_btn)
    if settle_ms:
        time.sleep(settle_ms / 1000.0)
    _bump(op, True)
    return {"success": True, "action": op, "name": name, "clicked": [int(cx), int(cy)],
            "score": r.get("score")}


def list_templates() -> dict:
    _ensure_dirs()
    items = []
    for f in sorted(os.listdir(TPL_DIR)):
        if not f.endswith(".png"):
            continue
        nm = f[:-4]
        _, meta = _load_template(nm)
        items.append(meta or {"name": nm})
    bases = [f[:-4] for f in sorted(os.listdir(BAS_DIR)) if f.endswith(".png")]
    return {"success": True, "templates": items, "baselines": bases, "store": STORE}


def delete_template(name: str) -> dict:
    nm = _safe_name(name)
    removed = []
    for p in (os.path.join(TPL_DIR, f"{nm}.png"), os.path.join(TPL_DIR, f"{nm}.json")):
        if os.path.isfile(p):
            os.remove(p); removed.append(os.path.basename(p))
    return {"success": bool(removed), "removed": removed}


# ---------------------------------------------------------------- ② 基线
def set_baseline(name: str, region: Any = None, hwnd: int | None = None) -> dict:
    """记下一块区域"正常的样子"，之后用 diff_baseline 看它偏离多少。"""
    op = "set_baseline"
    try:
        nm = _safe_name(name)
        reg = _norm_region(region)
        if reg is None:
            _bump(op, False)
            return {"success": False, "error": "必须给 region（x,y,w,h）"}
        _ensure_dirs()
        g = _gray(reg, hwnd)
        path = os.path.join(BAS_DIR, f"{nm}.png")
        cv2.imwrite(path, g)
        meta = {"name": nm, "region": reg, "hwnd": hwnd, "size": [int(g.shape[1]), int(g.shape[0])],
                "created": time.strftime("%Y-%m-%d %H:%M:%S"), "mean": round(float(g.mean()), 2)}
        with open(os.path.join(BAS_DIR, f"{nm}.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)
        _bump(op)
        return {"success": True, "action": op, **meta, "path": path}
    except Exception as exc:
        _bump(op, False)
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


def diff_baseline(name: str, region: Any = None, hwnd: int | None = None,
                  threshold: float = 8.0) -> dict:
    """返回当前画面与基线的平均绝对差（0~255）；changed = diff >= threshold。"""
    op = "diff_baseline"
    try:
        nm = _safe_name(name)
        p = os.path.join(BAS_DIR, f"{nm}.png")
        if not os.path.isfile(p):
            _bump(op, False)
            return {"success": False, "error": f"没有基线 {name}，先用 set_baseline 设一个"}
        base = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
        meta_p = os.path.join(BAS_DIR, f"{nm}.json")
        reg = _norm_region(region)
        if reg is None and os.path.isfile(meta_p):
            try:
                reg = _norm_region(json.load(open(meta_p, encoding="utf-8")).get("region"))
            except Exception:
                reg = None
        cur = _gray(reg, hwnd)
        if cur.shape != base.shape:
            if cur.shape[0] < base.shape[0] or cur.shape[1] < base.shape[1]:
                _bump(op, False)
                return {"success": False,
                        "error": f"区域尺寸不一致：基线 {base.shape[::-1]}，当前 {cur.shape[::-1]}"}
            cur = cur[:base.shape[0], :base.shape[1]]
        d = float(np.abs(cur.astype(np.int16) - base.astype(np.int16)).mean())
        _bump(op, True)
        return {"success": True, "action": op, "name": name, "diff": round(d, 2),
                "changed": d >= float(threshold), "threshold": float(threshold)}
    except Exception as exc:
        _bump(op, False)
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


def wait_baseline_change(name: str, threshold: float = 8.0, timeout_ms: int = 5000,
                        poll_ms: int = 120, region: Any = None, hwnd: int | None = None) -> dict:
    """等这块区域"变化超过阈值"（或直到超时）。"""
    op = "wait_baseline_change"
    t0 = time.time()
    last = 0.0
    while (time.time() - t0) * 1000 < timeout_ms:
        r = diff_baseline(name, region=region, hwnd=hwnd, threshold=threshold)
        if r.get("success"):
            last = r.get("diff", 0.0)
            if r.get("changed"):
                _bump(op, True)
                return {"success": True, "action": op, "changed": True, "diff": last,
                        "elapsed_ms": int((time.time() - t0) * 1000)}
        time.sleep(max(30, poll_ms) / 1000.0)
    _bump(op, False)
    return {"success": True, "action": op, "changed": False, "diff": last,
            "elapsed_ms": int((time.time() - t0) * 1000)}


# ---------------------------------------------------------------- ③ 稳定采样
def sample_stable(region: Any = None, hwnd: int | None = None,
                  times: int = 2, gap_ms: int = 200) -> dict:
    """连采多次，全部一致才算 stable。用来防"动画没走完就判状态"。"""
    op = "sample_stable"
    try:
        times = max(2, min(6, int(times)))
        hashes: list[str] = []
        means: list[float] = []
        for i in range(times):
            g = _gray(_norm_region(region), hwnd)
            hashes.append(hashlib.md5(g.tobytes()).hexdigest()[:12])
            means.append(round(float(g.mean()), 1))
            if i < times - 1:
                time.sleep(max(20, gap_ms) / 1000.0)
        stable = len(set(hashes)) == 1
        _bump(op, True)
        return {"success": True, "action": op, "stable": stable, "hash": hashes[-1],
                "hashes": hashes, "means": means, "times": times, "gap_ms": gap_ms}
    except Exception as exc:
        _bump(op, False)
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------- ④ 悬停探针
def hover_probe(x: int, y: int, region: Any = None, hwnd: int | None = None,
                dwell_ms: int = 400, away: Any = None, mouse: Any = None,
                threshold: float = 3.0) -> dict:
    """悬停到 (x,y) → 等 dwell_ms → 比较该区域是否变化 → 移开（away 可指定退开点）。

    专门对付"鼠标移上去才出现的菜单/按钮"：很多客户端和游戏是这样，
    单靠点击或截图都发现不了。
    """
    op = "hover_probe"
    try:
        if mouse is None:
            from pynput.mouse import Controller as MC
            mouse = MC()
        reg = _norm_region(region)
        if reg is None:
            return {"success": False, "error": "必须给 region（观察哪一块区域的变化）"}
        before = _gray(reg, hwnd)
        orig = tuple(mouse.position)
        mouse.position = (int(x), int(y))
        time.sleep(max(30, dwell_ms) / 1000.0)
        after = _gray(reg, hwnd)
        d = float(np.abs(after.astype(np.int16) - before.astype(np.int16)).mean())
        if away:
            mouse.position = (int(away[0]), int(away[1]))
        else:
            mouse.position = orig
        time.sleep(0.05)
        changed = d >= float(threshold)
        _bump(op, True)
        return {"success": True, "action": op, "hovered": [int(x), int(y)],
                "diff": round(d, 2), "revealed": changed, "threshold": float(threshold),
                "restored_to": list(away) if away else list(orig)}
    except Exception as exc:
        _bump(op, False)
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
