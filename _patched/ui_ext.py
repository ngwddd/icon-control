"""Batch execution and UI-Automation helpers for the DSH desktop MCP patch.

Two problems this solves:
  1. Every model-side tool call costs a full round trip (seconds). run_batch()
     collapses a whole gesture (move/click/type/wait) into ONE MCP call.
  2. Clicking by pixel coordinates is fragile. The ui_* helpers find a control
     by its accessible name and click its centre, so a wrong click is unlikely.

All mouse movement still goes through pynput, i.e. it really moves the cursor.
"""

from __future__ import annotations

import time
from computer_mcp import execution as _execution
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


# ── P0-2：进程排除表 ──────────────────────────────────────────────────
def _proc_name(hwnd) -> str:
    """窗口所属进程名（不含路径）。拿不到返回空串。"""
    try:
        import ctypes
        import ctypes.wintypes as wt

        pid = wt.DWORD(0)
        ctypes.windll.user32.GetWindowThreadProcessId(int(hwnd), ctypes.byref(pid))
        if not pid.value:
            return ""
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid.value)
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(600)
            size = wt.DWORD(600)
            if ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return buf.value.rsplit("\\", 1)[-1]
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    except Exception:                                   # noqa: BLE001
        return ""
    return ""


def excluded_processes() -> set:
    """DSH_UI_EXCLUDE_PROCESSES=Code.exe,Cursor.exe（大小写不敏感）。"""
    import os

    raw = os.environ.get("DSH_UI_EXCLUDE_PROCESSES", "") or ""
    return {x.strip().lower() for x in raw.split(",") if x.strip()}


def is_excluded(hwnd) -> tuple:
    """返回 (是否排除, 进程名)。"""
    name = _proc_name(hwnd).lower()
    return (bool(name) and name in excluded_processes()), name


def _element_id(ctype: str, name: str, pos: tuple) -> str:
    import hashlib

    raw = f"{ctype}|{name}|{pos[0]},{pos[1]},{pos[2]},{pos[3]}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]


def _walk(ctrl, depth, out, max_nodes, only_named=False, prefix="",
          *, want_id=True, stop_at=None, accept=None, budget=None):
    """Collect controls depth-first.

    ``accept`` filters during the walk, so a caller looking for one control does
    not pay for a full tree. ``stop_at`` stops as soon as that many controls were
    collected.

    ``budget`` is a mutable ``{"left": n}`` counter of nodes actually visited.
    It is separate from ``len(out)`` on purpose: with a filter, ``out`` only grows
    on matches, so a miss would otherwise walk the whole tree no matter what
    ``max_nodes`` says. ``want_id=False`` skips the AutomationId read for nodes
    that are not collected; collected nodes always carry it, because a reference
    without an id cannot be told apart from a different control with the same
    name, type and path.
    """
    if budget is not None and budget.get("left", 0) <= 0:
        return
    if accept is None and len(out) >= max_nodes:
        return
    if stop_at is not None and len(out) >= stop_at:
        return
    # Enumerate siblings one at a time instead of materialising GetChildren():
    # with a budget, the remaining siblings of a wide parent must never be
    # created at all (a 900-item list would otherwise be built to read 50).
    try:
        if hasattr(ctrl, "GetFirstChildControl") and hasattr(ctrl, "GetNextSiblingControl"):
            children = _iter_children(ctrl, budget)
        else:
            children = iter(ctrl.GetChildren())
    except Exception:
        if budget is not None:
            budget["errors"] = budget.get("errors", 0) + 1
        return
    for index, c in enumerate(children):
        if budget is not None:
            if budget["left"] <= 0:
                return
            budget["left"] -= 1
        if accept is None and len(out) >= max_nodes:
            return
        if stop_at is not None and len(out) >= stop_at:
            return
        # The child-index chain is what element references re-resolve against:
        # it survives a moving window, unlike the geometry-based element_id.
        path = f"{prefix}/{index}" if prefix else str(index)
        try:
            name = (c.Name or "").strip()
            rect = c.BoundingRectangle
            ctype = c.ControlTypeName
            if not only_named or name:
                pos = (int(rect.left), int(rect.top),
                       int(rect.width()), int(rect.height()))
                if accept is not None and not accept(c, ctype, name, pos):
                    pass
                else:
                    automation_id = ""
                    # Collected nodes (including the few filtered hits) always get
                    # an id; only the bulk walk can skip it.
                    if want_id or accept is not None:
                        try:
                            automation_id = (c.AutomationId or "").strip()
                        except Exception:               # noqa: BLE001
                            automation_id = ""
                    out.append(
                        {
                            "type": ctype,
                            "name": name,
                            "automation_id": automation_id,
                            "x": pos[0],
                            "y": pos[1],
                            "w": pos[2],
                            "h": pos[3],
                            "path": path,
                            # P0-3：稳定元素 id（类型+名字+几何），后续可按 id 点击，
                            # 避免同名控件点错（"确定" 在对话框里到处都是）
                            "element_id": _element_id(ctype, name, pos),
                        }
                    )
        except Exception:
            if budget is not None:
                budget["errors"] = budget.get("errors", 0) + 1
            continue
        if depth > 0:
            _walk(c, depth - 1, out, max_nodes, only_named, path,
                  want_id=want_id, stop_at=stop_at, accept=accept, budget=budget)
        elif budget is not None:
            # The frontier was not expanded: if it has children, controls below it
            # were never looked at, so the scan cannot prove a target is absent.
            try:
                if c.GetFirstChildControl() is not None:
                    budget["depth_cut"] = True
            except Exception:                           # noqa: BLE001
                budget["errors"] = budget.get("errors", 0) + 1


