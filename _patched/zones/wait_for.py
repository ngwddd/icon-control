"""zones/wait_for.py — 统一等待入口（P1-5）。

把原来分散的 wait_for_change / wait_template / wait_baseline_change 收成一个
`kind` 参数，模型只需要记一个工具（Windows-MCP 的 WaitFor 也是这个思路）。

实现策略：**委托**给已有实现，不重写轮询逻辑 —— 这样不引入新的时序 bug。
    change   → 复用 capture 的 diff（轮询 screen_state）
    text     → 复用 ocr_ext.ocr_read，直到找到 query
    template → 复用 vision_state.wait_template
    element  → 复用 ui_ext.ui_tree，直到出现该 element_id
    focused  → 等到前台窗口标题包含 query（不传则等到窗口变化）
"""

from __future__ import annotations

import time


def probe(condition: dict) -> dict:
    """One non-blocking check, shared by wait_for(any=[...]) and execute_verified."""
    kind = str(condition.get("kind", "text"))
    query = condition.get("query")
    element_id = condition.get("element_id")
    if kind == "text":
        if not query:
            return dict(ok=False, detail="text needs query")
        from computer_mcp import ocr_ext

        try:
            res = ocr_ext.ocr_read(max_lines=200)
            blob = " ".join(line.get("text", "") for line in (res.get("lines") or []))
        except Exception:                                # noqa: BLE001
            blob = ""
        return dict(ok=str(query) in blob, detail=f"text {query!r}")
    if kind == "element":
        if not element_id:
            return dict(ok=False, detail="element needs element_id")
        from computer_mcp import ui_ext

        tree = ui_ext.ui_tree(depth=8, max_nodes=800, only_named=False)
        ids = {node.get("element_id") for node in (tree.get("nodes") or [])}
        return dict(ok=element_id in ids, detail="element present")
    if kind == "template":
        from computer_mcp import vision_state as vs

        hit = vs.match_template(name=str(query or ""))
        return dict(ok=bool(hit and hit.get("found")), detail=f"template {query!r}")
    if kind == "focused":
        import ctypes

        hwnd = ctypes.windll.user32.GetForegroundWindow()
        buf = ctypes.create_unicode_buffer(512)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value or ""
        ok = str(query).lower() in title.lower() if query else False
        return dict(ok=ok, detail=f"focused {title!r}")
    if kind == "value":
        from computer_mcp import element_ops as eo
        from computer_mcp import snapshots

        try:
            target = snapshots.resolve(str(query), None)
            state = eo.read_state(int(target["hwnd"]), str(target["path"]))
        except Exception as exc:                         # noqa: BLE001
            return dict(ok=False, detail=f"value probe failed: {exc}")
        return dict(ok=str(state.get("value")) == str(condition.get("text")),
                    detail=f"value={state.get('value')!r}")
    return dict(ok=False, detail=f"unknown condition kind: {kind}")


def _run_any(conditions, timeout_ms: int, interval_ms: int) -> dict:
    t0 = time.perf_counter()
    deadline = t0 + max(0.1, timeout_ms / 1000.0)
    interval = max(0.05, interval_ms / 1000.0)
    polls = 0
    last = {}
    while True:
        polls += 1
        for condition in conditions:
            outcome = probe(condition)
            last[str(condition.get("kind"))] = outcome.get("detail")
            if outcome.get("ok"):
                return dict(ok=True, kind="any", matched=condition, polls=polls,
                            elapsed_s=round(time.perf_counter() - t0, 2))
        if time.perf_counter() >= deadline:
            return dict(ok=False, kind="any", polls=polls, detail=last,
                        elapsed_s=round(time.perf_counter() - t0, 2),
                        error="no condition matched before timeout")
        time.sleep(interval)


def run(kind: str = "change", query=None, element_id=None,
        timeout_ms: int = 5000, interval_ms: int = 150, any=None) -> dict:
    if any is not None:
        conditions = [condition for condition in any if isinstance(condition, dict)]
        if not conditions:
            return dict(ok=False, kind="any", error="any=[] needs at least one condition")
        return _run_any(conditions, int(timeout_ms), int(interval_ms))
    t0 = time.perf_counter()
    deadline = t0 + max(0.1, timeout_ms / 1000.0)
    interval = max(0.05, interval_ms / 1000.0)
    polls = 0

    def _done(ok, extra=None):
        out = {"ok": bool(ok), "kind": kind, "polls": polls,
               "elapsed_s": round(time.perf_counter() - t0, 2)}
        if extra:
            out.update(extra)
        return out

    if kind == "change":
        from computer_mcp.core import screenshot as cap

        first = cap.capture_screenshot()
        base = first.get("hash") or first.get("changed")
        while time.perf_counter() < deadline:
            time.sleep(interval)
            polls += 1
            cur = cap.capture_screenshot()
            if cur.get("changed") or (base and cur.get("hash") != base):
                return _done(True, {"detail": "screen changed"})
        return _done(False, {"detail": "no change before timeout"})

    if kind == "text":
        if not query:
            return _done(False, {"detail": "text 需要 query"})
        from computer_mcp import ocr_ext

        while time.perf_counter() < deadline:
            polls += 1
            try:
                res = ocr_ext.ocr_read(max_lines=200)
                blob = " ".join(l.get("text", "") for l in (res.get("lines") or []))
            except Exception:                            # noqa: BLE001
                blob = ""
            if query in blob:
                return _done(True, {"detail": f"found {query!r}"})
            time.sleep(interval)
        return _done(False, {"detail": f"text {query!r} not found"})

    if kind == "template":
        if not query:
            return _done(False, {"detail": "template 需要 query"})
        from computer_mcp import vision_state as vs

        while time.perf_counter() < deadline:
            polls += 1
            try:
                hit = vs.wait_template(name=str(query), timeout_ms=int(interval * 1000))
            except Exception:                            # noqa: BLE001
                hit = None
            if hit and hit.get("found"):
                return _done(True, {"detail": f"template {query!r} found", "match": hit})
            time.sleep(interval)
        return _done(False, {"detail": f"template {query!r} not found"})

    if kind == "element":
        if not element_id:
            return _done(False, {"detail": "element 需要 element_id"})
        from computer_mcp import ui_ext

        while time.perf_counter() < deadline:
            polls += 1
            tree = ui_ext.ui_tree(depth=8, max_nodes=800, only_named=False)
            ids = {n.get("element_id") for n in (tree.get("nodes") or [])}
            if element_id in ids:
                return _done(True, {"detail": "element present"})
            time.sleep(interval)
        return _done(False, {"detail": "element not found"})

    if kind == "focused":
        import ctypes

        def title() -> str:
            try:
                hwnd = ctypes.windll.user32.GetForegroundWindow()
                buf = ctypes.create_unicode_buffer(512)
                ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
                return buf.value or ""
            except Exception:                            # noqa: BLE001
                return ""

        start = title()
        while time.perf_counter() < deadline:
            polls += 1
            cur = title()
            if query and str(query).lower() in cur.lower():
                return _done(True, {"detail": f"focused {cur!r}"})
            if not query and cur != start:
                return _done(True, {"detail": f"focus changed → {cur!r}"})
            time.sleep(interval)
        return _done(False, {"detail": "focus condition not met"})

    return _done(False, {"detail": f"未知 kind: {kind}"})
