"""Batch execution and UI-Automation helpers for the Shell desktop MCP patch.

Two problems this solves:
  1. Every model-side tool call costs a full round trip (seconds). run_batch()
     collapses a whole gesture (move/click/type/wait) into ONE MCP call.
  2. Clicking by pixel coordinates is fragile. The ui_* helpers find a control
     by its accessible name and click its centre, so a wrong click is unlikely.

All mouse movement still goes through pynput, i.e. it really moves the cursor.
"""

from __future__ import annotations

import time
from typing import Any

try:
    import uiautomation as auto

    _UIA_OK = True
except Exception:  # pragma: no cover - uiautomation is optional
    auto = None
    _UIA_OK = False


# --------------------------------------------------------------------------- #
# UI Automation
# --------------------------------------------------------------------------- #
def _control_from(hwnd: int | None):
    if not _UIA_OK:
        return None
    if hwnd:
        try:
            return auto.ControlFromHandle(hwnd)
        except Exception:
            return None
    try:
        return auto.GetForegroundControl()
    except Exception:
        return None


def _walk(ctrl, depth, out, max_nodes, only_named=False):
    if len(out) >= max_nodes:
        return
    try:
        children = ctrl.GetChildren()
    except Exception:
        return
    for c in children:
        if len(out) >= max_nodes:
            return
        try:
            name = (c.Name or "").strip()
            rect = c.BoundingRectangle
            ctype = c.ControlTypeName
            if not only_named or name:
                out.append(
                    {
                        "type": ctype,
                        "name": name,
                        "x": int(rect.left),
                        "y": int(rect.top),
                        "w": int(rect.width()),
                        "h": int(rect.height()),
                    }
                )
        except Exception:
            continue
        if depth > 0:
            _walk(c, depth - 1, out, max_nodes, only_named)


def ui_tree(hwnd: int | None = None, depth: int = 3, max_nodes: int = 60, only_named: bool = True) -> dict[str, Any]:
    """Compact control tree of a window (or the foreground window). No screenshot."""
    if not _UIA_OK:
        return {"error": "uiautomation not installed in this venv"}
    t0 = time.perf_counter()
    root = _control_from(hwnd)
    if root is None:
        return {"error": "could not resolve window", "hwnd": hwnd}
    out: list[dict[str, Any]] = []
    _walk(root, max(0, int(depth)), out, max(1, int(max_nodes)), bool(only_named))
    return {
        "ok": True,
        "hwnd": hwnd,
        "window": (root.Name or "").strip(),
        "count": len(out),
        "nodes": out,
        "ms": round((time.perf_counter() - t0) * 1000, 1),
    }


def ui_find(
    name: str,
    hwnd: int | None = None,
    depth: int = 8,
    max_nodes: int = 400,
    exact: bool = False,
    index: int = 0,
) -> dict[str, Any]:
    """Find controls whose Name matches; returns candidates with centre points."""
    if not _UIA_OK:
        return {"error": "uiautomation not installed in this venv"}
    t0 = time.perf_counter()
    root = _control_from(hwnd)
    if root is None:
        return {"error": "could not resolve window", "hwnd": hwnd}
    out: list[dict[str, Any]] = []
    _walk(root, max(0, int(depth)), out, max_nodes, only_named=True)
    needle = name.casefold()
    hits = []
    for node in out:
        n = node["name"].casefold()
        if (n == needle) if exact else (needle in n):
            node = dict(node)
            node["cx"] = node["x"] + node["w"] // 2
            node["cy"] = node["y"] + node["h"] // 2
            hits.append(node)
    return {
        "ok": True,
        "found": len(hits),
        "index": index,
        "target": hits[index] if index < len(hits) else None,
        "candidates": hits[:10],
        "ms": round((time.perf_counter() - t0) * 1000, 1),
    }


def _resolve(hwnd, name, exact, index):
    res = ui_find(name=name, hwnd=hwnd, exact=exact, index=index)
    if not res.get("ok"):
        return None, res
    target = res.get("target")
    if not target:
        return None, {"error": f"no control named {name!r}", "candidates": res.get("candidates")}
    return target, res


