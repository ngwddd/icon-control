"""Named macros with window-relative coordinates and per-step verification.

Why this exists: every extra gesture used to cost a model round trip (seconds).
A macro replays a whole recorded sequence inside ONE tool call, and stores its
coordinates RELATIVE to the target window's client area, so moving or resizing
the window does not break it.

Macro file format (JSON, stored in MACRO_DIR):
{
  "name": "wechat_send",
  "description": "send a text to the WeChat file-transfer helper",
  "window": {"title_contains": "微信"},        # or {"process": "Weixin.exe"}
  "steps": [
    {"action": "click", "rel": [220, 380]},
    {"action": "sleep", "ms": 250},
    {"action": "type", "text": "${text}"},
    {"action": "click", "rel": [812, 992], "expect": {"changed": true, "timeout_ms": 1200}}
  ]
}

Step extras understood on top of the batch actions:
  "rel": [dx, dy]        coordinates relative to the window client area
  "expect": {...}        after this step, wait for a screen change
                         ({"changed": true, "timeout_ms": 1200}); failing it aborts
"""

from __future__ import annotations

import json
import os
import re
import time
from computer_mcp import execution as _execution
from pathlib import Path
from typing import Any

MACRO_DIR = os.environ.get(
    "DESK_MACRO_DIR",
    str(__import__('computer_mcp.security', fromlist=['data_home']).data_home() / 'macros'),
)

_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


# --------------------------------------------------------------------------- #
# storage
# --------------------------------------------------------------------------- #
def _path(name: str) -> str:
    if not _NAME_RE.match(name or ""):
        raise ValueError(f"bad macro name: {name!r}")
    return os.path.join(MACRO_DIR, name + ".json")


def macro_list() -> dict[str, Any]:
    os.makedirs(MACRO_DIR, exist_ok=True)
    out = []
    for fn in sorted(os.listdir(MACRO_DIR)):
        if not fn.endswith(".json"):
            continue
        p = os.path.join(MACRO_DIR, fn)
        try:
            with open(p, "r", encoding="utf-8-sig") as fh:
                spec = json.load(fh)
            out.append(
                {
                    "name": spec.get("name") or fn[:-5],
                    "description": spec.get("description", ""),
                    "window": spec.get("window"),
                    "steps": len(spec.get("steps") or []),
                }
            )
        except Exception as exc:
            out.append({"file": fn, "error": str(exc)})
    return {"ok": True, "dir": MACRO_DIR, "count": len(out), "macros": out}


def macro_save(spec: dict[str, Any]) -> dict[str, Any]:
    name = str(spec.get("name") or "").strip()
    if not name:
        return {"error": "spec.name is required"}
    steps = spec.get("steps")
    if not isinstance(steps, list) or not steps:
        return {"error": "spec.steps must be a non-empty list"}
    os.makedirs(MACRO_DIR, exist_ok=True)
    p = _path(name)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(spec, fh, ensure_ascii=False, indent=2)
    return {"ok": True, "saved": p, "name": name, "steps": len(steps)}


# --------------------------------------------------------------------------- #
# window resolution
# --------------------------------------------------------------------------- #
def _find_window(hint: dict[str, Any] | None) -> dict[str, Any] | None:
    if not hint:
        return None
    import win32gui

    title_sub = str(hint.get("title_contains") or "").casefold()
    proc_sub = str(hint.get("process") or "").casefold()
    explicit = hint.get('hwnd')
    if explicit is not None:
        if isinstance(explicit, bool) or not str(explicit).isdigit() or int(explicit) <= 0:
            raise ValueError('Explicit target hwnd must be a positive window handle')
        explicit = int(explicit)
    matches = []

    def cb(hwnd, _):
        if explicit is not None and hwnd != explicit:
            return
        if not win32gui.IsWindowVisible(hwnd) or win32gui.GetAncestor(hwnd, 2) != hwnd:
            return
        title = win32gui.GetWindowText(hwnd)
        if not title.strip() or (title_sub and title_sub not in title.casefold()):
            return
        if proc_sub:
            try:
                import win32process, psutil
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if proc_sub not in psutil.Process(pid).name().casefold():
                    return
            except Exception:
                return
        if not explicit and not title_sub and not proc_sub:
            return
        matches.append((hwnd, title))

    win32gui.EnumWindows(cb, None)
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError('Multiple matching windows; select an explicit top-level hwnd')
    hwnd, title = matches[0]
    wr = win32gui.GetWindowRect(hwnd)
    return {
        "hwnd": hwnd,
        "title": title,
        "minimized": bool(win32gui.IsIconic(hwnd)),
        # 客户区几何（保留兼容）
        **_client_origin(hwnd),
        # 窗口矩形几何 —— OCR(PrintWindow) 就是这个坐标系，点击必须用它换算
        "rect_x": int(wr[0]), "rect_y": int(wr[1]),
        "rect_w": int(wr[2] - wr[0]), "rect_h": int(wr[3] - wr[1]),
    }


def _force_foreground(hwnd: int) -> bool:
    """Bring a window to the front even when Windows' foreground lock refuses.

    Plain SetForegroundWindow is routinely rejected; when that happens the window
    stays behind and every simulated click lands on whatever covers it. That is
    exactly how a "successful" macro once did nothing at all. Attaching to the
    foreground thread's input queue lifts the restriction.
    """
    import time as _t

    import win32api
    import win32con
    import win32gui
    import win32process

    try:
        if win32gui.GetForegroundWindow() == hwnd:
            return True
    except Exception:
        return False

    fg = 0
    try:
        fg = win32gui.GetForegroundWindow()
    except Exception:
        pass
    fg_tid = 0
    if fg:
        try:
            fg_tid, _ = win32process.GetWindowThreadProcessId(fg)
        except Exception:
            fg_tid = 0
    my_tid = win32api.GetCurrentThreadId()
    attached = False
    try:
        if fg_tid and fg_tid != my_tid:
            win32process.AttachThreadInput(fg_tid, my_tid, True)
            attached = True
    except Exception:
        attached = False
    try:
        _execution.checkpoint('macro_run')
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        _execution.checkpoint('macro_run')
        win32gui.BringWindowToTop(hwnd)
        _execution.checkpoint('macro_run')
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    if attached:
        try:
            win32process.AttachThreadInput(fg_tid, my_tid, False)
        except Exception:
            pass

    if win32gui.GetForegroundWindow() != hwnd:
        # last resort: bounce the window through TOPMOST, which forces a z-order change
        try:
            swp = win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW
            _execution.checkpoint('macro_run')
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, swp)
            _execution.checkpoint('macro_run')
            win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0, swp)
            _execution.checkpoint('macro_run')
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass

    _execution.sleep(0.12)
    try:
        return win32gui.GetForegroundWindow() == hwnd
    except Exception:
        return False


