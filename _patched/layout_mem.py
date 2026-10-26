"""layout_mem.py — 布局标定与记忆（通用流程，不绑任何应用）

设计立场（用户 2026-10-27）：
    「我要改的是通用的……我要提升自己的综合能力，不是专项化能力。」
    「我就喜欢搞这种革命性的，而不是按着一个架构一直改。」

所以这里**不猜布局**。做法是：
    ① 人对着一张截图看一次，报出 4 个区域的**归一化坐标**（0~1，相对内容区）
    ② 存下来，键 = 应用名（标题去掉版本号）+ 内容区尺寸
    ③ 之后窗口怎么缩放/移动，代码按归一化自动换算 → 每次 0 成本
    ④ 换应用 = 再看一次（2 分钟），而不是"再写一套常量"

为什么这比"自动识别"强（已实测，不是观点）：
    · 纯像素启发式在真实画面上四项全错（内容区/文字行/网格/进度条）
    · 而"看一眼"这件事本来就该由模型/人做，它是**一次性的**
    · 代码只负责复用 —— 那是确定性工作

数据格式（~/.dsh/tools/desktop-mcp/state/layouts.json）：
    {
      "canity": {
        "stem": "canity",                  # 标题去掉版本号
        "canvas": [806, 640],              # 标定时的内容区尺寸
        "regions": {                        # 归一化 0~1，相对内容区
          "map":    [0.66, 0.55, 0.34, 0.42],
          "prompt": [0.31, 0.73, 0.36, 0.09],
          "bar":    [0.16, 0.82, 0.24, 0.04],
          "hud":    [0.02, 0.05, 0.30, 0.20]
        },
        "meta": {"pitch": 11, "note": "..."},
        "saved": 1700000000.0
      }
    }
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

STORE = Path.home() / ".dsh" / "tools" / "desktop-mcp" / "state" / "layouts.json"

# 标题里的版本号/数字去掉，让 "Canity v1.6.5" 与 "Canity v1.6.6" 命中同一个档案
_VER_RE = re.compile(r"\b(v|ver|version)?\s*\d+(\.\d+)*\b", re.I)


def stem(title: str) -> str:
    """把窗口标题压成"应用名"：去版本号、去多余空格。"""
    t = (title or "").strip()
    t = _VER_RE.sub(" ", t)
    t = re.sub(r"[^\w\u4e00-\u9fff]+", " ", t).strip().lower()
    return t or "unknown"


# ══════════════════════════ 存储 ══════════════════════════
def _load() -> dict:
    try:
        with open(STORE, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    tmp.replace(STORE)


# ══════════════════════════ 校验 ══════════════════════════
def validate_regions(regions: dict) -> tuple[dict, list[str]]:
    """归一化区域检查：必须是 [x,y,w,h]，全在 0~1，且 w/h > 0。"""
    out, errs = {}, []
    for name, box in (regions or {}).items():
        try:
            x, y, w, h = (float(v) for v in box)
        except Exception:
            errs.append(f"{name}: 不是 4 个数")
            continue
        if w <= 0 or h <= 0:
            errs.append(f"{name}: 宽高必须为正")
            continue
        if not (-0.02 <= x <= 1.02 and -0.02 <= y <= 1.02):
            errs.append(f"{name}: x/y 超出 0~1")
            continue
        if x + w > 1.05 or y + h > 1.05:
            errs.append(f"{name}: 右下角超出内容区")
            continue
        out[name] = [round(max(0.0, x), 4), round(max(0.0, y), 4),
                     round(min(1.0, w), 4), round(min(1.0, h), 4)]
    return out, errs


# ══════════════════════════ 读写档案 ══════════════════════════
def save_profile(title: str, canvas: tuple[int, int], regions: dict,
                 meta: dict | None = None, name: str | None = None) -> dict:
    regs, errs = validate_regions(regions)
    if errs:
        return {"ok": False, "errors": errs}
    if not regs:
        return {"ok": False, "errors": ["regions 不能为空"]}
    if not canvas or canvas[0] <= 0 or canvas[1] <= 0:
        return {"ok": False, "errors": ["canvas 尺寸无效"]}
    key = name or stem(title)
    data = _load()
    data[key] = {"stem": stem(title), "title": title,
                 "canvas": [int(canvas[0]), int(canvas[1])],
                 "regions": regs, "meta": meta or {},
                 "saved": time.time()}
    _save(data)
    return {"ok": True, "key": key, "regions": regs, "store": str(STORE)}


def delete_profile(name: str) -> dict:
    data = _load()
    key = name if name in data else stem(name)
    if key in data:
        data.pop(key)
        _save(data)
        return {"ok": True, "deleted": key}
    return {"ok": False, "error": f"没有这个档案：{name}"}


def list_profiles() -> dict:
    data = _load()
    return {"count": len(data), "store": str(STORE),
            "items": [{"key": k, "title": v.get("title"), "canvas": v.get("canvas"),
                       "regions": sorted((v.get("regions") or {}).keys()),
                       "saved": v.get("saved")} for k, v in data.items()]}


def find_profile(title: str, canvas: tuple[int, int] | None = None,
                 tol: float = 0.25) -> dict | None:
    """找最匹配的档案。

    匹配规则：
        ① 应用名（去版本号）完全一致 → 命中
        ② 没有完全一致的，就看内容区**宽高比**是否接近（±tol），
           且应用名有公共词 —— 用来兜住"标题里带文件名/状态"的情况
    """
    data = _load()
    s = stem(title)
    if s in data:
        return data[s]
    best, best_score = None, 0.0
    for k, v in data.items():
        vs = v.get("stem") or k
        # 名字相似度：公共词比例
        a, b = set(s.split()), set(vs.split())
        if not a or not b:
            continue
        overlap = len(a & b) / max(1, len(a | b))
        score = overlap
        if canvas and v.get("canvas"):
            ar_now = canvas[0] / max(1, canvas[1])
            ar_old = v["canvas"][0] / max(1, v["canvas"][1])
            if abs(ar_now - ar_old) / ar_old > tol:
                score *= 0.5
        if score > best_score:
            best, best_score = v, score
    return best if best_score >= 0.5 else None


# ══════════════════════════ 解析成像素 ══════════════════════════
def resolve(profile: dict, canvas_box: tuple[int, int, int, int]) -> dict:
    """把归一化区域换算成当前窗口上的像素框。

    canvas_box = 当前客户区 (x, y, w, h)（屏幕坐标）。

    两种缩放模式（存在 meta.scale_mode 里）：
        "fixed"（默认）  程序以**固定尺寸**绘制，贴在客户区左上角（游戏常见）。
                         → 用档案里的 canvas 尺寸，客户端更大也只按它算。
        "fit"           程序随窗口拉伸（编辑器/浏览器）。
                         → 用当前客户区尺寸。
    早先一律按客户区算，遇到"固定画布 + 大窗口"就整体偏移（实测过）。
    """
    cx, cy, cw, ch = canvas_box
    pw, ph = (profile.get("canvas") or [cw, ch])[:2]
    mode = ((profile.get("meta") or {}).get("scale_mode") or "fixed").lower()
    if mode == "fit":
        uw, uh = max(1, cw), max(1, ch)
    else:
        # 固定画布：**直接用档案尺寸**，不按客户区裁剪。
        # 客户区比画布小的时候，超出部分被窗口自然裁掉；
        # 按客户区缩一下会整体位移（实测 800x600 的客户区里 806x640 画布，
        # HUD 差 2~3px，越靠右下越明显）。
        uw, uh = max(1, int(pw)), max(1, int(ph))
    out = {}
    for name, (rx, ry, rw, rh) in ((profile.get("regions") or {}).items()):
        out[name] = [int(round(cx + rx * uw)), int(round(cy + ry * uh)),
                     max(1, int(round(rw * uw))), max(1, int(round(rh * uh)))]
    out["_canvas"] = [int(cx), int(cy), int(uw), int(uh)]
    return out


def describe(profile: dict) -> str:
    r = profile.get("regions") or {}
    rows = [f"{k:8} rel={v}" for k, v in sorted(r.items())]
    return f"{profile.get('title')}  canvas={profile.get('canvas')}\n" + "\n".join(rows)
