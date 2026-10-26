"""screen_model.py — 通用屏幕布局自动识别（**实验性：真实画面还没跑通**）

⚠️ 现状（2026-10-27 实测 3 张真实截图）：
    内容区 / HUD 文字行 / 网格面板 / 进度条 —— 四项在真实游戏画面上都还会判错。
    合成图上的单测是绿的，但那只能证明"结构判据自洽"。
    所以 `world_state(auto=true)` 默认关闭；可靠的路子是"一次性标定 + 记忆"，
    见 AGENTS.md 的「布局标定与记忆」一节。

原始目标（未变）

为什么要有这一层（用户 2026-10-27 的原话）：
    「我要改的是通用的。我的目的是为了让这个读取速度变快……
      我要提升自己的综合能力，不是专项化能力。」

之前的做法是我给游戏手填一堆坐标：
    map_region=[534,357,270,265]、prompt_box=[250,470,300,50]、canvas=806x640 …
换个游戏、窗口一改大小，全部失效 —— 这是专项化，不值钱。

这一层只回答四个**通用**问题，全部靠像素结构：
    ① `content_box`   这块窗口里，真正的"画面"是哪一块？（处理黑边/信箱）
    ② `find_text_rows` 哪些是"HUD 文字行"？（彩色/高亮的细横条）
    ③ `find_lattice`  哪里是"网格面板"（任意游戏的小地图/雷达/棋盘）？
    ④ `find_bars`     哪几根是"进度条"（细长的纯色矩形）？

然后 `state(img)` 把这些拼成一份**归一化**布局（坐标相对 content_box 的 0~1），
下游（WorldState/Servo）拿归一化坐标就能用，窗口缩放不影响。

设计原则：
    · 只用 numpy，不引入新依赖
    · 每个探测器都可以单独调用、单独测试（合成图上验证）
    · 判据是"结构性"的：周期性、长宽比、饱和度、行投影，而不是具体颜色值
"""

from __future__ import annotations

import numpy as np

# ── 通用阈值（与具体应用无关）──
DARK_MAX = 18          # 低于这个亮度算"黑边"
MIN_CONTENT = 0.15     # 内容至少占窗口这个比例，否则认为判错了


def _lum(img: np.ndarray) -> np.ndarray:
    return img.astype(np.float32).mean(axis=2)


def _sat(img: np.ndarray) -> np.ndarray:
    """饱和度（max-min）/max —— 用来把"HUD 彩色文字"从灰墙里分出来。"""
    f = img.astype(np.float32)
    mx = f.max(axis=2)
    mn = f.min(axis=2)
    return np.where(mx > 1, (mx - mn) / np.maximum(mx, 1), 0.0)


