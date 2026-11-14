"""Interleaved A/B: alternate installed (before) and overlay (after) runs.

Comparing two runs taken minutes apart is how a benchmark lies. This alternates
them inside one session, then reports per-task medians for both variants.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Run the benchmark under the package under test: the interpreter that has
# computer_mcp installed, or $ICON_CONTROL_BENCH_PYTHON when it differs.
PY = os.environ.get("ICON_CONTROL_BENCH_PYTHON") or sys.executable
ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 3


def run(variant: str) -> Path:
    label = f"ab-{variant}-{run.counter}"
    run.counter += 1
    env = {"PYTHONPATH": str(ROOT / ".runtime")} if variant == "after" else {}
    completed = subprocess.run(
        [PY, str(ROOT / "tools/bench/task_bench.py"), "--label", label, "--repeats", "3"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, **env})
    if completed.returncode != 0:
        print(completed.stdout[-500:], completed.stderr[-500:])
    return ROOT / ".runtime" / "bench" / f"tasks-{label}.json"


run.counter = 1
paths = {"before": [], "after": []}
for _ in range(ROUNDS):
    paths["before"].append(run("before"))
    paths["after"].append(run("after"))

summary = {}
for variant, items in paths.items():
    for path in items:
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for task in data["tasks"]:
            summary.setdefault(task["task"], {}).setdefault(variant, []).append(
                (task["median_ms"], task["passed"], task["errors"]))

print(f"{'task':24} {'before ms':>10} {'after ms':>9} {'change':>9} {'pass b/a':>10}")
for task, variants in summary.items():
    before = [row for row in variants.get("before", [])]
    after = [row for row in variants.get("after", [])]
    if not before or not after:
        continue
    b = sorted(row[0] for row in before)[len(before) // 2]
    a = sorted(row[0] for row in after)[len(after) // 2]
    change = (a - b) / b * 100 if b else 0
    print(f"{task:24} {b:>10.1f} {a:>9.1f} {change:>8.1f}% "
          f"{sum(r[1] for r in before)}/{sum(r[1] for r in after):<8}")
