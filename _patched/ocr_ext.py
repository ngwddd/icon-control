"""OCR helpers built on the Windows built-in recogniser (no Tesseract needed).

This is the fallback for applications whose UI Windows UI-Automation cannot see
(for example ChatClient 4.x, which draws its whole window into one render surface):
read the pixels, recognise the text, and click the text instead of guessing
pixel coordinates.

Three capabilities, all text-only results (far cheaper than sending an image):
    ocr_read(region)          -> every recognised line with its box
    find_text(query, region)  -> boxes whose text contains the query
    click_text(query, ...)    -> find + move the real cursor + click, in one call
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import time
from typing import Any

import mss
from PIL import Image

_ENGINE_CACHE: dict[str, Any] = {}


def _run_async(coro):
    """Run a pywinrt coroutine from sync code that may already sit in an event loop."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(coro)).result()


def _engine(lang_tag: str | None = None):
    key = lang_tag or "auto"
    if key in _ENGINE_CACHE:
        return _ENGINE_CACHE[key]
    import winrt.windows.globalization as g
    import winrt.windows.media.ocr as ocr

    engine = None
    if lang_tag:
        try:
            lang = g.Language(lang_tag)
            if ocr.OcrEngine.is_language_supported(lang):
                engine = ocr.OcrEngine.try_create_from_language(lang)
        except Exception:
            engine = None
    if engine is None:
        for tag in ("zh-Hans-CN", "zh-CN", "zh-Hans", "en-US"):
            try:
                lang = g.Language(tag)
                if ocr.OcrEngine.is_language_supported(lang):
                    engine = ocr.OcrEngine.try_create_from_language(lang)
                    if engine is not None:
                        break
            except Exception:
                continue
    if engine is None:
        engine = ocr.OcrEngine.try_create_from_user_profile_languages()
    _ENGINE_CACHE[key] = engine
    return engine


def _print_window(hwnd: int):
    """Grab a window's own pixels with PrintWindow (works when occluded)."""
    import win32gui
    import win32ui
    from ctypes import windll

    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        w, h = right - left, bottom - top
        if w <= 1 or h <= 1 or left <= -30000:
            return None, 0, 0
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, w, h)
        save_dc.SelectObject(bmp)
        ok = windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 0x00000002)
        img = None
        if ok:
            info = bmp.GetInfo()
            bits = bmp.GetBitmapBits(True)
            cand = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]), bits,
                                    "raw", "BGRX", 0, 1)
            if not _looks_blank(cand):
                img = cand
        win32gui.DeleteObject(bmp.GetHandle())
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)
        return img, int(left), int(top)
    except Exception:
        return None, 0, 0


def _grab(hwnd=None, region=None):
    """Return (image, origin_x, origin_y).

    With hwnd the pixels come from the window itself (PrintWindow), so an
    occluding window cannot corrupt what OCR reads. Region filtering happens
    later on absolute coordinates, because PrintWindow's bitmap and the client
    rectangle differ by the window border/title bar.
    """
    if hwnd:
        full, ox, oy = _print_window(hwnd)
        if full is not None:
            return full, ox, oy
    return _grab_screen(region)


def _region_for(region: dict[str, int] | None, hwnd: int | None) -> dict[str, int] | None:
    """Resolve the rectangle to OCR. Raising the window is best-effort: Windows
    refuses foreground steals often, and that must NOT poison the region."""
    if not hwnd:
        return region
    try:
        import win32con
        import win32gui
    except Exception:
        return region
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.30)
    except Exception:
        pass
    try:
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.15)
    except Exception:
        pass  # not allowed to steal focus - rendering below still works
    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    except Exception:
        return region
    if right - left <= 1 or bottom - top <= 1 or left <= -30000 or top <= -30000:
        return region
    return {"x": left, "y": top, "w": right - left, "h": bottom - top}


def _looks_blank(img: Image.Image) -> bool:
    try:
        lo, hi = img.convert("L").getextrema()
        return hi - lo <= 2
    except Exception:
        return False


_LOCAL = __import__("threading").local()


