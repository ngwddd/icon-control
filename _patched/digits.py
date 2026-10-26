"""digits.py — 数字识别（模板匹配版，v0.4 / P2）

为什么自己写：
    Windows OCR 对像素字体 HUD 读出的是 "5 韫 工 T Y ： 6E"（SANITY 99），
    单次 120~180 ms，且不可校正。而 HUD 数字只有 0-9，
    用「切字 → 归一化成 5×7 → 比汉明距离」1~3 ms 就能到 99%+。

两套模板：
    1. 内置标准 5×7 数字（够读大多数像素字体）
    2. 运行时学习：learn(label, img, box) 把当前字形存进 vision store，
       下次优先用学到的（字体怪异时用它救场）

用法：
    from computer_mcp import digits
    digits.read_digits(img, (x, y, w, h))            # → {"text": "99", ...}
    digits.learn("9", img, {…单字形区域…})            # 教它一个字形
"""

from __future__ import annotations

import json
import os

import numpy as np

STORE = os.path.join(os.path.expanduser("~"), ".dsh", "tools", "desktop-mcp",
                     "vision", "glyphs.json")

GW, GH = 5, 7                      # 归一化网格

# 标准 5×7 点阵（# = 有墨）
_FONT = {
    "0": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00110", "01000", "10000", "11111"],
    "3": ["11111", "00010", "00100", "00010", "00001", "10001", "01110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
}


def _bitmap(rows: list[str]) -> np.ndarray:
    return np.array([[1 if ch in "#1" else 0 for ch in row] for row in rows], dtype=np.uint8)


BUILTIN = {ch: _bitmap(rows) for ch, rows in _FONT.items()}


def _load_learned() -> dict[str, np.ndarray]:
    try:
        with open(STORE, encoding="utf-8") as fh:
            raw = json.load(fh)
        out = {}
        for label, bits in raw.items():
            arr = np.array(bits, dtype=np.uint8)
            if arr.shape == (GH, GW):
                out[str(label)] = arr
        return out
    except Exception:
        return {}


def _save_learned(table: dict[str, np.ndarray]) -> None:
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    data = {k: v.astype(int).tolist() for k, v in table.items()}
    with open(STORE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)


def normalize_glyph(mask: np.ndarray) -> np.ndarray:
    """任意大小的字形 → 5×7 二值网格（按面积平均后过阈值）。"""
    h, w = mask.shape[:2]
    if h == 0 or w == 0:
        return np.zeros((GH, GW), dtype=np.uint8)
    ys = np.linspace(0, h, GH + 1).astype(int)
    xs = np.linspace(0, w, GW + 1).astype(int)
    out = np.zeros((GH, GW), dtype=np.float32)
    for r in range(GH):
        y0, y1 = ys[r], max(ys[r] + 1, ys[r + 1])
        for c in range(GW):
            x0, x1 = xs[c], max(xs[c] + 1, xs[c + 1])
            cell = mask[y0:y1, x0:x1]
            out[r, c] = cell.mean() if cell.size else 0.0
    return (out > 0.35).astype(np.uint8)


def split_glyphs(mask: np.ndarray, gap: int = 1) -> list[tuple[int, int]]:
    """按列投影切成字符块，返回 [(x0, x1), ...]。"""
    if mask.size == 0:
        return []
    cols = mask.any(axis=0)
    blocks, start = [], None
    blank = 0
    for i, on in enumerate(cols):
        if on:
            if start is None:
                start = i
            blank = 0
        else:
            if start is not None:
                blank += 1
                if blank >= gap:
                    blocks.append((start, i - blank + 1))
                    start = None
                    blank = 0
    if start is not None:
        blocks.append((start, len(cols)))
    return [b for b in blocks if b[1] > b[0]]


def match(glyph: np.ndarray, table: dict[str, np.ndarray]) -> tuple[str, float]:
    best, best_score = "?", 0.0
    total = GH * GW
    for label, tpl in table.items():
        dist = int(np.abs(glyph.astype(np.int16) - tpl.astype(np.int16)).sum())
        score = 1.0 - dist / total
        if score > best_score:
            best, best_score = label, score
    return best, round(best_score, 3)


def read_digits(img: np.ndarray, box=None, thr: int = 140, min_conf: float = 0.55,
                gap: int = 1) -> dict:
    """读一块区域里的数字串。返回 text / 每个字形的置信度 / 整体置信度。"""
    from computer_mcp import perceive

    c = perceive.crop(img, box) if box is not None else img
    if c.size == 0:
        return {"text": "", "digits": [], "confidence": 0.0, "reason": "empty"}
    lum = c.astype(np.float32).mean(axis=2)
    mask = lum > thr
    if mask.sum() < 4:
        return {"text": "", "digits": [], "confidence": 0.0, "reason": "no ink"}

    blocks = split_glyphs(mask, gap=gap)
    if not blocks:
        return {"text": "", "digits": [], "confidence": 0.0, "reason": "no glyph"}

    table = {**BUILTIN, **_load_learned()}
    out, confs = [], []
    for (x0, x1) in blocks:
        sub = mask[:, x0:x1]
        rows = np.where(sub.any(axis=1))[0]
        if len(rows) == 0:
            continue
        sub = sub[rows.min():rows.max() + 1, :]
        g = normalize_glyph(sub)
        ch, conf = match(g, table)
        if conf < min_conf:
            out.append("?")
            confs.append(conf)
        else:
            out.append(ch)
            confs.append(conf)
    text = "".join(out)
    return {"text": text, "digits": out,
            "confidence": round(float(np.mean(confs)) if confs else 0.0, 3),
            "glyphs": len(out), "blocks": len(blocks)}


def learn(label: str, img: np.ndarray, box=None, thr: int = 140) -> dict:
    """教它一个字形（label 是"看到的是什么字"，例如 "9"）。"""
    from computer_mcp import perceive

    c = perceive.crop(img, box) if box is not None else img
    if c.size == 0:
        return {"ok": False, "error": "空区域"}
    lum = c.astype(np.float32).mean(axis=2)
    mask = lum > thr
    if mask.sum() < 3:
        return {"ok": False, "error": "这一块没有亮像素，选个字形区域再教"}
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    sub = mask[rows.min():rows.max() + 1, cols.min():cols.max() + 1]
    g = normalize_glyph(sub)
    table = _load_learned()
    table[str(label)] = g
    _save_learned(table)
    return {"ok": True, "label": str(label), "learned_total": len(table),
            "store": STORE, "grid": g.astype(int).tolist()}


def clear_learned() -> dict:
    try:
        if os.path.isfile(STORE):
            os.remove(STORE)
        return {"ok": True, "cleared": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def learned() -> dict:
    t = _load_learned()
    return {"count": len(t), "labels": sorted(t), "store": STORE}
