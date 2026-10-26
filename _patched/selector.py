"""selector.py — 软选择器：按"语义"找控件，找不到才退回硬坐标

为什么要有它（AutoRPA / CoAct-1 的结论 + 我们自己的实测）：
    硬坐标（rel_frac）在窗口尺寸变一点、换台机器、主题改一下就偏 —— 实测偏过 47 px。
    软选择器按**文字/模板/相对锚点**找，界面小改不会崩；实在找不到再用坐标兜底。

三级降级（每级都留证据，失败时说清是哪级失败）：
    ① text      窗口内 OCR → 找包含 query 的那一行 → 点行中心（最稳，但对小字/图标无效）
    ② template  cv2.matchTemplate（适合图标、无文字按钮）
    ③ rel       窗口比例坐标（最后兜底；会被记录成 method="rel"，便于统计退化率）

用法（program/track 的动作里）：
    {"kind":"click",
     "find":{"text":"发现","within":[0,0,0.35,0.7]},     # 只在左栏找
     "rel_frac":[0.0351,0.359]}                          # 兜底
"""

from __future__ import annotations

import re
import time

# ─────────────────────────── 文本归一化（OCR 容错） ───────────────────────────

def norm_text(s: str) -> str:
    """只留字母数字与汉字，转小写。OCR 会把 `TRACK-OK-2152` 读成 `TRACKOK2152`。"""
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", (s or "").lower())


def lcs_share(a: str, b: str) -> float:
    """最长公共子串占 a 的比例（对 OCR 少一两个字宽容）。"""
    if not a or not b:
        return 0.0
    if a in b:
        return 1.0
    best = 0
    for i in range(len(a)):
        for j in range(i + best + 1, len(a) + 1):
            if a[i:j] in b:
                best = max(best, j - i)
            else:
                break
    return best / float(len(a))


# ─────────────────────────── 候选打分（纯函数，可单测） ───────────────────────────

def score_line(line_text: str, query: str, min_lcs: float = 0.6) -> float:
    """一条 OCR 行对 query 的匹配分（0 表示不匹配）。"""
    q, t = norm_text(query), norm_text(line_text)
    if not q or not t:
        return 0.0
    if q == t:
        return 1.0
    if q in t:
        return 0.95
    share = lcs_share(q, t)
    return share if share >= min_lcs else 0.0


def _geom(ln: dict) -> tuple[float, float, float, float] | None:
    """从 OCR 行里取 (x, y, w, h)。

    实测本机 ocr_ext 的行是**扁平**的 {"text","x","y","w","h"}，
    不是嵌套 rect —— 按 rect 写会静默取不到（踩过）。
    这里三种形态都兼容：扁平 / 嵌套 rect / 四元组 box。
    """
    if all(k in ln for k in ("x", "y", "w", "h")):
        try:
            return float(ln["x"]), float(ln["y"]), float(ln["w"]), float(ln["h"])
        except Exception:
            return None
    r = ln.get("rect") or {}
    if isinstance(r, dict) and r:
        try:
            return float(r["x"]), float(r["y"]), float(r["width"]), float(r["height"])
        except Exception:
            try:
                return (float(r["left"]), float(r["top"]),
                        float(r["right"]) - float(r["left"]),
                        float(r["bottom"]) - float(r["top"]))
            except Exception:
                return None
    b = ln.get("box") or []
    if isinstance(b, (list, tuple)) and len(b) == 4:
        try:
            return float(b[0]), float(b[1]), float(b[2]), float(b[3])
        except Exception:
            return None
    return None


def choose_line(lines: list[dict], query: str, min_lcs: float = 0.6,
                within: list[float] | None = None,
                rect: tuple[int, int, int, int] | None = None,
                prefer_smallest: bool = True) -> dict | None:
    """从 OCR 行里挑最匹配的一条。

    lines: [{"text": str, "rect": {"x","y","width","height"}}]，坐标是**屏幕绝对**
    within: 可选的窗口内相对区域 [x,y,w,h]，只在这个区域里找（缩小误命中）
    prefer_smallest: 同样分数时选面积小的（更像"控件"而不是整块面板）
    """
    best, best_key = None, None
    for ln in lines or []:
        txt = str(ln.get("text") or "")
        s = score_line(txt, query, min_lcs)
        if s <= 0:
            continue
        g = _geom(ln)
        if g is None:
            continue
        x, y, w, h = g
        if within and rect:
            ox, oy, ow, oh = rect
            rx, ry, rw, rh = within
            lo_x, hi_x = ox + rx * ow, ox + (rx + rw) * ow
            lo_y, hi_y = oy + ry * oh, oy + (ry + rh) * oh
            cx, cy = x + w / 2, y + h / 2
            if not (lo_x <= cx <= hi_x and lo_y <= cy <= hi_y):
                continue
        area = w * h
        key = (round(s, 3), -area if prefer_smallest else area)
        if best_key is None or key > best_key:
            best_key = key
            best = {"text": txt, "score": round(s, 3),
                    "at": (int(x + w / 2), int(y + h / 2)),
                    "area": int(area)}
    return best


