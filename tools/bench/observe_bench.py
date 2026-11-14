"""Observation microbenchmarks: where does UIA time actually go?

Answers three questions without guessing:
  1. How much of a ui_tree call is traversal versus property reads?
  2. What does each extra property (Name / rect / type / AutomationId) cost?
  3. For a wide parent, what does early-exit save versus GetChildren()?

Run with the installed package (or a PYTHONPATH overlay):

    python tools/bench/observe_bench.py --hwnd 1234 --repeats 5
    python tools/bench/observe_bench.py --auto            # pick the biggest UIA window
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

PROPSETS = {
    "none": (),
    "name": ("name",),
    "name+rect": ("name", "rect"),
    "name+rect+type": ("name", "rect", "type"),
    "name+rect+type+id": ("name", "rect", "type", "automation_id"),
}


def _walk(ctrl, depth, out, max_nodes, props):
    """Mirror of ui_ext._walk with a configurable property set."""
    if len(out) >= max_nodes:
        return
    try:
        children = ctrl.GetChildren()
    except Exception:                                   # noqa: BLE001
        return
    for child in children:
        if len(out) >= max_nodes:
            return
        record = {}
        if "name" in props:
            record["name"] = (child.Name or "").strip()
        if "rect" in props:
            rect = child.BoundingRectangle
            record["rect"] = (rect.left, rect.top, rect.width(), rect.height())
        if "type" in props:
            record["type"] = child.ControlTypeName
        if "automation_id" in props:
            record["automation_id"] = (child.AutomationId or "").strip()
        out.append(record)
        if depth > 0:
            _walk(child, depth - 1, out, max_nodes, props)


def _median_ms(function, repeats):
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        value = function()
        samples.append((time.perf_counter() - started) * 1000.0)
    return round(statistics.median(samples), 2), round(min(samples), 2), value


def _widest_parent(root, depth=7, limit=12):
    """The parent with the most direct children, up to a small depth."""
    best = {"control": None, "children": 0}
    queue = [(root, 0)]
    seen = 0
    while queue and seen < limit * 20:
        node, level = queue.pop(0)
        seen += 1
        try:
            children = node.GetChildren()
        except Exception:                               # noqa: BLE001
            continue
        if len(children) > best["children"]:
            best = {"control": node, "children": len(children)}
        if level < depth:
            queue.extend((child, level + 1) for child in children[:limit])
    return best


def _stream_children(control, limit):
    """Enumerate only `limit` children using the walker, then stop."""
    out = []
    try:
        child = control.GetFirstChildControl()
    except Exception:                                   # noqa: BLE001
        return out
    while child is not None and len(out) < limit:
        out.append(child)
        try:
            child = child.GetNextSiblingControl()
        except Exception:                               # noqa: BLE001
            break
    return out


def measure(hwnd, depth, max_nodes, repeats, early_limit):
    from computer_mcp import ui_ext

    root = ui_ext._control_from(hwnd)
    if root is None:
        raise SystemExit(f"cannot resolve window {hwnd}")
    report = {"hwnd": hwnd, "title": (root.Name or "").strip(), "depth": depth,
              "max_nodes": max_nodes, "repeats": repeats, "properties": {}, "ui_tree": {}}

    def count_nodes(props):
        collected = []
        _walk(root, depth, collected, max_nodes, props)
        return len(collected)

    # 1. cost of each property set on the same tree
    for label, props in PROPSETS.items():
        median, best, nodes = _median_ms(lambda props=props: count_nodes(props), repeats)
        report["properties"][label] = {"median_ms": median, "min_ms": best, "nodes": nodes}

    # 2. the real api, for reference
    median, best, tree = _median_ms(
        lambda: ui_ext.ui_tree(hwnd=hwnd, depth=depth, max_nodes=max_nodes,
                               only_named=False), repeats)
    report["ui_tree"] = {"median_ms": median, "min_ms": best,
                         "count": (tree or {}).get("count")}

    # 3. wide parent: full GetChildren vs walker with an early stop
    widest = _widest_parent(root)
    entry = {"children": widest["children"]}
    if widest["children"] > early_limit:
        full_ms, _, _ = _median_ms(lambda: widest["control"].GetChildren(), repeats)
        early_ms, _, taken = _median_ms(
            lambda: _stream_children(widest["control"], early_limit), repeats)
        entry.update(full_ms=full_ms, early_ms=early_ms,
                     early_limit=early_limit, early_taken=len(taken),
                     saved_ms=round(full_ms - early_ms, 2))
    report["wide_parent"] = entry
    return report


def _auto_hwnd():
    """Pick the visible window with the most UIA nodes (small probe)."""
    import win32gui

    from computer_mcp import ui_ext

    best = {"hwnd": None, "count": 0, "title": ""}
    handles = []

    def collect(hwnd, acc):
        if win32gui.IsWindowVisible(hwnd):
            acc.append(hwnd)
        return True

    win32gui.EnumWindows(collect, handles)
    for hwnd in handles:
        rect = win32gui.GetWindowRect(hwnd)
        if rect[2] - rect[0] < 400 or rect[3] - rect[1] < 300:
            continue
        # The desktop shell is a poor benchmark target: it has a big tree with
        # almost no useful properties.
        if win32gui.GetClassName(hwnd) in ("Progman", "WorkerW", "Shell_TrayWnd"):
            continue
        try:
            tree = ui_ext.ui_tree(hwnd=hwnd, depth=3, max_nodes=60, only_named=False)
        except Exception:                               # noqa: BLE001
            continue
        count = tree.get("count") or 0
        if count > best["count"]:
            best = {"hwnd": hwnd, "count": count, "title": (tree.get("window") or "")[:40]}
    return best


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hwnd", type=int)
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--depth", type=int, default=6)
    parser.add_argument("--max-nodes", type=int, default=300)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--early-limit", type=int, default=10)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    hwnd = args.hwnd
    if hwnd is None:
        picked = _auto_hwnd()
        hwnd = picked["hwnd"]
        print(f"auto-picked hwnd={hwnd} title={picked['title']!r} nodes~{picked['count']}")
    if not hwnd:
        print("no suitable window found")
        return 2

    report = measure(hwnd, args.depth, args.max_nodes, args.repeats, args.early_limit)

    import importlib.metadata as metadata
    report["env"] = {
        "python": sys.version.split()[0],
        "uiautomation": metadata.version("uiautomation"),
        "computer_mcp": __import__("computer_mcp").__version__,
    }
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = args.out or Path(".runtime/bench") / f"observe-{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nwindow: {report['title']!r} hwnd={hwnd}")
    print(f"{'property set':22} {'median ms':>10} {'nodes':>7}")
    for label, data in report["properties"].items():
        print(f"{label:22} {data['median_ms']:>10} {data['nodes']:>7}")
    base = report["properties"]["none"]["median_ms"]
    total = report["properties"]["name+rect+type+id"]["median_ms"]
    print(f"\n  traversal only: {base:.2f} ms "
          f"({base / total * 100:.0f}% of the full walk), property reads: {total - base:.2f} ms")
    for label, data in report["properties"].items():
        if label != "none":
            print(f"  delta vs traversal: {label:20} +{data['median_ms'] - base:.2f} ms")
    tree = report["ui_tree"]
    print(f"{'ui_tree (api)':22} {tree['median_ms']:>10} {tree['count']:>7}")
    wide = report["wide_parent"]
    if "full_ms" in wide:
        print(f"wide parent: {wide['children']} children, full {wide['full_ms']} ms, "
              f"first {wide['early_limit']} via walker {wide['early_ms']} ms "
              f"({wide['saved_ms']} ms saved)")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
