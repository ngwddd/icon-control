"""zones/sense_fallback.py — 统一寻址：UIA → OCR → 模板（P2-9）

为什么需要：我们的 UIA 只能看到"规规矩矩"的控件。微信 4.x、游戏、Electron
自绘界面在 UIA 里是空树 —— 实战里只能靠截图 + OCR。

这个模块把三条路合成一个入口，返回统一结构：
    {"ok": True, "query": ..., "source": "uia|ocr|template",
     "candidates": [{"x","y","w","h","cx","cy","source","label","score"}],
     "tried": ["uia","ocr","template"]}

设计原则：
  · **按顺序尝试，命中即返回**（省时间：UIA 最便宜，模板最贵）
  · 每条来源内部出错只记进 tried，不影响下一条
  · 不做点击，只做定位 —— 点击交给 click/ui_click，职责单一
"""

from __future__ import annotations

import time


def _norm_cand(raw: dict, source: str, score: float, label: str = "") -> dict:
    x = int(raw.get("x", 0) or 0)
    y = int(raw.get("y", 0) or 0)
    w = int(raw.get("w", 0) or 0)
    h = int(raw.get("h", 0) or 0)
    cx = int(raw.get("cx") or (x + w // 2))
    cy = int(raw.get("cy") or (y + h // 2))
    return {"x": x, "y": y, "w": w, "h": h, "cx": cx, "cy": cy,
            "source": source, "label": label or raw.get("name") or raw.get("text") or "",
            "score": round(float(score), 3)}


def _try_uia(query: str, hwnd, limit: int) -> list:
    from computer_mcp import ui_ext

    out = []
    res = ui_ext.ui_find(name=query, hwnd=hwnd, exact=False, index=0)
    for c in (res.get("candidates") or [])[:limit]:
        out.append(_norm_cand(c, "uia", 1.0))
    return out


def _try_ocr(query: str, region, hwnd, limit: int) -> list:
    from computer_mcp import ocr_ext

    out = []
    res = ocr_ext.find_text(query=query, region=region, hwnd=hwnd)
    for c in (res.get("hits") or res.get("matches") or [])[:limit]:
        out.append(_norm_cand(c, "ocr", c.get("ratio", 1.0)))
    return out


def _try_template(query: str, region, hwnd, limit: int) -> list:
    from computer_mcp import vision_state as vs

    res = vs.match_template(name=query, region=region, hwnd=hwnd)
    if not res.get("success") or not res.get("found"):
        return []
    center = res.get("center") or [0, 0]
    cand = {"x": res.get("x", 0), "y": res.get("y", 0),
            "w": res.get("w", 0), "h": res.get("h", 0),
            "cx": center[0], "cy": center[1]}
    return [_norm_cand(cand, "template", res.get("score", 0.0), label=query)]


def find_element(query: str, hwnd=None, region=None, limit: int = 5,
                 sources=("uia", "ocr", "template")) -> dict:
    """按顺序尝试多条来源，返回第一个有结果的。"""
    t0 = time.perf_counter()
    tried, errors = [], []
    for src in sources:
        tried.append(src)
        try:
            if src == "uia":
                cands = _try_uia(query, hwnd, limit)
            elif src == "ocr":
                cands = _try_ocr(query, region, hwnd, limit)
            elif src == "template":
                cands = _try_template(query, region, hwnd, limit)
            else:
                errors.append(f"{src}: 未知来源")
                continue
        except Exception as exc:                        # noqa: BLE001
            errors.append(f"{src}: {type(exc).__name__}: {exc}")
            continue
        if cands:
            return {"ok": True, "query": query, "source": src,
                    "candidates": cands[:limit], "tried": tried,
                    "errors": errors,
                    "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)}
    return {"ok": False, "query": query, "source": None, "candidates": [],
            "tried": tried, "errors": errors,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)}
