"""perceive.py — 感知原语（v0.4 架构第二层）

设计原则：**只回答结构化的小问题**，不做整屏 OCR。
    · "这块区域里有没有亮字"           → probe_prompt   （1~2 ms）
    · "这条进度条填了百分之多少"        → probe_bar      （1~2 ms）
    · "画面中央通不通"                 → probe_openness （1 ms）
    · "这个颜色的小块在哪"             → probe_color_blob
    · "数字是多少"                     → digits.read_digits（P2，模板匹配）

为什么不用 OCR：
    实测 Windows OCR 对一个像素字体 HUD 读出的是 "L E E L 1" / "5 韫 工 T Y ： 6E"，
    单次 120~180 ms。而"有没有提示""条有多满"这类问题用像素算 1~2 ms 就够，还更准。

所有函数的 box 都是图像坐标 (x, y, w, h)，调用方负责把屏幕坐标换算过来。
"""

from __future__ import annotations

import numpy as np

# 常用颜色的参考值（RGB）与默认容差
COLORS = {
    "green": (46, 160, 67),
    "yellow": (210, 180, 60),
    "red": (200, 60, 50),
    "cyan": (80, 200, 220),
    "white": (230, 230, 230),
    "orange": (230, 140, 60),
}


def norm_box(box) -> tuple[int, int, int, int]:
    """接受 (x,y,w,h) / (x,y,x2,y2) / dict，统一成 (x, y, w, h)。"""
    if isinstance(box, dict):
        x, y = int(box.get("x", 0)), int(box.get("y", 0))
        w = int(box.get("w", box.get("width", 0)))
        h = int(box.get("h", box.get("height", 0)))
        return x, y, max(1, w), max(1, h)
    x, y, a, b = (int(v) for v in box)
    # 用户多半给 w,h；如果 a>b 且看起来像 x2，就按 x2/y2 处理
    return x, y, max(1, a), max(1, b)


def crop(img: np.ndarray, box) -> np.ndarray:
    x, y, w, h = norm_box(box)
    hgt, wid = img.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(wid, x + w), min(hgt, y + h)
    if x1 <= x0 or y1 <= y0:
        return img[:0, :0]
    return img[y0:y1, x0:x1]


def _lum(c: np.ndarray) -> np.ndarray:
    return c.astype(np.float32).mean(axis=2)


def _color_mask(c: np.ndarray, rgb: tuple[int, int, int], tol: int) -> np.ndarray:
    d = np.abs(c.astype(np.int16) - np.array(rgb, dtype=np.int16))
    return (d.max(axis=2) <= tol)


# ────────────────────────────── 原语 ──────────────────────────────
def probe_prompt(img: np.ndarray, box, thr: int = 150, min_ratio: float = 0.004) -> dict:
    """这块区域里有没有"亮文字"（提示语）。

    实测：游戏底部提示区，有 HOLD E 时亮像素 1265 个（占 6%），没有时 0 个。
    所以判据用「亮像素占比」，不用 OCR。
    """
    c = crop(img, box)
    if c.size == 0:
        return {"hit": False, "count": 0, "ratio": 0.0, "confidence": 0.0}
    lum = _lum(c)
    mask = lum > thr
    count = int(mask.sum())
    ratio = count / float(mask.size)
    hit = ratio >= min_ratio
    # 置信度：占比越接近 1~15% 越像"一行文字"；纯白大块会掉置信度
    conf = 1.0 if hit and ratio <= 0.30 else (0.7 if hit else 0.0)
    return {"hit": bool(hit), "count": count, "ratio": round(ratio, 4),
            "confidence": round(conf, 2), "thr": thr}


def probe_bar(img: np.ndarray, box, color: str = "green", tol: int = 60,
              axis: str = "x") -> dict:
    """进度条填充比例：按列（或行）统计命中颜色像素，算"尾巴在哪"。

    比 OCR 稳：条没有文字，只有颜色。
    """
    rgb = COLORS.get(color, color if isinstance(color, tuple) else COLORS["green"])
    c = crop(img, box)
    if c.size == 0:
        return {"fill": 0.0, "found": 0, "confidence": 0.0}
    mask = _color_mask(c, rgb, tol)
    if axis == "x":
        cols = mask.mean(axis=0)
        hit_cols = np.where(cols > 0.25)[0]
        span = mask.shape[1]
    else:
        rows = mask.mean(axis=1)
        hit_cols = np.where(rows > 0.25)[0]
        span = mask.shape[0]
    if len(hit_cols) == 0:
        return {"fill": 0.0, "found": 0, "confidence": 0.0, "color": color}
    fill = float(hit_cols.max() + 1) / float(span)
    return {"fill": round(min(1.0, fill), 3), "found": int(len(hit_cols)),
            "confidence": round(min(1.0, len(hit_cols) / 4.0), 2), "color": color}