def _sct():
    inst = getattr(_LOCAL, "sct", None)
    if inst is None:
        inst = mss.mss()
        _LOCAL.sct = inst
    return inst


def _grab_screen(region: dict[str, int] | None):
    sct = _sct()
    if True:
        if region:
            mon = {
                "left": int(region.get("x", 0)),
                "top": int(region.get("y", 0)),
                "width": int(region.get("w", 800)),
                "height": int(region.get("h", 600)),
            }
        else:
            mon = sct.monitors[1]
        shot = sct.grab(mon)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        return img, int(mon["left"]), int(mon["top"])


async def _recognize(img: Image.Image):
    import winrt.windows.graphics.imaging as imaging
    import winrt.windows.storage.streams as streams

    # PNG bytes -> InMemoryRandomAccessStream -> BitmapDecoder -> SoftwareBitmap
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()

    stream = streams.InMemoryRandomAccessStream()
    writer = streams.DataWriter(stream)
    writer.write_bytes(data)
    await writer.store_async()
    await writer.flush_async()
    stream.seek(0)

    decoder = await imaging.BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    engine = _engine()
    if engine is None:
        raise RuntimeError("no OCR engine available on this system")
    return await engine.recognize_async(bitmap)


def _enhance(img, upscale: float = 1.0, boost: bool = False):
    """给小子/低对比度文字做前置增强，返回 (新图, 实际缩放比)。

    Windows OCR 对 12px 以下或浅灰文字经常读不出来（实测ChatClient「发送」按钮 found=0）。
    先放大再识别能显著提高命中率；耗时按面积增长，所以只在指定区域做。
    """
    from PIL import Image as _Img
    import PIL.ImageOps as _Ops

    scale = max(0.5, float(upscale or 1.0))
    out = img
    if scale != 1.0:
        out = out.resize((max(1, int(out.width * scale)), max(1, int(out.height * scale))),
                         _Img.LANCZOS)
    if boost:
        if out.mode != "L":
            out = out.convert("L")
        out = _Ops.autocontrast(out, cutoff=1)
        out = out.convert("RGB")
    return out, scale


def _angle_of(result) -> float | None:
    """WinRT exposes text_angle sometimes as a float, sometimes as an object."""
    a = getattr(result, "text_angle", None)
    try:
        return float(getattr(a, "value", a))
    except Exception:
        return None


def ocr_read(region: dict[str, int] | None = None, max_lines: int = 80,
             hwnd: int | None = None, upscale: float = 1.0,
             boost: bool = False) -> dict[str, Any]:
    t0 = time.perf_counter()
    if hwnd and not region:
        # no explicit region: raise the window and use its whole rectangle
        region = _region_for(None, hwnd)
    img, ox, oy = _grab(hwnd, region)
    img, _scale = _enhance(img, upscale, boost)
    result = _run_async(_recognize(img))
    lines = []
    for line in (result.lines or [])[: max(1, int(max_lines))]:
        words = list(line.words or [])
        if not words:
            continue
        xs = [w.bounding_rect.x for w in words]
        ys = [w.bounding_rect.y for w in words]
        ws = [w.bounding_rect.width for w in words]
        hs = [w.bounding_rect.height for w in words]
        lines.append(
            {
                "text": line.text,
                "x": int(ox + min(xs) / _scale),
                "y": int(oy + min(ys) / _scale),
                "w": int((max(xs) + ws[xs.index(max(xs))] - min(xs)) / _scale),
                "h": int(max(hs) / _scale),
            }
        )
    if region:
        def _inside(ln):
            cx = ln["x"] + ln["w"] // 2
            cy = ln["y"] + ln["h"] // 2
            return (region["x"] <= cx <= region["x"] + region["w"]
                    and region["y"] <= cy <= region["y"] + region["h"])

        lines = [ln for ln in lines if _inside(ln)]

    return {
        "ok": True,
        "count": len(lines),
        "lines": lines,
        "text_angle": _angle_of(result),
        "ms": round((time.perf_counter() - t0) * 1000, 1),
    }


