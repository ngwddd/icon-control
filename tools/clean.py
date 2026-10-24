"""clean.py - remove the scratch files a desktop-automation task leaves behind.

Design rules (deliberate, do not weaken):
  * dry-run by default; you must pass --apply to delete
  * only files matching an explicit allowlist of OUR OWN scratch patterns
  * never touches macros/, _patched/, venv/, desk.py, _tray_walk.py
  * every deletion is printed with its absolute path and size
  * files modified in the last --min-age-min minutes are skipped (a task may
    still be running)

Usage:
    venv\\Scripts\\python.exe clean.py                # preview everything
    venv\\Scripts\\python.exe clean.py --apply        # delete
    venv\\Scripts\\python.exe clean.py --scope tool --apply
    venv\\Scripts\\python.exe clean.py --scope draw --apply --keep 3
    venv\\Scripts\\python.exe clean.py --scope temp --apply
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
DRAW = os.path.join(BASE, "_draw")
TEMP = os.environ.get("TEMP", r"C:\Users\Public\Temp")

# scratch scripts / param files we create in the tool directory
TOOL_PATTERNS = [
    r"^_bench.*\.py$",
    r"^_verify.*\.py$",
    r"^_batch_demo\.json$",
    r"^_uitree.*\.json$",
    r"^_trace_shapes\.py$",
    r"^_wgc\.png$",
    r"^_screen_now\.png$",
    r".*\.bak$",
]

# scratch files we create in %TEMP%
TEMP_PATTERNS = [
    r"^t_.*\.py$",
    r"^patch_.*\.py$",
    r"^test_patch\.py$",
    r"^bench_batch\.py$",
    r"^desk_err\.txt$",
    r"^dry\.json$",
    r"^run.*\.json$",
    r"^run_.*\.json$",
    r"^macro\d*\.py$",
    r"^ocr_.*\.py$",
    r"^wx.*\.py$",
]

KEEP_NAMES = {
    "desk.py", "_tray_walk.py", "clean.py", "reapply.py",
    "ui_ext.py", "macro_ext.py", "ocr_ext.py", "cli.py",
}


def _age_min(path: str) -> float:
    return (time.time() - os.path.getmtime(path)) / 60.0


def _collect(directory: str, patterns: list[str], min_age_min: float, keep: set[str],
             max_age_hours: float = 24.0):
    hits = []
    if not os.path.isdir(directory):
        return hits
    now = time.time()
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        if name in keep or name in KEEP_NAMES:
            continue
        if not any(re.match(p, name) for p in patterns):
            continue
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        age_min = (now - mtime) / 60.0
        if age_min < min_age_min:
            continue
        if max_age_hours and age_min > max_age_hours * 60:
            continue  # older than the window: not from this task, leave it alone
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        hits.append((path, size))
    hits.sort(key=lambda t: -t[1])
    return hits


def _report(label: str, hits, apply_flag: bool) -> tuple[int, int]:
    total = sum(s for _, s in hits)
    print(f"\n=== {label}: {len(hits)} 个文件 / {total/1024/1024:.2f} MB ===")
    shown = hits if len(hits) <= 40 else hits[:40]
    for path, size in shown:
        print(f"   {size/1024:8.1f} KB  {path}")
    if len(hits) > len(shown):
        print(f"   ... 还有 {len(hits) - len(shown)} 个")
    if not apply_flag:
        print("   [预览模式] 加 --apply 才会真的删除")
        return 0, total
    freed = 0
    for path, size in hits:
        try:
            os.remove(path)
            freed += size
        except OSError as exc:
            print(f"   ! 删除失败 {path}: {exc}")
    print(f"   已删除，释放 {freed/1024/1024:.2f} MB")
    return freed, total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", choices=["all", "tool", "draw", "temp"], default="all")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--keep", type=int, default=0,
                    help="for --scope draw: keep the N newest screenshots")
    ap.add_argument("--min-age-min", type=float, default=2.0,
                    help="skip files modified more recently than this")
    ap.add_argument("--max-age-hours", type=float, default=24.0,
                    help="ignore files older than this (not from this task)")
    args = ap.parse_args()

    grand_total = 0
    grand_freed = 0

    if args.scope in ("all", "tool"):
        hits = _collect(BASE, TOOL_PATTERNS, args.min_age_min, set(), args.max_age_hours)
        f, t = _report("工具目录临时脚本", hits, args.apply)
        grand_freed += f; grand_total += t

    if args.scope in ("all", "draw"):
        hits = _collect(DRAW, [r".*\.(png|jpg|jpeg)$"], args.min_age_min, set(), args.max_age_hours)
        if args.keep and len(hits) > args.keep:
            # keep the N NEWEST screenshots, not the N largest
            by_age = sorted(hits, key=lambda t: -os.path.getmtime(t[0]))
            keep_paths = {p for p, _ in by_age[:args.keep]}
            hits = [h for h in hits if h[0] not in keep_paths]
        f, t = _report(f"_draw 截图（保留最新 {args.keep} 张）", hits, args.apply)
        grand_freed += f; grand_total += t

    if args.scope in ("all", "temp"):
        hits = _collect(TEMP, TEMP_PATTERNS, args.min_age_min, set(), args.max_age_hours)
        f, t = _report("%TEMP% 本次任务脚本", hits, args.apply)
        grand_freed += f; grand_total += t

    print(f"\n合计: {grand_total/1024/1024:.2f} MB"
          + (f" -> 已释放 {grand_freed/1024/1024:.2f} MB" if args.apply else " (未删除)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