def ui_click(
    name: str,
    hwnd: int | None = None,
    exact: bool = False,
    index: int = 0,
    button: str = "left",
    mouse=None,
    settle_ms: int = 250,
) -> dict[str, Any]:
    """Move the real cursor to a control's centre and click it."""
    target, res = _resolve(hwnd, name, exact, index)
    if target is None:
        return res
    if mouse is None:
        return {"error": "mouse controller not provided"}
    t0 = time.perf_counter()
    mouse.position = (target["cx"], target["cy"])
    time.sleep(0.06)
    mouse.click(
        {"left": mouse_button_left(), "right": None, "middle": None}.get(button) or mouse_button_left()
    )
    time.sleep(max(0, settle_ms) / 1000.0)
    return {
        "ok": True,
        "clicked": {"name": target["name"], "type": target["type"], "x": target["cx"], "y": target["cy"]},
        "ms": round((time.perf_counter() - t0) * 1000, 1),
    }


def mouse_button_left():
    from pynput.mouse import Button

    return Button.left


def ui_invoke(name: str, hwnd: int | None = None, exact: bool = False, index: int = 0) -> dict[str, Any]:
    """Trigger a control's Invoke pattern without moving the cursor."""
    if not _UIA_OK:
        return {"error": "uiautomation not installed in this venv"}
    target, res = _resolve(hwnd, name, exact, index)
    if target is None:
        return res
    ctrl = None
    root = _control_from(hwnd)
    if root is not None:
        queue = [root]
        needle = name.casefold()
        while queue:
            c = queue.pop(0)
            try:
                n = (c.Name or "").strip().casefold()
                if ((n == needle) if exact else (needle in n)) and n:
                    ctrl = c
                    break
                queue.extend(c.GetChildren())
            except Exception:
                continue
    if ctrl is None:
        return {"error": "control vanished before invoke"}
    try:
        ctrl.GetInvokePattern().Invoke()
    except Exception as exc:
        return {"error": f"invoke failed: {exc}", "hint": "use ui_click instead"}
    return {"ok": True, "invoked": target["name"]}


def ui_set_text(name: str, text: str, hwnd: int | None = None, exact: bool = False, index: int = 0) -> dict[str, Any]:
    """Set a control's value through the Value pattern (no typing)."""
    if not _UIA_OK:
        return {"error": "uiautomation not installed in this venv"}
    target, res = _resolve(hwnd, name, exact, index)
    if target is None:
        return res
    root = _control_from(hwnd)
    if root is None:
        return {"error": "could not resolve window"}
    needle = name.casefold()
    queue = [root]
    while queue:
        c = queue.pop(0)
        try:
            n = (c.Name or "").strip().casefold()
            if ((n == needle) if exact else (needle in n)) and n:
                try:
                    c.GetValuePattern().SetValue(text)
                    return {"ok": True, "set": text, "target": target["name"]}
                except Exception:
                    try:
                        c.GetValuePattern().SetValue(text)
                    except Exception as exc:
                        return {"error": f"value pattern failed: {exc}", "hint": "focus it and use type"}
            queue.extend(c.GetChildren())
        except Exception:
            continue
    return {"error": "control vanished before set"}


# --------------------------------------------------------------------------- #
# Batch execution
# --------------------------------------------------------------------------- #
def resolve_key(name: str):
    """Map a friendly key name to a pynput key object (pynput rejects plain strings)."""
    from pynput.keyboard import Key

    n = str(name or "").strip().lower()
    table = {
        "enter": Key.enter, "return": Key.enter, "tab": Key.tab, "esc": Key.esc,
        "escape": Key.esc, "space": Key.space, "backspace": Key.backspace,
        "delete": Key.delete, "del": Key.delete, "home": Key.home, "end": Key.end,
        "up": Key.up, "down": Key.down, "left": Key.left, "right": Key.right,
        "pageup": Key.page_up, "pagedown": Key.page_down,
        "f1": Key.f1, "f2": Key.f2, "f3": Key.f3, "f4": Key.f4, "f5": Key.f5,
        "f6": Key.f6, "f7": Key.f7, "f8": Key.f8, "f9": Key.f9, "f10": Key.f10,
        "f11": Key.f11, "f12": Key.f12,
        # 修饰键（组合键会用到：alt+left / ctrl+a / shift+tab）
        "alt": Key.alt, "ctrl": Key.ctrl, "control": Key.ctrl,
        "shift": Key.shift, "win": Key.cmd, "cmd": Key.cmd,
        "alt_l": Key.alt_l, "alt_r": Key.alt_r,
        "ctrl_l": Key.ctrl_l, "ctrl_r": Key.ctrl_r,
        "shift_l": Key.shift_l, "shift_r": Key.shift_r,
    }
    if n in table:
        return table[n]
    if len(n) == 1:
        return n
    raise ValueError(f"unknown key name: {name!r}")