def _refresh_geometry(hwnd: int) -> dict[str, Any]:
    """Re-read BOTH coordinate systems after a window was restored/moved.

    Forgetting the window-rect half here is how a macro ends up using the
    -32000/-32000 geometry of a minimized window and clicking into nowhere.
    """
    import win32gui

    wr = win32gui.GetWindowRect(hwnd)
    return {
        **_client_origin(hwnd),
        "rect_x": int(wr[0]), "rect_y": int(wr[1]),
        "rect_w": int(wr[2] - wr[0]), "rect_h": int(wr[3] - wr[1]),
        "minimized": bool(win32gui.IsIconic(hwnd)),
    }


def _ensure_usable(hwnd: int, restore: bool = True) -> dict[str, Any]:
    """Make the window usable: un-minimize it and make sure it is really in front.

    Returns {"restored": bool, "foreground": bool} on success, or {"error": ...}
    when it cannot be brought to the front - in that case the caller MUST abort
    instead of clicking into whatever window happens to be on top.
    """
    import time as _t

    import win32con
    import win32gui

    info: dict[str, Any] = {"restored": False}
    if win32gui.IsIconic(hwnd):
        if not restore:
            return {"error": "target window is minimized and restore=false"}
        _execution.checkpoint('macro_run')
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        _execution.sleep(0.35)
        info["restored"] = True

    info["foreground"] = _force_foreground(hwnd)
    if not info["foreground"]:
        return {
            "error": "could not bring the target window to the foreground; refusing to click blindly",
            "hwnd": hwnd,
            "hint": "another window covers it and Windows denied the foreground switch",
        }
    return info


def _screen_bounds() -> tuple[int, int, int, int]:
    import win32api

    # 76..79 = SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN
    return (
        win32api.GetSystemMetrics(76),
        win32api.GetSystemMetrics(77),
        win32api.GetSystemMetrics(78),
        win32api.GetSystemMetrics(79),
    )


def _client_origin(hwnd: int) -> dict[str, int]:
    import win32gui

    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    x, y = win32gui.ClientToScreen(hwnd, (left, top))
    return {"x": int(x), "y": int(y), "w": int(right - left), "h": int(bottom - top)}


# --------------------------------------------------------------------------- #
# execution
# --------------------------------------------------------------------------- #
def _subst(value: Any, params: dict[str, Any]) -> Any:
    if isinstance(value, str):
        def repl(m):
            key = m.group(1)
            if key not in params:
                raise KeyError(f"macro parameter {key!r} not supplied")
            return str(params[key])

        return re.sub(r"\$\{(\w+)\}", repl, value)
    if isinstance(value, list):
        return [_subst(v, params) for v in value]
    if isinstance(value, dict):
        return {k: _subst(v, params) for k, v in value.items()}
    return value


# --------------------------------------------------------------------------- #
# coordinate helpers: top-left ("tl", default) or bottom-right ("br") anchored
# --------------------------------------------------------------------------- #
def _resolve_point(step: dict[str, Any], win: dict[str, Any] | None) -> tuple[int, int] | None:
    # ── 按比例坐标（抗窗口缩放）──
    # rel_frac = [fx, fy]，相对窗口客户区的 0~1 比例。
    # 这是为「同一个宏在 600x700 和 1566x1054 窗口上都要能点对」而加的：
    # 绝对 rel 在大窗口上会整体偏移（实测微信 type_verified 因此失配）。
    if "rel_frac" in step:
        if not win:
            return None
        fx, fy = float(step["rel_frac"][0]), float(step["rel_frac"][1])
        wx = (win.get("rect_x", win["x"]) if win else 0)
        wy = (win.get("rect_y", win["y"]) if win else 0)
        ww = (win.get("rect_w", win["w"]) if win else 0)
        wh = (win.get("rect_h", win["h"]) if win else 0)
        return (int(round(wx + fx * ww)), int(round(wy + fy * wh)))
    if "rel" not in step:
        return None
    dx, dy = int(step["rel"][0]), int(step["rel"][1])
    # 与 OCR/PrintWindow 同坐标系（窗口矩形），避免边框偏移导致的系统性点歪
    wx = (win.get("rect_x", win["x"]) if win else 0)
    wy = (win.get("rect_y", win["y"]) if win else 0)
    ww = (win.get("rect_w", win["w"]) if win else 0)
    wh = (win.get("rect_h", win["h"]) if win else 0)
    if str(step.get("anchor", "tl")).lower() == "br":
        return (wx + ww + dx, wy + wh + dy)
    return (wx + dx, wy + dy)


def _resolve_region(step: dict[str, Any], win: dict[str, Any] | None) -> dict[str, int] | None:
    """两种来源：region_mem（记忆库里的区域）优先，其次 region_rel。

    region_mem = {"app": "...", "key": "..."}  ← P2-1 学的区域，窗口缩放会跟着算
    region_rel = [dx, dy, w, h]  + 可选 region_anchor = "tl"(默认) / "br"

    region_anchor="tl"（默认）：dx/dy 从窗口左上角量
    region_anchor="br"       ：dx/dy 是**右下边距**（距右边/下边），
                               适合随窗口高度变化而移动的底部区域（输入框、工具栏）
    """
    mem = step.get("region_mem")
    if mem and win:
        try:
            from computer_mcp import anchor_mem as _am_r
            got = _am_r.locate_region(str(mem.get("app")), str(mem.get("key")), win["hwnd"])
            if got.get("ok"):
                return got["region"]
        except Exception:
            pass

    # region_frac = [fx, fy, fw, fh]：全部是 0~1 比例，最抗缩放
    fr = step.get("region_frac")
    if fr and win:
        fx, fy, fw, fh = (float(v) for v in fr)
        bx = win.get("rect_x", win["x"])
        by = win.get("rect_y", win["y"])
        rw = win.get("rect_w", win["w"])
        rh = win.get("rect_h", win["h"])
        return {"x": int(round(bx + fx * rw)), "y": int(round(by + fy * rh)),
                "w": max(1, int(round(fw * rw))), "h": max(1, int(round(fh * rh)))}

    rr = step.get("region_rel")
    if not rr or not win:
        return None
    dx, dy, w, h = (int(v) for v in rr)
    bx = win.get("rect_x", win["x"])
    by = win.get("rect_y", win["y"])
    if str(step.get("region_anchor", "tl")).lower() == "br":
        rw = win.get("rect_w", win["w"])
        rh = win.get("rect_h", win["h"])
        return {"x": bx + rw - dx - w, "y": by + rh - dy - h, "w": w, "h": h}
    return {"x": bx + dx, "y": by + dy, "w": w, "h": h}