def _norm(s: str) -> str:
    """Windows OCR puts spaces between CJK glyphs and makes occasional glyph
    mistakes (件 -> 亻牛). Strip all whitespace so matching works on content,
    not on spacing."""
    return "".join(str(s).split())


def _fuzzy_ratio(a: str, b: str) -> float:
    import difflib

    return difflib.SequenceMatcher(None, a, b).ratio()


def _lcs_len(a: str, b: str) -> int:
    """Longest common substring length (cheap DP, inputs are short)."""
    if not a or not b:
        return 0
    best = 0
    prev = [0] * (len(b) + 1)
    for ca in a:
        cur = [0] * (len(b) + 1)
        for j, cb in enumerate(b, start=1):
            if ca == cb:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def find_text(
    query: str,
    region: dict[str, int] | None = None,
    case_sensitive: bool = False,
    max_lines: int = 120,
    fuzzy: bool = True,
    min_ratio: float = 0.72,
    min_lcs_share: float = 0.6,
    hwnd: int | None = None,
    upscale: float = 1.0,
    boost: bool = False,
) -> dict[str, Any]:
    if not (query or "").strip():
        return {"error": "query is required"}
    data = ocr_read(region=region, max_lines=max_lines, hwnd=hwnd,
                    upscale=upscale, boost=boost)
    if not data.get("ok"):
        return data

    needle_raw = query if case_sensitive else query.casefold()
    needle = _norm(needle_raw)
    need_lcs = max(2, int(round(len(needle) * min_lcs_share)))
    hits: list[dict[str, Any]] = []

    for ln in data["lines"]:
        hay_raw = ln["text"] if case_sensitive else ln["text"].casefold()
        hay = _norm(hay_raw)

        ratio = None
        lcs = 0
        if needle and needle in hay:
            ratio = 1.0
            lcs = len(needle)
        elif fuzzy and needle:
            lcs = _lcs_len(needle, hay)
            best = 0.0
            span = len(needle)
            if len(hay) <= span:
                best = _fuzzy_ratio(hay, needle)
            else:
                for start in range(0, len(hay) - span + 1):
                    r = _fuzzy_ratio(hay[start:start + span], needle)
                    if r > best:
                        best = r
            # accept when either the whole-line similarity is high enough,
            # or the longest shared run covers most of the query (OCR often
            # mis-recognises one glyph, e.g. 件 -> 亻牛)
            if best >= min_ratio or lcs >= need_lcs:
                ratio = max(best, 0.0)

        if ratio is not None:
            hits.append(
                {
                    **ln,
                    "cx": ln["x"] + ln["w"] // 2,
                    "cy": ln["y"] + ln["h"] // 2,
                    "ratio": round(ratio, 3),
                    "lcs": lcs,
                }
            )

    hits.sort(key=lambda h: (-h["ratio"], -h["lcs"]))
    return {
        "ok": True,
        "query": query,
        "found": len(hits),
        "matches": hits[:10],
        "scanned_lines": data["count"],
        "normalized_query": needle,
        "need_lcs": need_lcs,
        "ms": data["ms"],
    }


def click_text(
    query: str,
    region: dict[str, int] | None = None,
    index: int = 0,
    mouse=None,
    case_sensitive: bool = False,
    settle_ms: int = 250,
    hwnd: int | None = None,
) -> dict[str, Any]:
    if mouse is None:
        return {"error": "mouse controller not provided"}
    res = find_text(query, region=region, case_sensitive=case_sensitive, hwnd=hwnd)
    if not res.get("ok"):
        return res
    matches = res.get("matches") or []
    if index >= len(matches):
        return {"error": f"text {query!r} not found", "found": res.get("found"), "matches": matches}
    target = matches[index]
    t0 = time.perf_counter()
    mouse.position = (target["cx"], target["cy"])
    time.sleep(0.08)
    from pynput.mouse import Button

    mouse.click(Button.left, 1)
    time.sleep(max(0, settle_ms) / 1000.0)
    return {
        "ok": True,
        "clicked_text": target["text"],
        "x": target["cx"],
        "y": target["cy"],
        "ms": round((time.perf_counter() - t0) * 1000, 1),
    }