def _iter_children(control, budget=None):
    """Yield children lazily; stop as soon as the visitor's budget is spent.

    ``GetChildren()`` walks every sibling before returning, so a caller that only
    needs the first fifty of a nine-hundred item list paid for all of them.
    """
    try:
        child = control.GetFirstChildControl()
    except Exception:                                   # noqa: BLE001
        if budget is not None:
            budget["errors"] = budget.get("errors", 0) + 1
        return
    while child is not None:
        if budget is not None and budget.get("left", 0) <= 0:
            return
        yield child
        try:
            child = child.GetNextSiblingControl()
        except Exception:                               # noqa: BLE001
            if budget is not None:
                budget["errors"] = budget.get("errors", 0) + 1
            return


def _control_obj_at_path(hwnd: int, path: str):
    """The raw UIA object for one control (pattern work needs the object itself)."""
    if not _UIA_OK:
        raise RuntimeError("uiautomation not installed in this venv")
    root = _control_from(hwnd)
    if root is None:
        return None
    node = root
    for part in [p for p in str(path).split('/') if p]:
        try:
            index = int(part)
        except ValueError:
            return None
        children = node.GetChildren()
        if index < 0 or index >= len(children):
            return None
        node = children[index]
    return node


def control_at_path(hwnd: int, path: str) -> dict[str, Any] | None:
    """Re-read one control by its child-index chain (used to refresh a reference)."""
    if not _UIA_OK:
        raise RuntimeError("uiautomation not installed in this venv")
    root = _control_from(hwnd)
    if root is None:
        return None
    node = root
    for part in [p for p in str(path).split('/') if p]:
        try:
            index = int(part)
        except ValueError:
            return None
        children = node.GetChildren()
        if index < 0 or index >= len(children):
            return None
        node = children[index]
    rect = node.BoundingRectangle
    return {
        "type": node.ControlTypeName,
        "name": (node.Name or "").strip(),
        "automation_id": (getattr(node, "AutomationId", "") or "").strip(),
        "x": int(rect.left),
        "y": int(rect.top),
        "w": int(rect.width()),
        "h": int(rect.height()),
        "path": str(path),
    }


