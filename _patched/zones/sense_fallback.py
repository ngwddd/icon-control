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
    out = {"x": x, "y": y, "w": w, "h": h, "cx": cx, "cy": cy,
           "source": source, "label": label or raw.get("name") or raw.get("text") or "",
           "score": round(float(score), 3)}
    # The UIA child-index path is what makes a reference re-resolvable; dropping
    # it here silently demoted every fused candidate to a 5 second visual ref.
    for key in ("path", "name", "type", "element_id", "automation_id", "hwnd"):
        if raw.get(key):
            out[key] = raw[key]
    return out


def _uia_confidence(query: str, name: str) -> float:
    """Name match quality. Calibrated per source: never mixed with OCR ratios."""
    q, n = query.casefold().strip(), (name or "").casefold().strip()
    if not n:
        return 0.0
    if n == q:
        return 0.95
    if n.startswith(q):
        return 0.85
    if q in n:
        return 0.7
    return 0.5


def _try_uia(query: str, hwnd, limit: int) -> list:
    from computer_mcp import ui_ext

    out = []
    res = ui_ext.ui_find(name=query, hwnd=hwnd, exact=False, index=0)
    for c in (res.get("candidates") or [])[:limit]:
        out.append(_norm_cand(c, "uia", _uia_confidence(query, c.get("name", ""))))
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


CONFIDENT = 0.85          # one candidate at this level ends the search
AMBIGUITY_MARGIN = 0.1    # two candidates this close are indistinguishable


def _run_source(src: str, query: str, hwnd, region, limit: int) -> list:
    if src == "uia":
        return _try_uia(query, hwnd, limit)
    if src == "ocr":
        return _try_ocr(query, region, hwnd, limit)
    if src == "template":
        return _try_template(query, region, hwnd, limit)
    raise ValueError(f"未知来源: {src}")


def _rank(cands: list) -> list:
    """Sort by confidence, then favour the smaller control on a tie.

    A big pane that happens to carry the label is rarely the thing you meant to
    click; the button inside it is. (This used to sort by descending area.)
    """
    return sorted(cands, key=lambda c: (-c["score"], c["w"] * c["h"]))


def find_element(query: str, hwnd=None, region=None, limit: int = 5,
                 sources=("uia", "ocr", "template"),
                 min_confidence: float = 0.0,
                 fuse: bool = True) -> dict:
    """Locate a target, fusing sources when the first answer is not clear-cut.

    The v1.4.0 behaviour — stop at the first source that returns anything — was
    both wasteful (it never compared) and unsafe (the first hit may be the wrong
    of two identical buttons). Now the cheap source runs first; OCR and template
    are only consulted when UIA is missing or ambiguous, and the result says
    whether the target is unambiguous.
    """
    t0 = time.perf_counter()
    if hwnd is None and "uia" in sources:
        # Resolve the window once so candidates can carry a re-resolvable path
        # and a snapshot reference even when the caller only passed a query.
        try:
            import win32gui
            hwnd = int(win32gui.GetForegroundWindow()) or None
        except Exception:                               # noqa: BLE001
            hwnd = None
    tried, errors, collected = [], [], []
    for src in sources:
        tried.append(src)
        try:
            collected.extend(_run_source(src, query, hwnd, region, limit))
        except Exception as exc:                        # noqa: BLE001
            errors.append(f"{src}: {type(exc).__name__}: {exc}")
            continue
        if not fuse:
            if collected:
                break
            continue
        ranked = _rank(collected)
        # Fast path: a single confident hit from the cheapest source is enough.
        if ranked and ranked[0]["score"] >= CONFIDENT and len(ranked) == 1:
            break
    collected = [c for c in collected if c["score"] >= min_confidence]
    ranked = _rank(collected)
    ambiguous = False
    if len(ranked) >= 2 and ranked[0]["score"] - ranked[1]["score"] < AMBIGUITY_MARGIN:
        same_spot = abs(ranked[0]["cx"] - ranked[1]["cx"]) < 4 and abs(ranked[0]["cy"] - ranked[1]["cy"]) < 4
        ambiguous = not same_spot
    snapshot = {}
    if hwnd and ranked:
        try:
            from computer_mcp import snapshots
            snapshot = snapshots.attach(hwnd, ranked[:limit])
            ranked = snapshot.pop('candidates')
        except Exception as exc:                        # noqa: BLE001
            errors.append('snapshot: ' + str(exc))
    if not ranked:
        return {"ok": False, "query": query, "source": None, "candidates": [],
                "ambiguous": False, "tried": tried, "errors": errors,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)}
    return {"ok": True, "query": query, "source": ranked[0]["source"],
            "target": ranked[0], "ambiguous": ambiguous,
            "confidence": ranked[0]["score"],
            **snapshot, "candidates": ranked[:limit], "tried": tried, "errors": errors,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)}