def probe_openness(img: np.ndarray, box) -> dict:
    """画面中央"通不通"：越开阔（通道深处）平均亮度越高、结构越简单。"""
    c = crop(img, box)
    if c.size == 0:
        return {"score": 0.0, "mean": 0.0, "std": 0.0}
    lum = _lum(c)
    mean = float(lum.mean())
    std = float(lum.std())
    # 开阔时：中等亮度、低方差；贴墙时：要么很暗要么满屏纹理（高方差）
    score = mean - 0.25 * std
    return {"score": round(score, 2), "mean": round(mean, 2), "std": round(std, 2)}


def probe_color_blob(img: np.ndarray, box, color: str = "green", tol: int = 60,
                     min_pixels: int = 12) -> dict:
    """某种颜色的连通块在哪（找光标、找目标点、找怪物血条）。"""
    rgb = COLORS.get(color, color if isinstance(color, tuple) else COLORS["green"])
    c = crop(img, box)
    if c.size == 0:
        return {"hit": False, "count": 0}
    mask = _color_mask(c, rgb, tol)
    count = int(mask.sum())
    if count < min_pixels:
        return {"hit": False, "count": count}
    ys, xs = np.where(mask)
    x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())
    ox, oy = norm_box(box)[:2]
    return {"hit": True, "count": count,
            "bbox": (ox + x0, oy + y0, x1 - x0 + 1, y1 - y0 + 1),
            "center": (ox + (x0 + x1) // 2, oy + (y0 + y1) // 2)}


def diff_region(a: np.ndarray, b: np.ndarray, box=None) -> dict:
    """两帧在指定区域的差异（给"这一步有没有生效"用）。"""
    if a is None or b is None:
        return {"mean": 0.0, "changed": False}
    if a.shape != b.shape:
        return {"mean": 255.0, "changed": True, "reason": "shape mismatch"}
    ca = crop(a, box) if box else a
    cb = crop(b, box) if box else b
    if ca.size == 0:
        return {"mean": 0.0, "changed": False}
    d = np.abs(cb.astype(np.float32) - ca.astype(np.float32)).mean()
    return {"mean": round(float(d), 2), "changed": bool(d > 1.2)}


def probe(kind: str, img: np.ndarray, box=None, **kw) -> dict:
    """统一入口，方便工具层直接转发。"""
    if kind in ("prompt", "text_bright"):
        return probe_prompt(img, box, **kw)
    if kind in ("bar", "progress"):
        return probe_bar(img, box, **kw)
    if kind in ("openness", "open"):
        return probe_openness(img, box)
    if kind in ("color", "blob", "color_blob"):
        return probe_color_blob(img, box, **kw)
    if kind in ("digits", "number"):
        from computer_mcp import digits as _digits
        return _digits.read_digits(img, box, **kw)
    return {"error": f"未知 probe kind: {kind}",
            "supported": ["prompt", "bar", "openness", "color", "digits"]}


def locate_rows(img: np.ndarray, box=None, color: str = "cyan", tol: int = 70,
                min_px: int = 6, gap: int = 4) -> list[dict]:
    """在区域里按颜色找"文字行"（HUD），返回每行的 y 范围与 x 范围。

    为什么需要：窗口大小/位置会变（实测 806x640 变成 537x427），
    硬编码坐标必然失效。颜色扫描一次 1~2 ms，比 OCR 定位快两个数量级。
    """
    rgb = COLORS.get(color, color if isinstance(color, tuple) else COLORS["cyan"])
    c = crop(img, box)
    if c.size == 0:
        return []
    mask = _color_mask(c, rgb, tol)
    if mask.sum() == 0:
        return []
    rows = np.where(mask.sum(axis=1) >= min_px)[0]
    if len(rows) == 0:
        return []
    groups, start, prev = [], rows[0], rows[0]
    for y in rows[1:]:
        if y - prev > gap:
            groups.append((start, prev))
            start = y
        prev = y
    groups.append((start, prev))
    ox, oy = norm_box(box)[:2] if box is not None else (0, 0)
    out = []
    for (y0, y1) in groups:
        sub = mask[y0:y1 + 1]
        xs = np.where(sub.sum(axis=0) > 0)[0]
        if len(xs) == 0:
            continue
        out.append({"y0": int(oy + y0), "y1": int(oy + y1),
                    "x0": int(ox + xs.min()), "x1": int(ox + xs.max()),
                    "box": (int(ox + xs.min()), int(oy + y0),
                            int(xs.max() - xs.min() + 1), int(y1 - y0 + 1))})
    return out