def ui_tree(hwnd: int | None = None, depth: int = 3, max_nodes: int = 60,
            only_named: bool = True, with_ids: bool = True) -> dict[str, Any]:
    """Compact control tree of a window (or the foreground window). No screenshot."""
    if not _UIA_OK:
        return {"error": "uiautomation not installed in this venv"}
    t0 = time.perf_counter()
    skip, proc = is_excluded(hwnd) if hwnd else (False, "")
    if skip:
        return {"error": f"进程 {proc} 在排除表里（DSH_UI_EXCLUDE_PROCESSES），跳过 UIA 遍历",
                "hwnd": hwnd, "excluded": True}
    root = _control_from(hwnd)
    if root is None:
        return {"error": "could not resolve window", "hwnd": hwnd}
    if not proc:
        proc = _proc_name(hwnd)
    out: list[dict[str, Any]] = []
    _walk(root, max(0, int(depth)), out, max(1, int(max_nodes)),
          bool(only_named), want_id=bool(with_ids))
    snapshot = {}
    try:
        import win32gui
        from computer_mcp import snapshots
        hwnd = hwnd or win32gui.GetForegroundWindow()
        snapshot = snapshots.attach(hwnd, out)
        out = snapshot.pop('candidates')
    except Exception as exc:
        snapshot = {'snapshot_error': str(exc)}
    return {
        **snapshot,
        "ok": True,
        "hwnd": hwnd,
        "process": proc,
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
    *,
    control_type: str | None = None,
    automation_id: str | None = None,
    enabled: bool | None = None,
    max_hits: int = 10,
) -> dict[str, Any]:
    """Find controls by name, optionally narrowed by type, id or enabled state.

    The match happens **during** the walk. Two separate limits apply:
    ``max_nodes`` caps how many controls are visited (so a miss still stops),
    ``max_hits`` caps how many matches are collected. When it stops early the
    result carries ``truncated: true`` plus ``truncated_reason`` — ``found`` is
    then a lower bound, not a total.

    ``index`` is honoured even when it is larger than ``max_hits``: the effective
    hit limit is at least ``index + 1``, otherwise "give me the 12th match" would
    silently return nothing.
    """
    if not _UIA_OK:
        return {"error": "uiautomation not installed in this venv"}
    t0 = time.perf_counter()
    root = _control_from(hwnd)
    if root is None:
        return {"error": "could not resolve window", "hwnd": hwnd}
    needle = name.casefold()
    type_needle = (control_type or "").casefold()
    id_needle = (automation_id or "").casefold()

    def accept(control, ctype, cname, pos):        # noqa: ARG001 - pos unused
        folded = cname.casefold()
        if (folded == needle) if exact else (needle in folded):
            pass
        else:
            return False
        if type_needle and type_needle not in ctype.casefold():
            return False
        if id_needle:
            try:
                if id_needle not in (control.AutomationId or "").casefold():
                    return False
            except Exception:                       # noqa: BLE001
                return False
        if enabled is not None:
            try:
                if bool(control.IsEnabled) != bool(enabled):
                    return False
            except Exception:                       # noqa: BLE001
                return False
        return True

    safe_index = max(0, int(index))
    limit = max(1, int(max_hits), safe_index + 1)
    budget = {"left": max(1, int(max_nodes)), "errors": 0}
    hits: list[dict[str, Any]] = []
    # The library's own FindFirst wrapper (Control(SubName=...)) polls with a 10 s
    # timeout and stalls even when the control exists, so the walk stays the only
    # path here. Measured: 10.0 s for a miss, 10.0 s for a hit at depth 16.
    _walk(root, max(0, int(depth)), hits, max_nodes, only_named=True,
          stop_at=limit, accept=accept, budget=budget)
    visited = max(1, int(max_nodes)) - budget["left"]
    hit_limit_reached = len(hits) >= limit
    node_limit_reached = budget["left"] <= 0
    truncated = hit_limit_reached or node_limit_reached
    truncated_reason = ("max_hits" if hit_limit_reached
                        else "max_nodes" if node_limit_reached else None)
    scan_errors = int(budget.get("errors", 0) or 0)
    depth_cut = bool(budget.get("depth_cut", False))
    # "Complete" means the whole configured area was read: no budget stop, no read
    # failure, and no unexplored frontier. A depth-limited search that stopped at
    # nodes which still have children proves nothing about what is underneath.
    scan_complete = (not truncated) and scan_errors == 0 and not depth_cut
    for node in hits:
        node["cx"] = node["x"] + node["w"] // 2
        node["cy"] = node["y"] + node["h"] // 2
    return {
        "ok": True,
        "found": len(hits),
        "truncated": truncated,
        "truncated_reason": truncated_reason,
        "visited": visited,
        "scan_complete": scan_complete,
        "scan_errors": scan_errors,
        "depth_truncated": depth_cut,
        "index": safe_index,
        "target": hits[safe_index] if safe_index < len(hits) else None,
        "candidates": hits[:10],
        "ms": round((time.perf_counter() - t0) * 1000, 1),
    }


def find_by_element_id(element_id: str, hwnd: int | None = None,
                       depth: int = 8, max_nodes: int = 600):
    """P0-3：按 element_id 找回控件（比名字匹配稳）。"""
    tree = ui_tree(hwnd=hwnd, depth=depth, max_nodes=max_nodes, only_named=False)
    if not tree.get("ok"):
        return None, tree
    hit = next((n for n in tree.get("nodes", []) if n.get("element_id") == element_id), None)
    if hit is None:
        return None, {"error": f"没有 element_id={element_id}", "count": tree.get("count")}
    hit = dict(hit)
    hit["cx"] = hit["x"] + hit["w"] // 2
    hit["cy"] = hit["y"] + hit["h"] // 2
    return hit, tree


