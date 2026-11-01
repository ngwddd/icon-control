"""dataset/retention.py — 三条上限：raw_days / frame_days / frames_gb。

只删 dataset/ 自己的东西；exports/ 只保留最近 N 份。
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from . import writer


def _dir_age_days(d: Path) -> float:
    try:
        return (time.time() - d.stat().st_mtime) / 86400.0
    except Exception:                                   # noqa: BLE001
        return 0.0


def sweep(dry_run: bool = False) -> dict:
    cfg = writer.load_config().get("retention", {})
    raw_days = float(cfg.get("raw_days", 90))
    frame_days = float(cfg.get("frame_days", 30))
    frames_gb = float(cfg.get("frames_gb", 8))
    keep_exports = int(cfg.get("exports", 4))

    report = {"removed_raw": [], "removed_frames": [], "removed_exports": [],
              "freed_bytes": 0, "dry_run": dry_run}

    # 1) raw 按天目录
    if writer.DATA.is_dir():
        for d in sorted(writer.DATA.iterdir()):
            if not d.is_dir() or _dir_age_days(d) <= raw_days:
                continue
            size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
            report["removed_raw"].append(d.name)
            report["freed_bytes"] += size
            if not dry_run:
                shutil.rmtree(d, ignore_errors=True)

    # 2) frames 按天目录 + 总量上限
    if writer.FRAMES.is_dir():
        keep = []
        for d in sorted(writer.FRAMES.iterdir()):
            if not d.is_dir():
                continue
            if _dir_age_days(d) > frame_days:
                size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
                report["removed_frames"].append(d.name)
                report["freed_bytes"] += size
                if not dry_run:
                    shutil.rmtree(d, ignore_errors=True)
            else:
                keep.append(d)
        total = sum(f.stat().st_size for d in keep for f in d.rglob("*") if f.is_file())
        if total > frames_gb * 1024 ** 3:
            for d in sorted(keep, key=lambda p: p.stat().st_mtime):
                if total <= frames_gb * 1024 ** 3:
                    break
                size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
                total -= size
                report["removed_frames"].append(d.name + " (超容量)")
                report["freed_bytes"] += size
                if not dry_run:
                    shutil.rmtree(d, ignore_errors=True)

    # 3) exports 只留最近 N 份
    exp = writer.ROOT / "exports"
    if exp.is_dir():
        dirs = sorted([d for d in exp.iterdir() if d.is_dir()],
                      key=lambda p: p.stat().st_mtime, reverse=True)
        for d in dirs[keep_exports:]:
            size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
            report["removed_exports"].append(d.name)
            report["freed_bytes"] += size
            if not dry_run:
                shutil.rmtree(d, ignore_errors=True)

    return report