def _fingerprint(win, strings, region=None, min_lcs_share=0.55, hwnd=None):
    """OCR once and report which of `strings` are currently visible."""
    from computer_mcp import ocr_ext

    texts = [str(s) for s in (strings or []) if str(s).strip()]
    if not texts:
        return {"ok": True, "matched": [], "missing": [], "skipped": True}
    res = ocr_ext.ocr_read(region=region, hwnd=None if region else hwnd, max_lines=120)
    lines = [ln["text"] for ln in (res.get("lines") or [])]
    norm = lambda s: "".join(str(s).split())
    hay = [norm(t) for t in lines]
    matched, missing = [], []
    for q in texts:
        nq = norm(q)
        hit = any(nq in h for h in hay)
        if not hit:
            # 允许单字错认：最长公共子串占比足够也算命中
            best = 0
            for h in hay:
                if not h:
                    continue
                cur = [0] * (len(h) + 1)
                prev = [0] * (len(h) + 1)
                for ca in nq:
                    for j, cb in enumerate(h, 1):
                        if ca == cb:
                            cur[j] = prev[j - 1] + 1
                            best = max(best, cur[j])
                    prev, cur = cur, [0] * (len(h) + 1)
            need = max(2, int(round(len(nq) * float(min_lcs_share))))
            hit = bool(nq) and best >= need
        (matched if hit else missing).append(q)
    return {"ok": not missing, "matched": matched, "missing": missing,
            "lines_seen": len(lines), "ms": res.get("ms")}


def window_metrics(hwnd: int) -> dict[str, Any]:
    """Report both coordinate systems so a click can be self-checked.

    OCR (PrintWindow) works in window-rect space; code that mixes in the client
    area is off by the border/title bar (measured +11px on WeChat). That offset is
    exactly what makes a *known* position click the wrong element.
    """
    import ctypes

    import win32gui

    try:
        wr = win32gui.GetWindowRect(hwnd)
        co = win32gui.ClientToScreen(hwnd, (0, 0))
        cr = win32gui.GetClientRect(hwnd)
    except Exception as exc:
        return {"error": str(exc)}
    dx, dy = int(co[0] - wr[0]), int(co[1] - wr[1])
    try:
        dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
    except Exception:
        dpi = None
    return {
        "hwnd": hwnd,
        "title": win32gui.GetWindowText(hwnd),
        "window_rect": {"x": wr[0], "y": wr[1], "w": wr[2] - wr[0], "h": wr[3] - wr[1]},
        "client_origin": {"x": co[0], "y": co[1], "w": cr[2], "h": cr[3]},
        "offset_client_vs_rect": {"dx": dx, "dy": dy},
        "dpi": dpi,
        "scale_guess": round(dpi / 96, 2) if dpi else None,
        "click_space": "window_rect (same as OCR/PrintWindow)",
        "warning": ("client 与 rect 偏移 %+d,%+d —— 换算一律用 rect" % (dx, dy)) if (dx or dy) else "无偏移",
    }


# Read capabilities from substituted on-disk steps, never from caller-supplied metadata.
_MACRO_SCOPES = {
    **dict.fromkeys("move click double_click right_click sleep".split(), ()),
    **dict.fromkeys("type key hotkey paste".split(), ('text_entry',)),
    **dict.fromkeys("clipboard_set".split(), ('clipboard_write',)),
    **dict.fromkeys("clipboard_get assert_clipboard".split(), ('clipboard_read',)),
    **dict.fromkeys("wait_change screen_state ui_click ui_invoke anchor_click page_check ensure_page click_text find_text verify_text wait_window assert_template assert_baseline wait_template sample_stable hover_probe assert_text assert_title".split(), ('screen_read',)),
    **dict.fromkeys("type_verified ensure_chat".split(), ('screen_read','text_entry')),
    **dict.fromkeys("learn_region learn_item capture_template set_baseline".split(), ('screen_read','file_write')),
    'anchor_click': ('screen_read','file_write'), 'launch': ('process',), 'close_windows': ('window_close',), 'exit_app': ('window_close',),
    'assert_file': ('file_read',),
    'paste': ('text_entry', 'clipboard_read'),
    'guarded_click': ('screen_read',),
}

def _guarded_click(step, win, mouse):
    """One visual transition: reject missing evidence, never retry the click."""
    from computer_mcp import verify_flow
    from computer_mcp.actions import mouse as mouse_actions
    if not win:
        return dict(ok=False, error='guarded_click requires an identified target window')

    def checks(field):
        value = step.get(field)
        if not isinstance(value, list) or not value:
            raise ValueError('guarded_click requires nonempty before and after checks')
        result = []
        identity_evidence = False
        for raw in value:
            if not isinstance(raw, dict) or raw.get('kind') not in ('text', 'template', 'baseline', 'stable'):
                raise ValueError('guarded_click accepts only explicit visual assertion kinds')
            check = dict(raw)
            if check['kind'] == 'text':
                import math
                query = check.get('query')
                if not isinstance(query, str) or not query.strip():
                    raise ValueError('Text page checks require a nonempty query')
                threshold = check.get('min_lcs_share', 1.0)
                if (isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or
                        not math.isfinite(threshold) or threshold != 1.0):
                    raise ValueError('Guarded text checks require min_lcs_share=1.0')
                check['min_lcs_share'] = 1.0
                check['require_evidence'] = True
            if type(check.get('absent', False)) is not bool:
                raise ValueError('Page assertion absent flag must be boolean')
            if check['kind'] == 'template':
                import math
                confidence = check.get('confidence', 0.8)
                if (isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or
                        not math.isfinite(confidence) or not 0.8 <= confidence <= 1):
                    raise ValueError('Guarded template confidence must be in [0.8, 1]')
                if not (check.get('name') or check.get('template')):
                    raise ValueError('Template page checks require an asset name')
            if check['kind'] in ('text', 'template') and not check.get('absent', False):
                identity_evidence = True
            region = _resolve_region(check, win)
            if region:
                check['region'] = region
            check['hwnd'] = win['hwnd']
            result.append(check)
        if not identity_evidence:
            raise ValueError('Each page condition requires positive text or template identity evidence')
        return result

    # Validate both halves before doing anything, not after the click.
    before, after = checks('before'), checks('after')
    import win32process
    from computer_mcp import capabilities, permission
    _, pid = win32process.GetWindowThreadProcessId(win['hwnd'])
    expected = capabilities.process_record(pid)
    import win32gui
    root = win32gui.GetAncestor(win['hwnd'], 2)
    if root != win['hwnd']:
        raise permission.PermissionDenied('Guarded click requires an explicit top-level window')
    initial = verify_flow.run([{'assert': before}])
    if not initial.get('ok'):
        return dict(ok=False, phase='before', evidence=initial, clicked=False)
    point = _resolve_point(step, win)
    if point is None:
        raise ValueError('guarded_click requires an explicit point')
    # Window geometry alone does not establish a trustworthy click target.
    _, pid = win32process.GetWindowThreadProcessId(win['hwnd'])
    if capabilities.process_record(pid) != expected:
        raise permission.PermissionDenied('Guarded click target changed after page observation')
    import win32gui
    _, point_pid = win32process.GetWindowThreadProcessId(win32gui.WindowFromPoint(point))
    if (capabilities.process_record(point_pid) != expected or
            win32gui.GetAncestor(win32gui.WindowFromPoint(point), 2) != root):
        raise permission.PermissionDenied('Guarded click point belongs to a different top-level window')
    mouse_actions.click(controller=mouse, x=point[0], y=point[1], button=step.get('button', 'left'), expected_hwnd=root)
    _execution.sleep(min(3000, max(0, int(step.get('settle_ms', 300)))) / 1000)
    _, pid = win32process.GetWindowThreadProcessId(win['hwnd'])
    if capabilities.process_record(pid) != expected:
        return dict(ok=False, phase='after', clicked=True, error='Target identity changed before postcondition')
    final = verify_flow.run([{'assert': after}])
    _, pid = win32process.GetWindowThreadProcessId(win['hwnd'])
    if capabilities.process_record(pid) != expected:
        return dict(ok=False, phase='after', clicked=True, error='Target identity changed during postcondition')
    return dict(ok=bool(final.get('ok')), phase='after', clicked=True, evidence=final,
                verified=bool(final.get('ok')), verification_method='visual_assertions')


