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


def run(kind: str = "change", query=None, element_id=None,
        timeout_ms: int = 5000, interval_ms: int = 150) -> dict:
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
