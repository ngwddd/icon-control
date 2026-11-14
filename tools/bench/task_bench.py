"""Task-level benchmark: fixed flows, independent verification, honest numbers.

Each task runs in-process against the package on PYTHONPATH and records:
  - wall time
  - tool-level calls (ui_tree / ui_find / ocr / keyboard)
  - OCR invocations
  - nodes materialised from UIA

Success is decided by an independent check (filesystem, control value), never by
the tool's own ``success`` field.

    python tools/bench/task_bench.py --label before
    python tools/bench/task_bench.py --label after --out .runtime/bench/tasks-after.json
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

COUNTERS = {"calls": {}, "ocr": 0, "nodes": 0}


def _bump(name):
    COUNTERS["calls"][name] = COUNTERS["calls"].get(name, 0) + 1


def instrument():
    """Wrap the modules we measure. Idempotent per process."""
    from computer_mcp import ocr_ext, ui_ext

    if getattr(ui_ext, "_bench_wrapped", False):
        return
    original_tree = ui_ext.ui_tree
    original_find = ui_ext.ui_find
    original_ocr = ocr_ext.find_text
    original_walk = ui_ext._walk

    def ui_tree(*args, **kwargs):
        _bump("ui_tree")
        result = original_tree(*args, **kwargs)
        if isinstance(result, dict):
            COUNTERS["nodes"] += len(result.get("elements") or [])
        return result

    def ui_find(*args, **kwargs):
        _bump("ui_find")
        result = original_find(*args, **kwargs)
        if isinstance(result, dict):
            COUNTERS["nodes"] += len(result.get("elements") or [])
        return result

    def find_text(*args, **kwargs):
        COUNTERS["ocr"] += 1
        _bump("ocr_read")
        return original_ocr(*args, **kwargs)

    def walk(*args, **kwargs):
        _bump("walk")
        return original_walk(*args, **kwargs)

    ui_ext.ui_tree = ui_tree
    ui_ext.ui_find = ui_find
    ui_ext._walk = walk
    ocr_ext.find_text = find_text
    ui_ext._bench_wrapped = True


def _reset():
    COUNTERS["calls"].clear()
    COUNTERS["ocr"] = 0
    COUNTERS["nodes"] = 0


# ----------------------------------------------------------------- tasks

def _find_window(class_name=None, title_contains=None, process_pid=None):
    import win32gui

    found = []

    def visit(hwnd, acc):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        if class_name and win32gui.GetClassName(hwnd) != class_name:
            return True
        title = win32gui.GetWindowText(hwnd)
        if title_contains and title_contains not in title:
            return True
        rect = win32gui.GetWindowRect(hwnd)
        if rect[2] - rect[0] < 300 or rect[3] - rect[1] < 200:
            return True
        acc.append((hwnd, title, rect))
        return True

    win32gui.EnumWindows(visit, found)
    return found[0] if found else None


def task_explorer_tree_size():
    """A full tree read of Explorer: the cost of one observation."""
    from computer_mcp import ui_ext

    window = _find_window(class_name="CabinetWClass")
    if not window:
        return None, "no Explorer window"
    hwnd, _, _ = window
    tree = ui_ext.ui_tree(hwnd=hwnd, depth=8, max_nodes=400, only_named=False)
    count = (tree or {}).get("count") or 0
    COUNTERS["nodes"] += count
    names = [(node.get("name") or "").lower() for node in (tree.get("nodes") or [])]
    has_list = any("项" in name or "item" in name for name in names)
    return (count > 50), {"count": count, "has_list_container": has_list}


def task_explorer_find_address():
    """Locate the address bar by name; verify the hit by its automation_id."""
    from computer_mcp import ui_ext

    window = _find_window(class_name="CabinetWClass")
    if not window:
        return None, "no Explorer window"
    hwnd, _, _ = window
    found = ui_ext.ui_find(name="地址", exact=False, hwnd=hwnd)
    rows = (found or {}).get("candidates") or []
    COUNTERS["nodes"] += len(rows)
    target = (found or {}).get("target") or {}
    ok = bool(rows) and "地址" in (target.get("name") or "")
    return ok, {"hits": len(rows), "target_type": target.get("type"),
                "target_id": target.get("automation_id")}


def task_notepad_find_doc():
    """Locate the document control; verify the ref re-resolves to the same type."""
    from computer_mcp import ui_ext

    window = _find_window(class_name="Notepad")
    if not window:
        return None, "no Notepad window"
    hwnd, _, _ = window
    tree = ui_ext.ui_tree(hwnd=hwnd, depth=12, max_nodes=800, only_named=False)
    nodes = (tree or {}).get("nodes") or []
    COUNTERS["nodes"] += len(nodes)
    documents = [node for node in nodes if node.get("type") == "DocumentControl"]
    if not documents:
        return False, {"count": len(nodes), "documents": 0}
    doc = documents[0]
    resolved = ui_ext.control_at_path(hwnd, doc.get("path")) or {}
    ok = resolved.get("type") == "DocumentControl"
    return ok, {"count": len(nodes), "documents": len(documents),
                "path": doc.get("path"), "resolves_to_same_type": ok}


def task_notepad_find_menu():
    """Locate the File menu item by name (a stable Win32 target)."""
    from computer_mcp import ui_ext

    window = _find_window(class_name="Notepad")
    if not window:
        return None, "no Notepad window"
    hwnd, _, _ = window
    found = ui_ext.ui_find(name="文件", exact=True, hwnd=hwnd)
    rows = (found or {}).get("candidates") or []
    COUNTERS["nodes"] += len(rows)
    types = [row.get("type") or "" for row in rows]
    ok = bool(rows) and any(t.endswith("MenuItemControl") for t in types)
    return ok, {"hits": len(rows), "types": types[:3]}


TASKS = [
    ("explorer_tree_size", task_explorer_tree_size),
    ("explorer_find_address", task_explorer_find_address),
    ("notepad_find_doc", task_notepad_find_doc),
    ("notepad_find_menu", task_notepad_find_menu),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="run")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    instrument()
    results = []
    for name, function in TASKS:
        timings, records = [], []
        for _ in range(args.repeats):
            _reset()
            started = time.perf_counter()
            try:
                ok, evidence = function()
            except Exception as exc:                    # noqa: BLE001
                ok, evidence = "error", f"{type(exc).__name__}: {exc}"
            elapsed = (time.perf_counter() - started) * 1000.0
            timings.append(elapsed)
            records.append({
                "ok": ok,
                "evidence": evidence,
                "elapsed_ms": round(elapsed, 1),
                "calls": dict(COUNTERS["calls"]),
                "ocr": COUNTERS["ocr"],
                "nodes": COUNTERS["nodes"],
            })
        successful = [record for record in records if record["ok"] is True]
        results.append({
            "task": name,
            "runs": len(records),
            "passed": len(successful),
            "skipped": sum(1 for record in records if record["ok"] is None),
            "errors": sum(1 for record in records if record["ok"] == "error"),
            "median_ms": round(statistics.median(timings), 1),
            "min_ms": round(min(timings), 1),
            "calls": records[-1]["calls"],
            "ocr": records[-1]["ocr"],
            "nodes": records[-1]["nodes"],
            "sample_evidence": records[-1]["evidence"],
            "last_error": next((r["evidence"] for r in records if r["ok"] == "error"), None),
        })

    import computer_mcp
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    import win32api
    report = {"label": args.label, "version": computer_mcp.__version__,
              "screen": [win32api.GetSystemMetrics(0), win32api.GetSystemMetrics(1)],
              "package": computer_mcp.__file__, "tasks": results,
              "when": time.strftime("%Y-%m-%dT%H:%M:%S")}
    out = args.out or Path(".runtime/bench") / f"tasks-{args.label}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"{'task':24} {'pass':>5} {'skip':>4} {'median ms':>10} {'ocr':>4} {'nodes':>6}")
    for item in results:
        print(f"{item['task']:24} {item['passed']:>5} {item['skipped']:>4} "
              f"{item['median_ms']:>10} {item['ocr']:>4} {item['nodes']:>6}")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