def _check_macro_action(action):
    from computer_mcp import permission, capabilities
    if action not in _MACRO_SCOPES:
        raise ValueError('Unknown macro action: ' + action)
    for scope in _MACRO_SCOPES[action]:
        if not capabilities.has_scope(scope):
            raise permission.PermissionDenied('Macro action requires ' + scope)


def _clipboard_text():
    """Current clipboard text, or None. Never raises for a non-text clipboard."""
    from computer_mcp import capabilities, permission
    if not capabilities.has_scope('clipboard_read'):
        raise permission.PermissionDenied('Clipboard read approval required')
    import win32clipboard as clipboard
    clipboard.OpenClipboard()
    try:
        try:
            return str(clipboard.GetClipboardData(clipboard.CF_UNICODETEXT))
        except Exception:
            return None
    finally:
        clipboard.CloseClipboard()


def _clipboard_sequence():
    import win32clipboard as clipboard
    return int(clipboard.GetClipboardSequenceNumber())


def _write_clipboard(text):
    """Replace the clipboard and return the sequence number of our own write."""
    import win32clipboard as clipboard
    clipboard.OpenClipboard()
    try:
        clipboard.EmptyClipboard()
        clipboard.SetClipboardText(str(text))
    finally:
        clipboard.CloseClipboard()
    return _clipboard_sequence()


def _restore_clipboard(previous, written_sequence):
    """Restore only when nobody else wrote after us; never clobber newer content."""
    if previous is None:
        return False
    if _clipboard_sequence() != written_sequence:
        return False
    _write_clipboard(previous)
    return True


def _clipboard_observation(value, need):
    """Report match/size only: clipboard content must never reach a log."""
    value = '' if value is None else str(value)
    ok = (str(need) in value) if need else True
    entry = {'chars': len(value)}
    sub = {'ok': ok}
    if not ok:
        sub['error'] = 'clipboard does not contain the required text'
    return entry, sub