# ─────────────────────────── 解析（带缓存 + 降级） ───────────────────────────

_CACHE: dict[str, tuple[float, list[dict]]] = {}


def _ocr_lines(rect: tuple[int, int, int, int], ttl: float = 0.6) -> list[dict]:
    """对窗口做一次 OCR，0.6 秒内复用（同一轮里点多个控件不重复 OCR）。"""
    key = f"{rect}"
    now = time.time()
    hit = _CACHE.get(key)
    if hit and (now - hit[0]) < ttl:
        return hit[1]
    try:
        from computer_mcp import ocr_ext

        res = ocr_ext.ocr_read(region={"x": rect[0], "y": rect[1],
                                       "w": rect[2], "h": rect[3]}, max_lines=80)
        lines = list(res.get("lines") or [])
    except Exception:
        lines = []
    _CACHE[key] = (now, lines)
    return lines


def clear_cache() -> None:
    _CACHE.clear()


def resolve(rect: tuple[int, int, int, int], spec: dict,
            min_lcs: float = 0.6, template_dir: str | None = None) -> dict:
    """按 spec 找点击点，返回 {"ok", "at", "method", "detail"}。

    spec 形如：
        {"text": "发现", "within": [0,0,0.35,0.7]}      # ① OCR
        {"template": "ic_discover.png"}                  # ② 模板
        {"rel": [0.0351, 0.359]}                         # ③ 直接给比例（兜底）
    """
    if not spec:
        return {"ok": False, "at": None, "method": "", "detail": "空 spec"}

    # ① 文本
    q = spec.get("text")
    if q:
        lines = _ocr_lines(rect)
        hit = choose_line(lines, str(q), min_lcs=float(spec.get("min_lcs", min_lcs)),
                          within=spec.get("within"), rect=rect)
        if hit:
            return {"ok": True, "at": hit["at"], "method": "text",
                    "detail": f"命中「{hit['text']}」score={hit['score']}"}
        # 文本没命中 → 继续降级

    # ② 模板
    name = spec.get("template")
    if name:
        try:
            import os

            import cv2
            import numpy as np
            from PIL import Image
            import mss

            d = template_dir or os.path.expanduser(
                r"~/.dsh/tools/desktop-mcp/templates")
            path = os.path.join(d, str(name))
            if os.path.isfile(path):
                # cv2.imread 在 Windows 上读不了含中文/空格的路径（实测返回 None）
                # → 先用 numpy 读字节再 imdecode
                tpl = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
                with mss.mss() as sct:
                    shot = sct.grab({"left": rect[0], "top": rect[1],
                                     "width": rect[2], "height": rect[3]})
                img = np.asarray(Image.frombytes("RGB", shot.size, shot.bgra,
                                                 "raw", "BGRX"))[:, :, 1]
                if tpl is not None and img.shape[0] >= tpl.shape[0] and img.shape[1] >= tpl.shape[1]:
                    res = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
                    _, mx, _, loc = cv2.minMaxLoc(res)
                    if mx >= float(spec.get("min_score", 0.75)):
                        at = (rect[0] + loc[0] + tpl.shape[1] // 2,
                              rect[1] + loc[1] + tpl.shape[0] // 2)
                        return {"ok": True, "at": at, "method": "template",
                                "detail": f"模板 {name} score={mx:.2f}"}
        except Exception as e:
            pass

    # ③ 比例兜底
    rel = spec.get("rel")
    if rel:
        x, y, w, h = rect
        at = (int(x + float(rel[0]) * w), int(y + float(rel[1]) * h))
        return {"ok": True, "at": at, "method": "rel",
                "detail": "文本/模板都没命中，退回比例坐标"}

    return {"ok": False, "at": None, "method": "",
            "detail": "三级都失败（text/template/rel 都没给或没命中）"}
