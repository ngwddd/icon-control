"""anchor_mem.py — a learned anchor memory for UI elements.

Why
---
Every task currently re-derives where things are (full-screen OCR, or hard-coded
coordinates). Both are wrong in different ways: OCR costs 100-800ms per look,
hard-coded absolute coordinates break the moment the window moves and fail
*silently*.

What is stored per (app, element)
---------------------------------
1. normalised position      x_ratio = (abs_x - rect_x) / rect_w
                            y_ratio = (abs_y - rect_y) / rect_h
   plus corner offsets      dx_right = rect_w - (abs_x - rect_x)
                            dy_bottom = rect_h - (abs_y - rect_y)
   -> survives resizing and moving; the corner form survives proportional
      layout changes better than the ratio form
2. a visual fingerprint     average-hash (64 bit) of a small patch around the
                            anchor, so a lookup can *verify* it is still looking
                            at the same widget instead of clicking blindly
3. usage counters           hits / misses / last_ok / updated, with a layout
                            signature (aspect ratio + DPI scale) so a stale entry
                            from another layout mode is not trusted

Lookup order (fast -> safe)
---------------------------
    cached position -> patch hash match?  -> click          (3-5 ms)
    hash mismatch   -> fall back to OCR by text             (100-800 ms)
    OCR hit         -> click and *re-learn* from the result

The module is import-light (ctypes/PIL/mss only) and stores plain JSON at
~/.dsh/tools/desktop-mcp/memory/anchors.json
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

MEM_DIR = os.environ.get(
    "DESK_MEMORY_DIR",
    os.path.join(os.path.expanduser("~"), ".dsh", "tools", "desktop-mcp", "memory"),
)
STORE = os.path.join(MEM_DIR, "anchors.json")

PATCH_W = 60
PATCH_H = 26
HASH_THRESHOLD = 10
SOFT_THRESHOLD = 30
MAX_PROTOTYPES = 6          # hamming distance (of 64 bits) that still counts as a match


# --------------------------------------------------------------------------- #
# storage
# --------------------------------------------------------------------------- #
def _now() -> str:
    """本地时间戳（记忆库里只用来排序和排查，不参与判定）。"""
    return time.strftime("%Y-%m-%d %H:%M:%S")


_CACHE: dict[str, Any] = {"mtime": None, "data": {}}


def _load() -> dict[str, Any]:
    """Read the anchor store, re-parsing only when the file changed."""
    try:
        mtime = os.path.getmtime(STORE)
    except OSError:
        return {}
    if _CACHE["mtime"] == mtime:
        return _CACHE["data"]
    try:
        with open(STORE, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            _CACHE["mtime"] = mtime
            _CACHE["data"] = data
            return data
    except Exception:
        pass
    return _CACHE["data"] or {}


def _save(data: dict[str, Any]) -> None:
    os.makedirs(MEM_DIR, exist_ok=True)
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, STORE)


def list_all() -> dict[str, Any]:
    data = _load()
    out = []
    for app, items in data.items():
        for key, rec in (items or {}).items():
            out.append({
                "app": app, "key": key,
                "npos": rec.get("npos"), "corner": rec.get("corner"),
                "hits": rec.get("hits", 0), "misses": rec.get("misses", 0),
                "layout": rec.get("layout"), "updated": rec.get("updated"),
            })
    return {"ok": True, "store": STORE, "count": len(out), "anchors": out}


def forget(app: str, key: str | None = None) -> dict[str, Any]:
    data = _load()
    if app not in data:
        return {"ok": False, "error": f"app {app!r} 不在记忆里"}
    if key:
        if key not in data[app]:
            return {"ok": False, "error": f"{app}/{key} 不在记忆里"}
        data[app].pop(key)
        _save(data)
        return {"ok": True, "forgot": f"{app}/{key}"}
    data.pop(app)
    _save(data)
    return {"ok": True, "forgot_app": app}


# --------------------------------------------------------------------------- #
# geometry / visual fingerprint
# --------------------------------------------------------------------------- #
def _geometry(hwnd: int) -> dict[str, int]:
    import win32gui

    wr = win32gui.GetWindowRect(hwnd)
    return {"x": int(wr[0]), "y": int(wr[1]),
            "w": max(1, int(wr[2] - wr[0])), "h": max(1, int(wr[3] - wr[1]))}


def layout_signature(hwnd: int) -> dict[str, Any]:
    import ctypes

    g = _geometry(hwnd)
    try:
        dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
    except Exception:
        dpi = 96
    return {
        "aspect": round(g["w"] / g["h"], 2),
        "scale": round((dpi or 96) / 96, 2),
        "w": g["w"], "h": g["h"],
    }


_LOCAL = __import__("threading").local()


def _sct():
    """One mss instance per thread — re-creating it costs a few ms per call."""
    import mss

    inst = getattr(_LOCAL, "sct", None)
    if inst is None:
        inst = mss.mss()
        _LOCAL.sct = inst
    return inst


def _grab(x: int, y: int, w: int, h: int):
    from PIL import Image

    shot = _sct().grab({"left": int(x), "top": int(y), "width": int(w), "height": int(h)})
    return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX").convert("L")


def ahash(img, size: int = 8) -> str:
    """Average hash: 64 bits, robust to tiny rendering shifts."""
    small = img.resize((size, size))
    px = list(small.getdata())
    avg = sum(px) / len(px)
    bits = "".join("1" if p >= avg else "0" for p in px)
    return "%016x" % int(bits, 2)


def hamming(a: str, b: str) -> int:
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except Exception:
        return 64


def _patch_hash(abs_x: int, abs_y: int, pw: int = PATCH_W, ph: int = PATCH_H) -> str | None:
    x = int(abs_x - pw // 2)
    y = int(abs_y - ph // 2)
    if x < 0 or y < 0:
        return None
    try:
        return ahash(_grab(x, y, pw, ph))
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# learn / locate / verify
# --------------------------------------------------------------------------- #
def learn(app: str, key: str, hwnd: int, abs_x: int, abs_y: int,
          note: str = "") -> dict[str, Any]:
    g = _geometry(hwnd)
    if not (g["x"] <= abs_x <= g["x"] + g["w"] and g["y"] <= abs_y <= g["y"] + g["h"]):
        return {"ok": False, "error": "坐标不在窗口矩形内，拒绝学习",
                "window": g, "point": [abs_x, abs_y]}
    data = _load()
    rec = data.setdefault(app, {}).setdefault(key, {})
    hits = rec.get("hits", 0)
    cur = _patch_hash(abs_x, abs_y)
    protos = list(rec.get("prototypes") or ([] if not rec.get("patch") else [rec["patch"]]))
    if cur:
        # 与已有原型足够像就不重复存；否则追加（外观随状态变：空/有字/悬停）
        if not any(hamming(cur, old_h) <= 8 for old_h in protos):
            protos.append(cur)
            protos = protos[-MAX_PROTOTYPES:]
    rec.update({
        "npos": {"x": round((abs_x - g["x"]) / g["w"], 5),
                 "y": round((abs_y - g["y"]) / g["h"], 5)},
        "corner": {"dx_right": g["x"] + g["w"] - abs_x,
                   "dy_bottom": g["y"] + g["h"] - abs_y},
        "prototypes": protos,
        "patch": cur or rec.get("patch"),
        "layout": layout_signature(hwnd),
        "last_point": [int(abs_x), int(abs_y)],
        "hits": hits + 1,
        "misses": rec.get("misses", 0),
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "note": note,
    })
    _save(data)
    return {"ok": True, "app": app, "key": key, "stored": rec}


def locate(app: str, key: str, hwnd: int) -> dict[str, Any] | None:
    """Turn the stored representation back into an absolute point for this window."""
    data = _load()
    rec = (data.get(app) or {}).get(key)
    if not rec:
        return None
    g = _geometry(hwnd)
    # 优先用「右下角偏移」：按比例布局变化时它更稳
    dxr = (rec.get("corner") or {}).get("dx_right")
    dyb = (rec.get("corner") or {}).get("dy_bottom")
    if dxr is not None and dyb is not None:
        x, y = g["x"] + g["w"] - dxr, g["y"] + g["h"] - dyb
    else:
        npos = rec.get("npos") or {}
        x = g["x"] + npos.get("x", 0) * g["w"]
        y = g["y"] + npos.get("y", 0) * g["h"]
    x, y = int(round(x)), int(round(y))
    same_layout = rec.get("layout", {}).get("aspect") == layout_signature(hwnd)["aspect"]
    return {"x": x, "y": y, "patch": rec.get("patch"),
            "prototypes": rec.get("prototypes") or ([rec["patch"]] if rec.get("patch") else []),
            "hits": rec.get("hits", 0), "misses": rec.get("misses", 0),
            "same_layout": same_layout, "updated": rec.get("updated")}


def verify(app: str, key: str, hwnd: int, max_dist: int = HASH_THRESHOLD) -> dict[str, Any]:
    """Is the stored widget still where we think it is?"""
    loc = locate(app, key, hwnd)
    if not loc:
        return {"ok": False, "reason": "no_memory", "app": app, "key": key}
    if not loc.get("same_layout"):
        return {"ok": False, "reason": "layout_changed", "at": [loc["x"], loc["y"]]}
    cur = _patch_hash(loc["x"], loc["y"])
    protos = loc.get("prototypes") or ([loc["patch"]] if loc.get("patch") else [])
    if cur is None or not protos:
        return {"ok": False, "reason": "hash_unavailable", "at": [loc["x"], loc["y"]]}
    dist = min(hamming(cur, h) for h in protos if h)
    return {"ok": dist <= max_dist, "reason": "hash", "at": [loc["x"], loc["y"]],
            "distance": dist, "threshold": max_dist,
            "prototypes": len(protos), "soft_ok": dist <= SOFT_THRESHOLD}


def confirm(app: str, key: str, success: bool) -> dict[str, Any]:
    data = _load()
    rec = (data.get(app) or {}).get(key)
    if not rec:
        return {"ok": False, "error": "no_memory"}
    if success:
        rec["hits"] = rec.get("hits", 0) + 1
        rec["last_ok"] = time.strftime("%Y-%m-%d %H:%M:%S")
    else:
        rec["misses"] = rec.get("misses", 0) + 1
    _save(data)
    return {"ok": True, "hits": rec.get("hits", 0), "misses": rec.get("misses", 0)}



# --------------------------------------------------------------------------- #
# P2：区域与列表项记忆（2026-10-25）
#
# 点记忆只能记住"一个坐标"；列表类界面（ChatClient聊天列表、ChatClient 联系人、工坊卡片）
# 更需要「第 N 项在哪」和「一块区域在哪」。这里用「归一化位置 + 右下角偏移」
# 两条冗余线索，窗口缩放跟移动都能算回来。
# --------------------------------------------------------------------------- #
def _norm_pos(x: int, y: int, geo: dict[str, Any]) -> dict[str, float]:
    return {"x": round((x - geo["x"]) / max(1, geo["w"]), 5),
            "y": round((y - geo["y"]) / max(1, geo["h"]), 5)}


def _from_norm(npos: dict[str, float], geo: dict[str, Any]) -> tuple[int, int]:
    return (int(geo["x"] + npos["x"] * geo["w"]),
            int(geo["y"] + npos["y"] * geo["h"]))


def _resolve_from_corner(entry: dict[str, Any], geo: dict[str, Any]) -> tuple[int, int]:
    c = entry.get("corner") or {}
    if "dx_right" in c and "dy_bottom" in c:
        return (int(geo["x"] + geo["w"] - c["dx_right"]),
                int(geo["y"] + geo["h"] - c["dy_bottom"]))
    return _from_norm(entry.get("npos") or {"x": 0, "y": 0}, geo)


def learn_region(app: str, key: str, hwnd: int, x: int, y: int, w: int, h: int,
                 note: str = "") -> dict[str, Any]:
    """记一块矩形区域（例如"聊天消息区""输入框"）。"""
    geo = _geometry(hwnd)
    if not geo:
        return {"ok": False, "error": "cannot read window geometry"}
    if x < geo["x"] or y < geo["y"] or x + w > geo["x"] + geo["w"] or y + h > geo["y"] + geo["h"]:
        return {"ok": False, "error": "region is outside the window rect",
                "region": [x, y, w, h], "window": geo}

    data = _load()
    node = data.setdefault(app, {})
    entry = node.setdefault(f"{key}", {})
    entry.update({
        "kind": "region",
        "npos": _norm_pos(x, y, geo),
        "nsize": {"w": round(w / max(1, geo["w"]), 5), "h": round(h / max(1, geo["h"]), 5)},
        "corner": {"dx_right": int(geo["x"] + geo["w"] - x),
                   "dy_bottom": int(geo["y"] + geo["h"] - y)},
        "size": {"w": int(w), "h": int(h)},
        "layout": layout_signature(hwnd),
        "note": note,
        "hits": int(entry.get("hits", 0)),
        "misses": int(entry.get("misses", 0)),
        "learned_at": _now(),
    })
    _save(data)
    return {"ok": True, "app": app, "key": key, "region": [x, y, w, h], "layout": entry["layout"]}


def locate_region(app: str, key: str, hwnd: int) -> dict[str, Any]:
    """按当前窗口几何把区域算回来（窗口缩放/移动都跟得上）。"""
    data = _load()
    entry = (data.get(app) or {}).get(key)
    if not entry or entry.get("kind") != "region":
        return {"ok": False, "reason": "not_learned"}
    geo = _geometry(hwnd)
    if not geo:
        return {"ok": False, "reason": "no_geometry"}

    x, y = _resolve_from_corner(entry, geo)
    size = entry.get("size") or {}
    if "nsize" in entry and entry.get("layout") != layout_signature(hwnd):
        w = int(round(entry["nsize"]["w"] * geo["w"]))
        h = int(round(entry["nsize"]["h"] * geo["h"]))
    else:
        w, h = int(size.get("w", 0)), int(size.get("h", 0))

    # 越界保护：夹到窗口内
    x = max(geo["x"], min(x, geo["x"] + geo["w"] - 1))
    y = max(geo["y"], min(y, geo["y"] + geo["h"] - 1))
    w = max(1, min(w, geo["x"] + geo["w"] - x))
    h = max(1, min(h, geo["y"] + geo["h"] - y))
    return {"ok": True, "region": {"x": x, "y": y, "w": w, "h": h},
            "same_layout": entry.get("layout") == layout_signature(hwnd)}


def learn_item(app: str, key: str, hwnd: int, index: int, x: int, y: int,
               note: str = "") -> dict[str, Any]:
    """记「列表第 index 项」的位置（index 从 0 起）。"""
    geo = _geometry(hwnd)
    if not geo:
        return {"ok": False, "error": "cannot read window geometry"}
    if not (geo["x"] <= x <= geo["x"] + geo["w"] and geo["y"] <= y <= geo["y"] + geo["h"]):
        return {"ok": False, "error": "point is outside the window rect", "point": [x, y]}

    data = _load()
    node = data.setdefault(app, {})
    entry = node.setdefault(key, {})
    if entry.get("kind") != "item":
        entry.clear()
    items = entry.setdefault("items", {})
    idx = str(int(index))
    items[idx] = {"npos": _norm_pos(x, y, geo),
                  "corner": {"dx_right": int(geo["x"] + geo["w"] - x),
                             "dy_bottom": int(geo["y"] + geo["h"] - y)}}
    entry.update({
        "kind": "item",
        "layout": layout_signature(hwnd),
        "note": note,
        "hits": int(entry.get("hits", 0)),
        "misses": int(entry.get("misses", 0)),
        "learned_at": _now(),
    })
    # 相邻两项的垂直间距（用于推算未记录的位置）
    if len(items) >= 2:
        ys = sorted(int(k) for k in items)
        gaps = []
        for a, b in zip(ys, ys[1:]):
            pa = _from_norm(items[str(a)]["npos"], geo)
            pb = _from_norm(items[str(b)]["npos"], geo)
            if b - a > 0:
                gaps.append((pb[1] - pa[1]) / (b - a))
        if gaps:
            entry["row_h"] = round(sum(gaps) / len(gaps), 1)
    _save(data)
    return {"ok": True, "app": app, "key": key, "index": int(index),
            "items": len(items), "row_h": entry.get("row_h")}


def locate_item(app: str, key: str, hwnd: int, index: int) -> dict[str, Any]:
    """取「列表第 index 项」的坐标；没记过的项用最近的已记项 + 行高推算。"""
    data = _load()
    entry = (data.get(app) or {}).get(key)
    if not entry or entry.get("kind") != "item":
        return {"ok": False, "reason": "not_learned"}
    geo = _geometry(hwnd)
    if not geo:
        return {"ok": False, "reason": "no_geometry"}

    items = entry.get("items") or {}
    idx = str(int(index))
    if idx in items:
        x, y = _resolve_from_corner(items[idx], geo)
        return {"ok": True, "at": (x, y), "exact": True}

    known = sorted(int(k) for k in items)
    if not known:
        return {"ok": False, "reason": "no_items"}
    nearest = min(known, key=lambda k: abs(k - int(index)))
    x, y = _resolve_from_corner(items[str(nearest)], geo)
    row_h = entry.get("row_h")
    if row_h:
        y = int(y + (int(index) - nearest) * row_h)
        return {"ok": True, "at": (x, y), "exact": False, "based_on": nearest, "row_h": row_h}
    return {"ok": True, "at": (x, y), "exact": False, "based_on": nearest}

def stats(app: str | None = None) -> dict[str, Any]:
    data = _load()
    apps = [app] if app else list(data)
    out = {}
    for a in apps:
        items = data.get(a) or {}
        out[a] = {"elements": len(items),
                  "hits": sum(v.get("hits", 0) for v in items.values()),
                  "misses": sum(v.get("misses", 0) for v in items.values())}
    return {"ok": True, "stats": out, "store": STORE}