# ══════════════════════════ ① 内容区 ══════════════════════════
def content_box(img: np.ndarray) -> tuple[int, int, int, int]:
    """找出"真正的画面"矩形（去黑边 / 信箱 letterbox）。

    判据取**并集**，缺一个都会漏：
        ① 与背景色的亮度差  —— 平色内容（编辑器、菜单）靠这个
        ② 局部纹理方差      —— 很暗但带噪点的游戏画面靠这个
    只用①：暗色游戏画面会被判成黑边；只用②：平色内容会被判成黑边（都实测过）。
    """
    if img is None or img.size == 0:
        return (0, 0, 0, 0)
    H, W = img.shape[:2]
    g = img.astype(np.float32).mean(axis=2)
    hist = np.bincount(g.astype(np.uint8).ravel(), minlength=256)
    bg = int(np.argmax(hist))
    bright = g > bg + 8

    b = 8
    hh, ww = (H // b) * b, (W // b) * b
    textured = np.zeros((H, W), dtype=bool)
    if hh and ww:
        blocks = g[:hh, :ww].reshape(hh // b, b, ww // b, b)
        std = blocks.std(axis=(1, 3))
        tex_blocks = std > 2.0
        big = np.repeat(np.repeat(tex_blocks, b, axis=0), b, axis=1)
        textured[:hh, :ww] = big

    mask = bright | textured
    rows = np.where(mask.sum(axis=1) >= 2)[0]
    cols = np.where(mask.sum(axis=0) >= 2)[0]
    if len(rows) < 4 or len(cols) < 4:
        return (0, 0, W, H)
    # 块级判据只有 8px 粒度（纹理块会往外扩最多 8px），
    # 所以用**亮度 mask** 精修边界；亮度不足时再退回块级结果。
    refine = bright if bright.sum() > 0.02 * H * W else mask
    row_ok = refine.sum(axis=1) >= 2
    col_ok = refine.sum(axis=0) >= 2
    y0 = next((y for y in range(max(0, int(rows.min()) - 8), min(H, int(rows.min()) + 9)) if row_ok[y]), int(rows.min()))
    y1 = next((y for y in range(min(H - 1, int(rows.max()) + 8), max(-1, int(rows.max()) - 9), -1) if row_ok[y]), int(rows.max()))
    x0 = next((x for x in range(max(0, int(cols.min()) - 8), min(W, int(cols.min()) + 9)) if col_ok[x]), int(cols.min()))
    x1 = next((x for x in range(min(W - 1, int(cols.max()) + 8), max(-1, int(cols.max()) - 9), -1) if col_ok[x]), int(cols.max()))
    if (x1 - x0 + 1) * (y1 - y0 + 1) < 0.15 * W * H:
        return (0, 0, W, H)
    return (x0, y0, x1 - x0 + 1, y1 - y0 + 1)


# ══════════════════════════ ② HUD 文字行 ══════════════════════════
def find_text_rows(img: np.ndarray, box=None, min_px: int = 6,
                   sat_min: float = 0.35, lum_min: int = 150,
                   gap: int = 3, min_h: int = 6, max_h: int = 40,
                   max_w_frac: float = 0.85) -> list[dict]:
    """找出"HUD 文字行"：高饱和/高亮 + **形状像一行字**。

    只看颜色会把整张图连成一行（实测过）。真正的文字行有三个附加特征：
        ① 高度在 6~40 px 之间（字高）
        ② 宽度不会占满整窗（< max_w_frac）
        ③ 行内边缘密度高（有字的轮廓），且行上下是背景
    """
    if img is None or img.size == 0:
        return []
    x0o, y0o = 0, 0
    if box is not None:
        x, y, w, h = box
        img = img[y:y + h, x:x + w]
        x0o, y0o = x, y
    H, W = img.shape[:2]
    sat = _sat(img)
    lum = _lum(img)
    mask = (sat > sat_min) | (lum > lum_min)
    if not mask.any():
        return []

    edge = np.zeros((H, W), dtype=bool)
    g = lum
    edge[:, 1:] |= np.abs(np.diff(g, axis=1)) > 25
    edge[1:, :] |= np.abs(np.diff(g, axis=0)) > 25

    prof = mask.sum(axis=1)
    rows = np.where(prof >= min_px)[0]
    if len(rows) == 0:
        return []
    groups, start, prev = [], rows[0], rows[0]
    for y in rows[1:]:
        if y - prev > gap:
            groups.append((start, prev))
            start = y
        prev = y
    groups.append((start, prev))

    out = []
    for (a, b) in groups:
        h = b - a + 1
        if h < min_h or h > max_h:          # 太高 → 不是一行字
            continue
        sub = mask[a:b + 1]
        xs = np.where(sub.sum(axis=0) > 0)[0]
        if len(xs) < 6:
            continue
        w = int(xs.max() - xs.min() + 1)
        if w > max_w_frac * W:              # 太宽 → 是场景/整行背景
            continue
        # 行内要有足够多的"字边缘"
        if edge[a:b + 1, xs.min():xs.max() + 1].mean() < 0.02:
            continue
        out.append({"box": (x0o + int(xs.min()), y0o + a, w, h),
                    "y0": y0o + a, "y1": y0o + b})
    return out


# ══════════════════════════ ③ 网格面板（小地图/雷达） ══════════════════════════
def _period(profile: np.ndarray, lo: int = 4, hi: int = 40) -> float | None:
    """用自相关找一维剖面的主周期。返回 None 表示没找到明显周期。"""
    v = profile.astype(np.float32)
    v = v - v.mean()
    if not np.any(v):
        return None
    ac = np.correlate(v, v, mode="full")[len(v) - 1:]
    if ac[0] <= 0:
        return None
    ac = ac / ac[0]
    best, best_p = 0.0, None
    for p in range(lo, min(hi, len(ac))):
        if ac[p] > best:
            best, best_p = float(ac[p]), p
    if best_p is None or best < 0.25:
        return None
    return float(best_p)


def _runs_of(mask_row: np.ndarray, min_len: int) -> list[tuple[int, int]]:
    """返回这一行里长度 >= min_len 的连续 True 段 [(start, length), ...]。"""
    out = []
    idx = np.where(mask_row)[0]
    if len(idx) == 0:
        return out
    start = prev = idx[0]
    for v in idx[1:]:
        if v - prev > 1:
            if prev - start + 1 >= min_len:
                out.append((int(start), int(prev - start + 1)))
            start = v
        prev = v
    if prev - start + 1 >= min_len:
        out.append((int(start), int(prev - start + 1)))
    return out


def find_lattice(img: np.ndarray, box=None, min_cells: int = 3,
                 flat_max: float = 12.0) -> list[dict]:
    """找出"网格面板"：小地图 / 雷达 / 棋盘。

    两步：
        ① 周期 + 范围：边缘图的行列投影，用自相关求 pitch
        ② **格内平色过滤**：UI 面板的格子内部是平色（方差小），
           墙面纹理是噪声（方差大）。只看①会把墙面当面板（实测误报 17px 假面板）。
    """
    if img is None or img.size == 0:
        return []
    x0o, y0o = 0, 0
    if box is not None:
        x, y, w, h = box
        img = img[y:y + h, x:x + w]
        x0o, y0o = x, y
    g = _lum(img)
    H, W = g.shape
    edge = np.zeros((H, W), dtype=bool)
    edge[:, 1:] |= np.abs(np.diff(g, axis=1)) > 12
    edge[1:, :] |= np.abs(np.diff(g, axis=0)) > 12
    if edge.sum() < 40:
        return []

    px = _period(edge.sum(axis=0))
    py = _period(edge.sum(axis=1))
    pitch = px or py
    if not pitch or pitch < 4:
        return []

    def extent(prof):
        idx = np.where(prof > 0)[0]
        return (int(idx.min()), int(idx.max())) if len(idx) else (0, 0)

    cx0, cx1 = extent(edge.sum(axis=0))
    cy0, cy1 = extent(edge.sum(axis=1))
    w, h = cx1 - cx0 + 1, cy1 - cy0 + 1
    if w < pitch * min_cells or h < pitch * min_cells:
        return []

    # 格内平色检查：在候选框里按 pitch 取格心 3x3，算方差中位数
    sub = g[cy0:cy1 + 1, cx0:cx1 + 1]
    stds = []
    yy = int(pitch // 2)
    while yy + 2 < sub.shape[0]:
        xx = int(pitch // 2)
        while xx + 2 < sub.shape[1]:
            stds.append(float(sub[yy:yy + 3, xx:xx + 3].std()))
            xx += int(pitch)
        yy += int(pitch)
    if not stds:
        return []
    med = float(np.median(stds))
    if med > flat_max:                 # 格内是噪声 → 墙面纹理，不是 UI 面板
        return []

    return [{"box": (x0o + cx0, y0o + cy0, w, h),
             "pitch": round(float(pitch), 2),
             "cells": [int(w // pitch), int(h // pitch)],
             "flat": round(med, 1),
             "score": round(min(1.0, (1.0 - med / flat_max) * 0.5 + 0.5), 3)}]


# ══════════════════════════ ④ 进度条 ══════════════════════════
def find_bars(img: np.ndarray, box=None, min_ratio: float = 6.0,
              max_h: int = 26, sat_min: float = 0.30,
              flat_std: float = 10.0) -> list[dict]:
    """找出进度条：**平色**（内部方差低）+ 细长 + 两端锐利。

    只看"细长高饱和"会把抗锯齿的 1px 噪线当成条（实测抓到整宽 1px）。
    真进度条内部是纯色（列方向方差极小），且高度 4~26 px。
    """
    if img is None or img.size == 0:
        return []
    x0o, y0o = 0, 0
    if box is not None:
        x, y, w, h = box
        img = img[y:y + h, x:x + w]
        x0o, y0o = x, y
    sat = _sat(img)
    lum = _lum(img)
    mask = (sat > sat_min) & (lum > 40)
    if mask.sum() < 20:
        return []

    prof = mask.sum(axis=1)
    rows = np.where(prof >= 6)[0]
    if len(rows) == 0:
        return []
    groups, start, prev = [], rows[0], rows[0]
    for y in rows[1:]:
        if y - prev > 2:
            groups.append((start, prev))
            start = y
        prev = y
    groups.append((start, prev))

    q = (img // 8 * 8).reshape(-1, 3)
    bg = np.median(q, axis=0)
    track = (np.abs(img.astype(np.float32) - bg).max(axis=2) > 10)

    out = []
    for (a, b) in groups:
        h = b - a + 1
        if h < 4 or h > max_h:
            continue
        band = img[a:b + 1]
        # 平色检查：每条列的颜色在竖直方向的标准差
        col_std = band.astype(np.float32).std(axis=0).mean(axis=-1)
        sub_fill = mask[a:b + 1]
        sub_track = track[a:b + 1]
        xs = np.where(sub_track.sum(axis=0) > 0)[0]
        if len(xs) < 24:
            continue
        x0i, x1i = int(xs.min()), int(xs.max())
        w = x1i - x0i + 1
        if w / max(1, h) < min_ratio:
            continue
        # 条内部应当是平色（取其中位数，避免边缘影响）
        if float(np.median(col_std[x0i:x1i + 1])) > flat_std:
            continue
        cols = sub_fill[:, x0i:x1i + 1].mean(axis=0)
        filled = int((cols > 0.4).sum())
        fill = filled / float(w)
        out.append({"box": (x0o + x0i, y0o + a, w, h),
                    "fill": round(min(1.0, fill), 3)})
    return out


# ══════════════════════════ 统一状态 ══════════════════════════
def state(img: np.ndarray, max_rows: int = 8) -> dict:
    """把一张窗口图压成"布局状态"：内容区 + 文字行 + 网格面板 + 进度条。

    所有坐标同时给两种：像素（box）和**归一化**（rel，相对 content_box 的 0~1）。
    下游用 rel 就不怕窗口缩放。
    """
    if img is None or img.size == 0:
        return {"canvas": None, "error": "空图"}
    H, W = img.shape[:2]
    cb = content_box(img)
    cx, cy, cw, ch = cb

    def rel(box):
        x, y, w, h = box
        return [round((x - cx) / max(1, cw), 3), round((y - cy) / max(1, ch), 3),
                round(w / max(1, cw), 3), round(h / max(1, ch), 3)]

    rows = find_text_rows(img, box=cb)[:max_rows]
    lattices = find_lattice(img, box=cb)
    bars = find_bars(img, box=cb)

    return {
        "window": [W, H],
        "canvas": {"box": list(cb), "rel": [0, 0, 1, 1],
                   "size": [cw, ch], "margin": [cx, cy, W - cx - cw, H - cy - ch]},
        "text_rows": [{"box": list(r["box"]), "rel": rel(r["box"])} for r in rows],
        "lattices": [{"box": list(l["box"]), "rel": rel(l["box"]),
                      "pitch": l["pitch"], "cells": l["cells"], "score": l["score"]}
                     for l in lattices],
        "bars": [{"box": list(b["box"]), "rel": rel(b["box"]), "fill": b["fill"]}
                 for b in bars],
        "counts": {"text_rows": len(rows), "lattices": len(lattices), "bars": len(bars)},
    }