def run_batch(
    steps: list[dict[str, Any]],
    mouse,
    keyboard,
    stop_on_error: bool = True,
    default_sleep_ms: int = 120,
    max_steps: int = 80,
) -> dict[str, Any]:
    """Execute a sequence of gestures in a single call.

    Step shapes (action is required):
      {"action":"move","x":..,"y":..}
      {"action":"click"|"double_click"|"right_click"}
      {"action":"type","text":".."}
      {"action":"key","key":"enter"}
      {"action":"sleep","ms":300}
      {"action":"wait_change","timeout_ms":3000}
      {"action":"screen_state"}
      {"action":"ui_click","name":"发送","hwnd":123}
    """
    from computer_mcp.core import screenshot as capture_core

    t_all = time.perf_counter()
    log: list[dict[str, Any]] = []
    failures = 0

    for i, raw in enumerate(steps[: max(1, int(max_steps))]):
        step = dict(raw or {})
        action = str(step.get("action", "")).strip().lower()
        t0 = time.perf_counter()
        entry: dict[str, Any] = {"i": i, "action": action}
        try:
            if action == "move":
                mouse.position = (int(step["x"]), int(step["y"]))
                entry["ok"] = True
            elif action == "click":
                _click(mouse, step)
                entry["ok"] = True
            elif action == "double_click":
                _click(mouse, step, 2)
                entry["ok"] = True
            elif action == "right_click":
                _click(mouse, step, 1, right=True)
                entry["ok"] = True
            elif action == "type":
                keyboard.type(str(step.get("text", "")))
                entry["ok"] = True
                entry["chars"] = len(str(step.get("text", "")))
            elif action == "key":
                key = resolve_key(str(step.get("key", "enter")))
                keyboard.press(key)
                keyboard.release(key)
                entry["ok"] = True
            elif action == "sleep":
                ms = int(step.get("ms", default_sleep_ms))
                time.sleep(ms / 1000.0)
                entry["ok"] = True
                entry["slept_ms"] = ms
            elif action == "wait_change":
                res = capture_core.wait_for_change(
                    timeout_ms=int(step.get("timeout_ms", 3000)),
                    poll_ms=int(step.get("poll_ms", 120)),
                )
                entry["ok"] = True
                entry["result"] = res
            elif action == "screen_state":
                entry["ok"] = True
                entry["result"] = capture_core.screen_state()
            elif action == "ui_click":
                res = ui_click(
                    name=str(step["name"]),
                    hwnd=step.get("hwnd"),
                    exact=bool(step.get("exact", False)),
                    index=int(step.get("index", 0)),
                    mouse=mouse,
                    settle_ms=int(step.get("settle_ms", 250)),
                )
                entry["ok"] = bool(res.get("ok"))
                entry["result"] = res
                if not entry["ok"]:
                    failures += 1
            else:
                entry["ok"] = False
                entry["error"] = f"unknown action {action!r}"
                failures += 1
        except Exception as exc:
            entry["ok"] = False
            entry["error"] = f"{type(exc).__name__}: {exc}"
            failures += 1

        entry["ms"] = round((time.perf_counter() - t0) * 1000, 1)
        log.append(entry)

        if not entry.get("ok") and stop_on_error:
            break
        if action not in ("sleep", "wait_change") and int(step.get("gap_ms", default_sleep_ms)) > 0:
            time.sleep(int(step.get("gap_ms", default_sleep_ms)) / 1000.0)

    return {
        "ok": failures == 0,
        "steps_run": len(log),
        "failed": failures,
        "total_ms": round((time.perf_counter() - t_all) * 1000, 1),
        "log": log,
    }


def _click(mouse, step, count=1, right=False):
    from pynput.mouse import Button

    if "x" in step and "y" in step:
        mouse.position = (int(step["x"]), int(step["y"]))
    btn = Button.right if (right or str(step.get("button", "")).lower() == "right") else Button.left
    mouse.click(btn, int(count))