def _resolve(hwnd, name, exact, index):
    if int(index) < 0:
        return None, {'error': 'Negative candidate indexes are not allowed'}
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
    element_id: str | None = None,
    ref: str | None = None,
) -> dict[str, Any]:
    """Move the real cursor to a control's centre and click it.

    P0-3：给了 element_id 就按 id 定位（优先），不再靠名字匹配。
    """
    if ref:
        from computer_mcp.snapshots import resolve
        target = resolve(ref, hwnd)
        hwnd = target['hwnd']
        res = {}
    elif element_id:
        target, res = find_by_element_id(str(element_id), hwnd=hwnd)
    else:
        target, res = _resolve(hwnd, name, exact, index)
    if target is None:
        return res
    if mouse is None:
        return {"error": "mouse controller not provided"}
    if hwnd:
        from computer_mcp.winutil import point_owner
        if point_owner(target['cx'], target['cy']) != hwnd:
            return {'ok': False, 'error': 'Target window is obscured; observe it again'}
    t0 = time.perf_counter()
    mouse.position = (target["cx"], target["cy"])
    _execution.sleep(0.06)
    mouse.click(
        {"left": mouse_button_left(), "right": None, "middle": None}.get(button) or mouse_button_left()
    )
    _execution.sleep(max(0, settle_ms) / 1000.0)
    return {
        "ok": True,
        "clicked": {"name": target["name"], "type": target["type"], "x": target["cx"], "y": target["cy"]},
        "ms": round((time.perf_counter() - t0) * 1000, 1),
    }


def mouse_button_left():
    from pynput.mouse import Button

    return Button.left


def _bound_window(hwnd):
    import win32gui
    window = hwnd or win32gui.GetForegroundWindow()
    if not window:
        raise ValueError('No target window')
    return window


def _check_control(control, hwnd):
    import win32gui, win32process
    from computer_mcp.capabilities import require_target
    from computer_mcp.permission import PermissionDenied
    top = control.GetTopLevelControl()
    actual = int(top.NativeWindowHandle)
    if (not actual or actual != win32gui.GetAncestor(hwnd, 2) or
            int(control.ProcessId) != win32process.GetWindowThreadProcessId(actual)[1]):
        raise PermissionDenied('Resolved UIA control belongs to a different target')
    require_target(hwnd=actual)


def ui_invoke(name: str, hwnd: int | None = None, exact: bool = False, index: int = 0) -> dict[str, Any]:
    """Trigger a control's Invoke pattern without moving the cursor."""
    if not _UIA_OK:
        return {"error": "uiautomation not installed in this venv"}
    hwnd = _bound_window(hwnd)
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
                box = c.BoundingRectangle
                identity = _element_id(c.ControlTypeName, (c.Name or '').strip(),
                    (int(box.left),int(box.top),int(box.width()),int(box.height())))
                if identity == target.get('element_id'):
                    ctrl = c
                    break
                queue.extend(c.GetChildren())
            except Exception:
                continue
    if ctrl is None:
        return {"error": "control vanished before invoke"}
    try:
        from computer_mcp.execution import check
        check('ui_invoke')
        from computer_mcp.capabilities import require_target
        pattern = ctrl.GetInvokePattern()
        _check_control(ctrl, hwnd)
        pattern.Invoke()
    except Exception as exc:
        return {"error": f"invoke failed: {exc}", "hint": "use ui_click instead"}
    return {"ok": True, "invoked": target["name"]}