def run_macro(
    name: str,
    params: dict[str, Any] | None = None,
    mouse=None,
    keyboard=None,
    dry_run: bool = False,
    default_gap_ms: int = 140,
) -> dict[str, Any]:
    from computer_mcp import ocr_ext  # noqa: F401  (anchor_click.fallback_text 需要)
    from computer_mcp.core import screenshot as capture_core
    from computer_mcp import ui_ext

    params = params or {}
    try:
        p = _path(name)
    except ValueError as exc:
        return {"error": str(exc)}
    if not os.path.exists(p):
        return {"error": f"macro not found: {name}", "dir": MACRO_DIR}

    from computer_mcp.workspace import owned_path
    p = owned_path(Path(MACRO_DIR), p)
    with p.open("rb") as source:
        body = source.read(1048577)
    if len(body) > 1048576:
        raise ValueError('Macro exceeds the 1 MiB limit')
    spec = json.loads(body.decode('utf-8-sig'))

    merged = dict(spec.get("defaults") or {})
    merged.update(params)
    required = spec.get('required_params', [])
    if not isinstance(required, list) or any(not isinstance(k, str) for k in required):
        return {'error': 'Invalid required_params declaration'}
    missing = [key for key in required if merged.get(key) is None or
               isinstance(merged.get(key), bool) or not str(merged.get(key)).strip()]
    if missing:
        return {'error': 'Missing nonempty required macro parameters', 'missing_params': missing}
    try:
        spec = _subst(spec, merged)
    except KeyError as exc:
        return {"error": str(exc)}

    try:
        win = _find_window(spec.get("window"))
    except ValueError as exc:
        return {'error': str(exc)}
    if spec.get("window") and win is None:
        # 宏自己会 launch / wait_window 时，允许先没有窗口
        allows_late = bool(spec.get("allow_missing_window")) or any(
            str(s.get("action", "")).lower() in ("launch", "wait_window")
            for s in (spec.get("steps") or [])
        )
        if not allows_late:
            return {"error": "target window not found", "window_hint": spec.get("window")}

    # A minimized/mislocated window produces garbage coordinates (-32000, tiny size).
    # Restore + foreground it first, then re-read its client origin.
    guard: dict[str, Any] = {}
    if win:
        guard = _ensure_usable(win["hwnd"], restore=bool(spec.get("restore", True)))
        if guard.get("error"):
            return {"error": guard["error"], "window": win}
        win = {**win, **_refresh_geometry(win["hwnd"])}

    vx, vy, vw, vh = _screen_bounds()

    def _in_screen(x: int, y: int) -> bool:
        return vx <= x < vx + vw and vy <= y < vy + vh

    # Refuse to run if any relative coordinate lands outside the visible screen.
    bad: list[dict[str, Any]] = []
    for i, step in enumerate(spec.get("steps") or []):
        pt = _resolve_point(step, win)
        if pt and not _in_screen(*pt):
            bad.append({"i": i, "action": step.get("action"), "abs": list(pt)})
    if bad:
        return {
            "error": "resolved coordinates fall outside the screen; macro aborted before clicking",
            "window": win,
            "offscreen_steps": bad[:5],
            "hint": "open/restore the target window first, or fix the rel coordinates",
        }

    for step in spec.get("steps") or []:
        _check_macro_action(str(step.get("action", "")).lower())

    if dry_run:
        resolved = []
        for i, step in enumerate(spec.get("steps") or []):
            item = {"i": i, "action": step.get("action")}
            pt = _resolve_point(step, win)
            if pt:
                item["abs"] = list(pt)
            reg = _resolve_region(step, win)
            if reg:
                item["region"] = reg
            for k in ("text", "query", "key", "name", "ms", "index"):
                if k in step:
                    item[k] = step[k]
            resolved.append(item)
        return {"ok": True, "dry_run": True, "window": win, "steps": resolved}

    t_all = time.perf_counter()
    log: list[dict[str, Any]] = []
    failed = 0

    # 步骤展开：repeat=N 的步骤直接复制 N 份（每份独立 _repeat_index）
    expanded: list[dict[str, Any]] = []
    for raw in (spec.get("steps") or []):
        n = max(1, int(raw.get("repeat", 1)))
        if n == 1:
            expanded.append(dict(raw))
        else:
            for k in range(n):
                cp = dict(raw)
                cp["_repeat_index"] = k
                expanded.append(cp)

    # 队列化而不是 for：失败时可以把同一个步骤重新塞回队头实现 retry
    queue: list[tuple[int, dict[str, Any]]] = list(enumerate(expanded))
    while queue:
        i, step = queue.pop(0)
        step = dict(step)
        action = str(step.get("action", "")).lower()
        _check_macro_action(action)
        t0 = time.perf_counter()
        entry: dict[str, Any] = {"i": i, "action": action}
        # 每一步都重读几何：用户在宏运行中挪窗口/改大小是常见情况
        if win:
            try:
                win = {**win, **_refresh_geometry(win["hwnd"])}
            except Exception:
                pass
        try:
            pt = _resolve_point(step, win)
            if pt:
                step["x"], step["y"] = pt
                entry["abs"] = list(pt)
            region = _resolve_region(step, win)
            if region:
                entry["region"] = region

            if action in ("move", "click", "double_click", "right_click", "sleep", "wait_change", "screen_state"):
                sub = ui_ext.run_batch(
                    [step], mouse, keyboard, stop_on_error=True, default_sleep_ms=0, max_steps=1
                )
            elif action == "guarded_click":
                sub = _guarded_click(step, win, mouse)
                entry['page_transition'] = sub
            elif action == "type":
                keyboard.type(str(step.get("text", "")))
                sub = {"ok": True}
            elif action == "key":
                k = ui_ext.resolve_key(str(step.get("key", "enter")))
                keyboard.press(k)
                keyboard.release(k)
                sub = {"ok": True}
            elif action == "ui_click":
                res = ui_ext.ui_click(
                    name=str(step["name"]),
                    hwnd=step.get("hwnd") or (win["hwnd"] if win else None),
                    exact=bool(step.get("exact", False)),
                    mouse=mouse,
                )
                sub = {"ok": bool(res.get("ok")), "result": res}
            elif action == "ui_invoke":
                res = ui_ext.ui_invoke(
                    name=str(step["name"]),
                    hwnd=step.get("hwnd") or (win["hwnd"] if win else None),
                    exact=bool(step.get("exact", False)),
                )
                sub = {"ok": bool(res.get("ok")), "result": res}
            elif action == "type_verified":
                # 「点 -> 打 -> 验 -> 重试」：解决"点完立刻打字，焦点还没落到输入框"的竞态
                from computer_mcp import anchor_mem as _am

                app_id = str(step.get("app", "unknown"))
                key_id = str(step.get("key", ""))
                region = _resolve_region(step, win) if step.get("region_rel") else None
                text = str(step.get("text", ""))
                attempts = max(1, int(step.get("attempts", 3)))
                tries: list[dict[str, Any]] = []
                ok_typed = False
                target = None

                v = _am.verify(app_id, key_id, win["hwnd"] if win else 0) if key_id else {"ok": False}
                if v.get("ok") or (v.get("reason") == "hash" and v.get("at")):
                    target = tuple(v["at"])
                elif step.get("fallback_rel") and win:
                    target = _resolve_point({**step, "rel": step["fallback_rel"]}, win)

                for attempt in range(attempts):
                    if target is None:
                        tries.append({"attempt": attempt, "ok": False, "error": "没有可用的输入框坐标"})
                        break
                    mouse.position = target
                    _execution.sleep(0.06 + 0.06 * attempt)
                    from pynput.mouse import Button as _B
                    mouse.click(_B.left, 1)
                    _execution.sleep(float(step.get("focus_wait_ms", 260) + 80 * attempt) / 1000.0)
                    # 每次尝试前都先清空，避免残留拼接（Ctrl+A / Delete）
                    if True:
                        # 重试前先 Ctrl+A / Delete 清掉上一次可能残留的文本
                        _ctrl = ui_ext.resolve_key("ctrl")
                        _a = ui_ext.resolve_key("a")
                        keyboard.press(_ctrl); keyboard.press(_a)
                        keyboard.release(_a); keyboard.release(_ctrl)
                        _execution.sleep(0.08)
                        _del = ui_ext.resolve_key("delete")
                        keyboard.press(_del); keyboard.release(_del)
                    keyboard.type(text)
                    _execution.sleep(float(step.get("settle_ms", 180)) / 1000.0)
                    fp = _fingerprint(win, [text], region=region, hwnd=None if region else (win["hwnd"] if win else None),
                                      min_lcs_share=float(step.get("min_lcs_share", 0.6)))
                    tries.append({"attempt": attempt, "ok": fp.get("ok"), "missing": fp.get("missing")})
                    if fp.get("ok"):
                        ok_typed = True
                        break
                entry["tries"] = tries
                entry["ok"] = ok_typed
                if not ok_typed:
                    entry["error"] = "打字后校验失败：输入框里没有出现文本（焦点没进去或输入被拦）"
                sub = {"ok": ok_typed}
            elif action == "anchor_click":
                # 记忆库优先：查表 -> 视觉指纹校验 -> 点击
                # 校验不过就降级（OCR 找文字 / 兜底 rel 坐标），成功后自动重写记忆
                from computer_mcp import anchor_mem

                app_id = str(step.get("app", "unknown"))
                key_id = str(step["key"])
                method = None
                point = None
                detail: dict[str, Any] = {}

                strict = bool(step.get("strict", False))
                v = anchor_mem.verify(app_id, key_id, win["hwnd"] if win else 0)
                detail["verify"] = v
                if v.get("ok"):
                    point = tuple(v["at"]); method = "anchor"
                elif (not strict and v.get("reason") == "hash" and v.get("at")
                      and int(v.get("distance", 99)) <= int(step.get("max_dist_soft", 32))):
                    # 外观会随状态变（输入框有字/没字、按钮亮/灰）：
                    # 位置仍在同一布局下，就把指纹当参考信号，点击后靠 expect 兜底
                    point = tuple(v["at"]); method = "anchor_soft"
                    detail["soft_reason"] = "visual state differs, position trusted"

                if point is None and step.get("fallback_text"):
                    res = ocr_ext.find_text(query=str(step["fallback_text"]),
                                            hwnd=(win["hwnd"] if win else None),
                                            min_lcs_share=float(step.get("min_lcs_share", 0.55)))
                    if res.get("found"):
                        m0 = res["matches"][0]
                        point = (m0["cx"], m0["cy"]); method = "ocr"
                        detail["ocr"] = {"text": m0["text"], "ratio": m0.get("ratio")}

                if point is None and step.get("fallback_rel") and win:
                    fp = _resolve_point({**step, "rel": step["fallback_rel"]}, win)
                    point = fp; method = "rel"

                if point is None:
                    entry["ok"] = False
                    entry["error"] = "记忆不可用且没有可用的降级方式"
                    entry["detail"] = detail
                    sub = {"ok": False}
                else:
                    mouse.position = point
                    _execution.sleep(0.05)   # hover 稳定余量
                    from pynput.mouse import Button as _Btn
                    mouse.click(_Btn.left, 1)
                    entry["ok"] = True
                    entry["method"] = method
                    entry["abs"] = list(point)
                    # 学到新位置（ocr/rel 成功时更新记忆）
                    if step.get("learn", True) and method in ("ocr", "rel"):
                        try:
                            detail["learned"] = anchor_mem.learn(app_id, key_id, win["hwnd"],
                                                                 int(point[0]), int(point[1]),
                                                                 note=f"auto via {method}")
                        except Exception as exc:
                            detail["learn_error"] = str(exc)
                    entry["detail"] = detail
                    sub = {"ok": True}
            elif action in ("page_check", "ensure_page"):
                # 阶段1画面 vs 阶段3画面 对账：
                #   page_check  -> 只报告（不一致也不动）
                #   ensure_page -> 不一致就执行 restore 步骤把页面切回阶段1的样子
                fp = _fingerprint(
                    win,
                    step.get("fingerprint") or step.get("expect_text") or [],
                    region=region,
                    min_lcs_share=float(step.get("min_lcs_share", 0.55)),
                    hwnd=(win["hwnd"] if win else None),
                )
                entry["fingerprint"] = fp
                if fp.get("ok"):
                    entry["ok"] = True
                    entry["page_state"] = "match"
                    sub = {"ok": True}
                elif action == "page_check":
                    entry["ok"] = False
                    entry["error"] = "页面与阶段1不一致（只报告，未改动）: 缺 %s" % fp.get("missing")
                    sub = {"ok": False}
                else:
                    restore = step.get("restore") or []
                    attempts = max(1, int(step.get("attempts", 2)))
                    log_tries = []
                    ok_now = False
                    for attempt in range(attempts):
                        if restore:
                            ui_ext.run_batch(restore, mouse, keyboard,
                                             stop_on_error=True, default_sleep_ms=120)
                        _execution.sleep(float(step.get("settle_ms", 1200)) / 1000.0)
                        again = _fingerprint(
                            win,
                            step.get("fingerprint") or step.get("expect_text") or [],
                            region=region,
                            min_lcs_share=float(step.get("min_lcs_share", 0.55)),
                            hwnd=(win["hwnd"] if win else None),
                        )
                        log_tries.append({"attempt": attempt, "ok": again.get("ok"),
                                          "missing": again.get("missing")})
                        if again.get("ok"):
                            ok_now = True
                            break
                    entry["restore_tries"] = log_tries
                    entry["ok"] = ok_now
                    entry["page_state"] = "restored" if ok_now else "unrecoverable"
                    if not ok_now:
                        entry["error"] = "无法切回阶段1的页面（指纹仍缺 %s）" % fp.get("missing")
                sub = {"ok": bool(entry.get("ok"))}
            elif action == "ensure_chat":
                from computer_mcp import ocr_ext

                title_q = str(step.get("title_query", ""))
                list_q = str(step.get("list_query", title_q))
                t_reg = step.get("title_region_rel")
                l_reg = step.get("list_region_rel")
                t_region = ({"x": win["x"] + int(t_reg[0]), "y": win["y"] + int(t_reg[1]),
                             "w": int(t_reg[2]), "h": int(t_reg[3])} if (t_reg and win) else None)
                l_region = ({"x": win["x"] + int(l_reg[0]), "y": win["y"] + int(l_reg[1]),
                             "w": int(l_reg[2]), "h": int(l_reg[3])} if (l_reg and win) else None)
                share = float(step.get("min_lcs_share", 0.55))
                title = ocr_ext.find_text(query=title_q, region=t_region,
                                          hwnd=(win["hwnd"] if win else None),
                                          min_lcs_share=share)
                if int(title.get("found") or 0) > 0:
                    entry["already_open"] = True
                    entry["title"] = (title.get("matches") or [{}])[0].get("text")
                    sub = {"ok": True}
                else:
                    entry["already_open"] = False
                    lst = ocr_ext.find_text(
                        query=list_q, region=l_region,
                        hwnd=(win["hwnd"] if win else None),
                        min_lcs_share=float(step.get("list_lcs_share", share)),
                    )
                    matches = lst.get("matches") or []
                    if not matches:
                        sub = {"ok": False, "error": f"chat {list_q!r} not found in the list"}
                    else:
                        from pynput.mouse import Button

                        idx = int(step.get("index", 0))
                        t = matches[idx] if idx < len(matches) else matches[0]
                        attempts = max(1, int(step.get("attempts", 3)))
                        settle = float(step.get("settle_ms", 420)) / 1000.0
                        got = False
                        tries: list[dict[str, Any]] = []
                        for attempt in range(attempts):
                            # the row toggles in WeChat: retry until the title shows up
                            dx = (-40, 40, 0)[attempt % 3]
                            mouse.position = (t["cx"] + dx, t["cy"])
                            _execution.sleep(0.10)
                            mouse.click(Button.left, 1)
                            _execution.sleep(settle)
                            again = ocr_ext.find_text(
                                query=title_q, region=t_region,
                                hwnd=(win["hwnd"] if win else None),
                                min_lcs_share=share,
                            )
                            got = int(again.get("found") or 0) > 0
                            tries.append({"attempt": attempt, "dx": dx, "opened": got})
                            if got:
                                break
                        entry["clicked"] = {"text": t["text"], "x": t["cx"], "y": t["cy"],
                                            "ratio": t.get("ratio")}
                        entry["attempts"] = tries
                        entry["title_verified"] = got
                        sub = {"ok": got}
                        if not got:
                            sub["error"] = f"chat did not open after {attempts} attempts"
            elif action in ("click_text", "find_text", "verify_text"):
                from computer_mcp import ocr_ext

                q = str(step.get("query", ""))
                res = ocr_ext.find_text(
                    query=q,
                    region=region,
                    hwnd=(win["hwnd"] if win else None),
                    min_ratio=float(step.get("min_ratio", 0.72)),
                    min_lcs_share=float(step.get("min_lcs_share", 0.6)),
                    upscale=float(step.get("upscale", 1.0)),
                    boost=bool(step.get("boost", False)),
                )
                found = int(res.get("found") or 0)
                entry["found"] = found
                if action == "verify_text":
                    sub = {"ok": found > 0}
                    if found == 0:
                        sub["error"] = f"text {q!r} not on screen"
                elif action == "click_text":
                    idx = int(step.get("index", 0))
                    matches = res.get("matches") or []
                    if found == 0:
                        sub = {"ok": False, "error": f"text {q!r} not found"}
                    elif idx >= len(matches):
                        sub = {"ok": False, "error": f"index {idx} out of range ({found} matches)"}
                    else:
                        t = matches[idx]
                        mouse.position = (t["cx"], t["cy"])
                        _execution.sleep(0.08)
                        from pynput.mouse import Button

                        mouse.click(Button.left, 1)
                        entry["clicked"] = {"text": t["text"], "x": t["cx"], "y": t["cy"],
                                            "ratio": t.get("ratio")}
                        sub = {"ok": True}
                else:
                    sub = {"ok": True}
                    entry["matches"] = (res.get("matches") or [])[:3]
            elif action == "close_windows":
                from computer_mcp import appkit as _app_c
                res = _app_c.close_windows(
                    process=str(step["process"]) if step.get("process") else None,
                    exe_contains=str(step["exe_contains"]) if step.get("exe_contains") else None,
                    title_contains=str(step["title_contains"]) if step.get("title_contains") else None,
                    exact_title=str(step["exact_title"]) if step.get("exact_title") else None,
                    wait_ms=int(step.get("wait_ms", 1500)),
                )
                entry["closed"] = res
                sub = {"ok": bool(res.get("ok"))}
                if not sub["ok"]:
                    sub["error"] = f"{res.get('still_open')} window(s) still open"

            elif action in ("learn_region", "learn_item"):
                from computer_mcp import anchor_mem as _am_l

                app_id = str(step.get("app", ""))
                key_id = str(step.get("key", ""))
                if not (app_id and key_id) or not win:
                    sub = {"ok": False, "error": "learn_* 需要 app/key 和已定位窗口"}
                elif action == "learn_region":
                    rg = _resolve_region({k: v for k, v in step.items() if k != "region_mem"}, win)
                    if not rg:
                        sub = {"ok": False, "error": "learn_region 需要 region_rel 或 region_mem"}
                    else:
                        res = _am_l.learn_region(app_id, key_id, win["hwnd"],
                                                 rg["x"], rg["y"], rg["w"], rg["h"],
                                                 note=str(step.get("note", "")))
                        entry["learned"] = res
                        sub = {"ok": bool(res.get("ok"))}
                        if not sub["ok"]:
                            sub["error"] = res.get("error")
                else:
                    p2 = _resolve_point(step, win)
                    if not p2:
                        sub = {"ok": False, "error": "learn_item 需要 x/y 或 rel"}
                    else:
                        res = _am_l.learn_item(app_id, key_id, win["hwnd"],
                                               int(step.get("index", 0)), p2[0], p2[1],
                                               note=str(step.get("note", "")))
                        entry["learned"] = res
                        sub = {"ok": bool(res.get("ok"))}
                        if not sub["ok"]:
                            sub["error"] = res.get("error")

            elif action in ("launch", "wait_window", "exit_app"):
                from computer_mcp import appkit as _app

                if action == "launch":
                    target = str(step.get("target") or step.get("name") or "")
                    res = _app.launch(target, settle_ms=int(step.get("settle_ms", 0)))
                    entry["launch"] = res
                    sub = {"ok": bool(res.get("ok"))}
                    if not sub["ok"]:
                        sub["error"] = res.get("error", "launch failed")

                elif action == "wait_window":
                    crit = {}
                    for k in ("process", "exe_contains", "title_contains", "class_contains"):
                        if step.get(k):
                            crit[k] = str(step[k])
                    res = _app.wait_window(timeout_ms=int(step.get("timeout_ms", 20000)),
                                           poll_ms=int(step.get("poll_ms", 300)), **crit)
                    entry["wait"] = {"ok": res.get("ok"), "elapsed_ms": res.get("elapsed_ms")}
                    if res.get("ok"):
                        w = res["window"]
                        entry["hwnd"] = w["hwnd"]
                        try:
                            _ensure_usable(w["hwnd"], restore=True)
                            win = {"hwnd": w["hwnd"], **_refresh_geometry(w["hwnd"])}
                            entry["abs_rect"] = win
                        except Exception as exc:
                            entry["geometry_error"] = str(exc)
                        sub = {"ok": True}
                    else:
                        sub = {"ok": False, "error": res.get("error", "wait_window timeout")}

                else:  # exit_app
                    res = _app.exit_app(
                        process=str(step["process"]) if step.get("process") else None,
                        exe_contains=str(step["exe_contains"]) if step.get("exe_contains") else None,
                        timeout_ms=int(step.get("timeout_ms", 8000)),
                        force=bool(step.get("force", True)),
                    )
                    entry["exit"] = res
                    sub = {"ok": bool(res.get("ok"))}
                    if not sub["ok"]:
                        sub["error"] = f"still running: {res.get('pids_after')}"

            # ---- vision state（通用：自绘 UI / 游戏 / Electron 都能用）----
            elif action in ("capture_template", "assert_template", "set_baseline",
                            "assert_baseline", "wait_template", "sample_stable", "hover_probe"):
                from computer_mcp import vision_state as _vs

                region = _resolve_region(step, win) if (step.get("region_rel") or step.get("region_mem")) else None
                hw = win["hwnd"] if win else None
                nm = str(step.get("name") or step.get("template") or "").strip()
                if action in ("capture_template", "set_baseline") and not (nm and region):
                    step_result = {"ok": False, "error": f"{action} 需要 name + region_rel"}
                elif action == "capture_template":
                    step_result = _vs.capture_template(nm, region, hwnd=hw)
                    step_result = {"ok": bool(step_result.get("success")), **step_result}
                elif action == "set_baseline":
                    step_result = _vs.set_baseline(nm, region, hwnd=hw)
                    step_result = {"ok": bool(step_result.get("success")), **step_result}
                elif action == "assert_template":
                    r = _vs.match_template(nm, region=region, hwnd=hw,
                                           confidence=float(step.get("confidence", 0.8)))
                    want = not bool(step.get("absent", False))
                    ok = bool(r.get("found")) == want and bool(r.get("success"))
                    step_result = {"ok": ok, "found": r.get("found"), "score": r.get("score"),
                                   "expected_present": want, "match": r if not ok else None}
                elif action == "wait_template":
                    r = _vs.wait_template(nm, timeout_ms=int(step.get("timeout_ms", 5000)),
                                          appear=not bool(step.get("absent", False)),
                                          confidence=float(step.get("confidence", 0.8)),
                                          region=region, hwnd=hw)
                    step_result = {"ok": bool(r.get("matched")), **r}
                elif action == "assert_baseline":
                    r = _vs.diff_baseline(nm, region=region, hwnd=hw,
                                          threshold=float(step.get("threshold", 8.0)))
                    want = bool(step.get("changed", True))
                    ok = bool(r.get("success")) and bool(r.get("changed")) == want
                    step_result = {"ok": ok, **r}
                elif action == "sample_stable":
                    r = _vs.sample_stable(region=region, hwnd=hw,
                                          times=int(step.get("times", 2)),
                                          gap_ms=int(step.get("gap_ms", 200)))
                    want = bool(step.get("stable", True))
                    step_result = {"ok": bool(r.get("success")) and bool(r.get("stable")) == want, **r}
                else:  # hover_probe
                    pt = _resolve_point(step, win)
                    if not pt or not region:
                        step_result = {"ok": False, "error": "hover_probe 需要 rel 坐标 + region_rel"}
                    else:
                        away = None
                        if step.get("away_rel") and win:
                            aw = {"rel": step["away_rel"]}
                            away = _resolve_point(aw, win)
                        r = _vs.hover_probe(pt[0], pt[1], region=region, hwnd=hw,
                                            dwell_ms=int(step.get("dwell_ms", 400)),
                                            threshold=float(step.get("threshold", 3.0)),
                                            away=away, mouse=mouse_controller)
                        want = step.get("revealed")
                        ok = bool(r.get("success")) and (want is None or bool(r.get("revealed")) == bool(want))
                        step_result = {"ok": ok, **r}
            elif action == "hotkey":
                # 组合键：{"action":"hotkey","keys":["ctrl","a"]}
                keys = step.get("keys") or []
                if isinstance(keys, str):
                    keys = [k.strip() for k in keys.split("+") if k.strip()]
                resolved = [ui_ext.resolve_key(str(k)) for k in keys]
                for k in resolved:
                    keyboard.press(k)
                _execution.sleep(float(step.get("hold_ms", 40)) / 1000.0)
                for k in reversed(resolved):
                    keyboard.release(k)
                _execution.sleep(float(step.get("settle_ms", 120)) / 1000.0)
                entry["keys"] = keys
                sub = {"ok": bool(resolved)}

            elif action in ("clipboard_set", "clipboard_get", "paste",
                            "assert_title", "assert_file", "assert_text"):

                if action == "clipboard_set":
                    txt = str(step.get("text", ""))
                    _execution.checkpoint('macro_run')
                    _write_clipboard(txt)
                    entry["chars"] = len(txt)
                    sub = {"ok": True}

                elif action == "clipboard_get":
                    val = _clipboard_text() or ''
                    need = step.get("contains")
                    entry, sub = _clipboard_observation(val, need)

                elif action == "paste":
                    from computer_mcp import permission, capabilities
                    txt = str(step.get("text", ""))
                    previous = None
                    sequence = None
                    if not capabilities.has_scope('clipboard_read'):
                        raise permission.PermissionDenied('Macro paste requires clipboard_read')
                    if txt:
                        if not capabilities.has_scope('clipboard_write'):
                            raise permission.PermissionDenied('Macro action requires clipboard_write')
                        _execution.checkpoint('macro_run')
                        previous = _clipboard_text()
                        sequence = _write_clipboard(txt)
                        _execution.sleep(0.15)
                    _ctrl = ui_ext.resolve_key("ctrl")
                    _v = ui_ext.resolve_key("v")
                    keyboard.press(_ctrl); keyboard.press(_v)
                    keyboard.release(_v); keyboard.release(_ctrl)
                    _execution.sleep(float(step.get("settle_ms", 700)) / 1000.0)
                    entry["chars"] = len(txt)
                    if txt and sequence is not None:
                        entry["clipboard_restored"] = _restore_clipboard(previous, sequence)
                    sub = {"ok": True}

                elif action == "assert_title":
                    import win32gui as _wg
                    need = str(step.get("contains", step.get("query", "")))
                    hw = (win["hwnd"] if win else _wg.GetForegroundWindow())
                    title = _wg.GetWindowText(hw)
                    entry["title"] = title
                    ok_t = need in title
                    sub = {"ok": ok_t}
                    if not ok_t:
                        sub["error"] = f"window title {title!r} does not contain {need!r}"

                elif action == "assert_file":
                    path = str(step.get("path", ""))
                    need = step.get("contains")
                    from computer_mcp.workspace import readable_path, read_text
                    path = str(readable_path(path))
                    exists = os.path.isfile(path)
                    entry["exists"] = exists
                    entry["path"] = path
                    ok_f = exists
                    if exists and need:
                        try:
                            content = read_text(path, encoding=str(step.get("encoding", "utf-8")))
                            ok_f = str(need) in content
                            entry["contains"] = bool(ok_f)
                        except Exception as exc:
                            ok_f = False
                            entry["error_detail"] = str(exc)
                    sub = {"ok": ok_f}
                    if not ok_f:
                        sub["error"] = f"assert_file failed (exists={exists}) {path!r}"

                else:  # assert_text
                    from computer_mcp import ocr_ext as _ocr
                    q2 = str(step.get("query", step.get("contains", "")))
                    res2 = _ocr.find_text(
                        query=q2,
                        region=region,
                        hwnd=(win["hwnd"] if win else None),
                        min_ratio=float(step.get("min_ratio", 0.72)),
                        min_lcs_share=float(step.get("min_lcs_share", 0.6)),
                        upscale=float(step.get("upscale", 1.0)),
                        boost=bool(step.get("boost", False)),
                    )
                    found2 = int(res2.get("found") or 0)
                    entry["found"] = found2
                    forbidden = step.get("absent")
                    ok_a = found2 > 0
                    if forbidden:
                        res3 = _ocr.find_text(query=str(forbidden), region=region,
                                              hwnd=(win["hwnd"] if win else None),
                                              min_lcs_share=float(step.get("min_lcs_share", 0.6)))
                        if int(res3.get("found") or 0) > 0:
                            ok_a = False
                            entry["absent_violation"] = str(forbidden)
                    sub = {"ok": ok_a}
                    if not ok_a:
                        sub["error"] = (f"assert_text: {q2!r} not found"
                                        if found2 == 0 else
                                        f"assert_text: {forbidden!r} should be absent but found")
            else:
                sub = {"ok": False, "error": f"unknown macro action {action!r}"}

            entry["ok"] = bool(sub.get("ok", True))
            if sub.get("result"):
                entry["result"] = sub["result"]

            # 记忆库自动更新：凡带 app/key 的步骤都记账（anchor_click 自己已管，跳过避免重复计数）
            _app = step.get("app")
            _key = step.get("key")
            if _app and _key and action != "anchor_click":
                try:
                    from computer_mcp import anchor_mem as _am_upd
                    _am_upd.confirm(str(_app), str(_key), bool(entry["ok"]))
                    entry["memory_updated"] = bool(entry["ok"])
                except Exception:
                    pass

            expect = step.get("expect")
            if entry["ok"] and expect:
                want = bool(expect.get("changed", True))
                timeout = int(expect.get("timeout_ms", 1500))
                ch = capture_core.wait_for_change(timeout_ms=timeout, poll_ms=120)
                got = bool(ch.get("changed"))
                entry["expect"] = {"wanted": want, "got": got, "diff": ch.get("diff")}
                if got != want:
                    entry["ok"] = False
                    entry["error"] = f"expectation failed (wanted changed={want}, got {got})"

        except Exception as exc:
            entry["ok"] = False
            entry["error"] = f"{type(exc).__name__}: {exc}"

        entry["ms"] = round((time.perf_counter() - t0) * 1000, 1)
        log.append(entry)
        if not entry["ok"]:
            tries = int(step.get("_tries", 0)) + 1
            max_tries = 1 if action == 'guarded_click' else max(1, int(step.get("retry", 1)))
            if tries < max_tries:
                step["_tries"] = tries
                entry["retrying"] = f"{tries}/{max_tries}"
                queue.insert(0, (i, step))
                rgap = int(step.get("retry_gap_ms", 400))
                if rgap > 0:
                    _execution.sleep(rgap / 1000.0)
                continue
            failed += 1
            break

        gap = int(step.get("gap_ms", default_gap_ms))
        if action not in ("sleep", "wait_change") and gap > 0:
            _execution.sleep(gap / 1000.0)

    return {
        "ok": failed == 0,
        "macro": spec.get("name", name),
        "window": win,
        "steps_run": len(log),
        "failed": failed,
        "total_ms": round((time.perf_counter() - t_all) * 1000, 1),
        "log": log,
    }
