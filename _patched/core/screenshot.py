"""Screenshot capture functionality (patched for 对话壳（***）: smaller, faster, diff-aware).

Upstream behaviour: full-resolution PNG, ~128 ms and ~960 KB per call, and no way
to tell whether anything actually changed.

This version:
  * returns a downscaled JPEG by default (1280x720 q75, ~115 KB)
  * reports `changed` / `diff` by comparing against the previous frame
  * exposes screen_state() (no image, ~25 ms) and wait_for_change() for polling
    without pulling a picture

Tunable via env vars (read at import) or set_capture_config():
    DESK_CAPTURE_SCALE           float, default 0.5
    DESK_CAPTURE_QUALITY         int,   default 75
    DESK_CAPTURE_FORMAT          'jpeg' | 'png', default 'jpeg'
    DESK_CAPTURE_MASK_BOTTOM     int,   default 60   (taskbar strip ignored by diff)
    DESK_CAPTURE_DIFF_THRESHOLD  float, default 0.8  (mean abs diff %, counts as changed)
"""

import base64
import hashlib
import os
import time
from io import BytesIO
from typing import Any

import mss
from PIL import Image

_CONFIG: dict[str, Any] = {
    "scale": float(os.environ.get("DESK_CAPTURE_SCALE", "0.5")),
    "quality": int(os.environ.get("DESK_CAPTURE_QUALITY", "75")),
    "format": os.environ.get("DESK_CAPTURE_FORMAT", "jpeg").lower(),
    "mask_bottom": int(os.environ.get("DESK_CAPTURE_MASK_BOTTOM", "60")),
    "diff_threshold": float(os.environ.get("DESK_CAPTURE_DIFF_THRESHOLD", "0.8")),
}

_prev_small: bytes | None = None
_prev_ts = 0.0
_last_change_ts = 0.0
_change_count = 0


def get_capture_config() -> dict[str, Any]:
    return dict(_CONFIG)


def set_capture_config(**kwargs: Any) -> dict[str, Any]:
    for key, value in kwargs.items():
        if key not in _CONFIG or value is None:
            continue
        if key in ("quality", "mask_bottom"):
            _CONFIG[key] = int(value)
        elif key in ("scale", "diff_threshold"):
            _CONFIG[key] = float(value)
        elif key == "format":
            _CONFIG[key] = str(value).lower()
    return dict(_CONFIG)


def _monitor(region: dict[str, int] | None, sct) -> dict[str, int]:
    if not region:
        return sct.monitors[1]
    return {
        "left": int(region.get("x", 0)),
        "top": int(region.get("y", 0)),
        "width": int(region.get("w", 800)),
        "height": int(region.get("h", 600)),
    }


_LOCAL = __import__("threading").local()


def _sct():
    inst = getattr(_LOCAL, "sct", None)
    if inst is None:
        inst = mss.mss()
        _LOCAL.sct = inst
    return inst


def _grab(region: dict[str, int] | None = None) -> tuple[Image.Image, int, int]:
    sct = _sct()
    shot = sct.grab(_monitor(region, sct))
    img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    return img, shot.width, shot.height


def _small_gray(img: Image.Image) -> bytes:
    """Tiny grayscale frame used for cheap comparison (taskbar masked out)."""
    w, h = img.size
    keep_h = max(1, h - int(_CONFIG["mask_bottom"]))
    return img.crop((0, 0, w, keep_h)).resize((160, 90), Image.BILINEAR).convert("L").tobytes()


def _mean_abs_diff(a: bytes, b: bytes) -> float:
    if not a or not b or len(a) != len(b):
        return 100.0
    total = 0
    for x, y in zip(a, b, strict=True):
        total += abs(x - y)
    return (total / len(a)) / 255.0 * 100.0


def _update_diff(img: Image.Image) -> tuple[bool, float, float]:
    """Update the previous-frame cache; returns (changed, diff, since_last_ms)."""
    global _prev_small, _prev_ts, _last_change_ts, _change_count
    small = _small_gray(img)
    diff = _mean_abs_diff(_prev_small, small) if _prev_small is not None else 100.0
    changed = diff >= float(_CONFIG["diff_threshold"])
    now = time.time()
    since_last = (now - _prev_ts) * 1000 if _prev_ts else 0.0
    if changed:
        _last_change_ts = now
        _change_count += 1
    _prev_small = small
    _prev_ts = now
    return changed, diff, since_last


def capture_screenshot(region: dict[str, int] | None = None) -> dict[str, Any]:
    """Capture the screen, downscale, encode, and compare against the previous frame."""
    t0 = time.perf_counter()
    img, src_w, src_h = _grab(region)
    t_captured = time.perf_counter()

    changed, diff, since_last = _update_diff(img)

    scale = float(_CONFIG["scale"])
    if scale != 1.0:
        img = img.resize((max(1, int(src_w * scale)), max(1, int(src_h * scale))), Image.BILINEAR)
    out_w, out_h = img.size

    buffer = BytesIO()
    if str(_CONFIG["format"]) == "png":
        img.save(buffer, format="PNG")
        fmt = "base64_png"
    else:
        img.save(buffer, format="JPEG", quality=int(_CONFIG["quality"]))
        fmt = "base64_jpeg"
    raw = buffer.getvalue()
    t_encoded = time.perf_counter()

    return {
        "format": fmt,
        "data": base64.b64encode(raw).decode("utf-8"),
        "width": out_w,
        "height": out_h,
        "source_width": src_w,
        "source_height": src_h,
        "scale": scale,
        "bytes": len(raw),
        "changed": bool(changed),
        "diff": round(diff, 2),
        "capture_ms": round((t_captured - t0) * 1000, 1),
        "encode_ms": round((t_encoded - t_captured) * 1000, 1),
        "since_last_ms": round(since_last, 0),
        "frames_seen": _change_count,
        "hash": hashlib.md5(_prev_small or b"").hexdigest()[:12],
    }


def screen_state(region: dict[str, int] | None = None) -> dict[str, Any]:
    """Cheap state check: no image in the return value (~25 ms)."""
    global _prev_small
    t0 = time.perf_counter()
    img, src_w, src_h = _grab(region)
    changed, diff, since_last = _update_diff(img)
    return {
        "changed": bool(changed),
        "diff": round(diff, 2),
        "threshold": float(_CONFIG["diff_threshold"]),
        "hash": hashlib.md5(_prev_small or b"").hexdigest()[:12],
        "width": src_w,
        "height": src_h,
        "since_last_ms": round(since_last, 0),
        "ms_since_last_change": round((time.time() - _last_change_ts) * 1000, 0) if _last_change_ts else None,
        "frames_seen": _change_count,
        "state_ms": round((time.perf_counter() - t0) * 1000, 1),
    }


def wait_for_change(timeout_ms: int = 5000, poll_ms: int = 120) -> dict[str, Any]:
    """Block until the screen changes or the timeout expires."""
    t0 = time.time()
    deadline = t0 + timeout_ms / 1000.0
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = screen_state()
        if last.get("changed"):
            return {
                "changed": True,
                "diff": last.get("diff"),
                "hash": last.get("hash"),
                "waited_ms": round((time.time() - t0) * 1000, 0),
            }
        time.sleep(poll_ms / 1000.0)
    return {
        "changed": False,
        "diff": last.get("diff"),
        "hash": last.get("hash"),
        "waited_ms": round((time.time() - t0) * 1000, 0),
        "note": "no change above threshold before timeout",
    }