def ui_set_text(name: str, text: str, hwnd: int | None = None, exact: bool = False, index: int = 0) -> dict[str, Any]:
    """Set a control's value through the Value pattern (no typing)."""
    if not _UIA_OK:
        return {"error": "uiautomation not installed in this venv"}
    hwnd = _bound_window(hwnd)
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
            box = c.BoundingRectangle
            identity = _element_id(c.ControlTypeName, (c.Name or '').strip(),
                (int(box.left),int(box.top),int(box.width()),int(box.height())))
            if identity == target.get('element_id'):
                try:
                    from computer_mcp.execution import check
                    check('ui_set_text')
                    from computer_mcp.capabilities import require_target
                    pattern = c.GetValuePattern()
                    _check_control(c, hwnd)
                    pattern.SetValue(text)
                    return {"ok": True, "set": text, "target": target["name"]}
                except Exception as exc:
                    return {"error": f"value pattern failed: {exc}"}
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
    # Keys held by the batch are released even when a later step fails.
    held_keys: list[str] = []

    for i, raw in enumerate(steps[: max(1, int(max_steps))]):
        from computer_mcp.execution import check
        check('batch')
        step = dict(raw or {})
        action = str(step.get("action", "")).strip().lower()
        t0 = time.perf_counter()
        entry: dict[str, Any] = {"i": i, "action": action}
        state_unknown: list = []
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
                from computer_mcp.core.utils import split_chord
                modifiers, base = split_chord(str(step.get("key", "enter")))
                for modifier in modifiers:
                    keyboard.press(resolve_key(modifier))
                    held_keys.append(modifier)
                try:
                    keyboard.press(resolve_key(base))
                    held_keys.append(base)
                    hold_ms = int(step.get("hold_ms", 0) or 0)
                    if hold_ms > 0:
                        # Some targets sample key state on a timer; a ~5 ms tap
                        # can fall entirely between two samples. Same cap as the
                        # top-level tool, and the same cooperative wait.
                        hold_ms = min(hold_ms, 10_000)
                        entry["held_ms"] = hold_ms
                        _execution.sleep(hold_ms / 1000.0)
                    keyboard.release(resolve_key(base))
                    if base in held_keys:
                        held_keys.remove(base)
                    state_unknown = []
                finally:
                    for modifier in reversed(modifiers):
                        try:
                            keyboard.release(resolve_key(modifier))
                            if modifier in held_keys:
                                held_keys.remove(modifier)
                        except Exception as exc:        # noqa: BLE001
                            state_unknown.append({"key": modifier,
                                                  "error": f"{type(exc).__name__}: {exc}"})
                    if state_unknown:
                        # A modifier that did not come up changes what the next
                        # step means (ctrl+a becomes ctrl+A), so nothing else may
                        # run until the keyboard state is known again.
                        entry["keyboard_state_unknown"] = state_unknown
                entry["ok"] = True
                if modifiers:
                    entry["chord"] = True
                if int(step.get("hold_ms", 0) or 0) > 0:
                    entry["held_ms"] = int(step.get("hold_ms", 0))
            elif action in ("key_down", "key_up"):
                key = str(step.get("key", ""))
                if not key:
                    raise ValueError(f"{action} needs a key")
                if action == "key_down":
                    keyboard.press(resolve_key(key))
                    if key not in held_keys:
                        held_keys.append(key)
                    entry["ok"] = True
                else:
                    keyboard.release(resolve_key(key))
                    if key in held_keys:
                        held_keys.remove(key)
                    entry["ok"] = True
            elif action == "sleep":
                ms = int(step.get("ms", default_sleep_ms))
                _execution.sleep(ms / 1000.0)
                entry["ok"] = True
                entry["slept_ms"] = ms
            elif action == "wait_change":
                res = capture_core.wait_for_change(
                    timeout_ms=int(step.get("timeout_ms", 3000)),
                    poll_ms=int(step.get("poll_ms", 120)),
                )
                entry["ok"] = bool(res.get('changed')) and not res.get('error')
                entry["result"] = res
                if not entry['ok']:
                    failures += 1
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

        if state_unknown:
            entry["ok"] = False
            failures += 1
            break                       # keyboard state is unknown: never continue
        if not entry.get("ok") and stop_on_error:
            break
        if action not in ("sleep", "wait_change") and int(step.get("gap_ms", default_sleep_ms)) > 0:
            _execution.sleep(int(step.get("gap_ms", default_sleep_ms)) / 1000.0)

    released = []
    release_failed = []
    for key in list(held_keys):
        try:
            keyboard.release(resolve_key(key))
            released.append(key)
            held_keys.remove(key)
        except Exception as exc:                        # noqa: BLE001
            release_failed.append({"key": key, "error": f"{type(exc).__name__}: {exc}"})
    if release_failed:
        failures += 1
    return {
        "ok": failures == 0,
        "steps_run": len(log),
        "failed": failures,
        "total_ms": round((time.perf_counter() - t_all) * 1000, 1),
        "released_keys": released,
        "release_failed": release_failed,
        "log": log,
    }


def _click(mouse, step, count=1, right=False):
    from pynput.mouse import Button

    if "x" in step and "y" in step:
        mouse.position = (int(step["x"]), int(step["y"]))
    btn = Button.right if (right or str(step.get("button", "")).lower() == "right") else Button.left
    mouse.click(btn, int(count))
