"""dataset/writer.py — 追加写 JSONL + 用量统计 + 帧（可选）。

崩溃安全：每行一次 write + flush，坏行最多丢最后一条。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "raw"
FRAMES = ROOT / "frames"
CONFIG = ROOT / "config.json"

DEFAULT_CONFIG = {
    "enabled": True,
    "frames": False,
    "max_frame_kb": 120,
    "debug": False,
    "retention": {"raw_days": 90, "frame_days": 30, "frames_gb": 8, "exports": 4},
}


def load_config() -> dict:
    try:
        with open(CONFIG, encoding="utf-8") as fh:
            cfg = json.load(fh)
        merged = dict(DEFAULT_CONFIG)
        merged.update(cfg or {})
        return merged
    except Exception:                                   # noqa: BLE001
        return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def today_dir() -> Path:
    d = DATA / time.strftime("%Y-%m-%d")
    d.mkdir(parents=True, exist_ok=True)
    return d


def append_episode(ep: dict) -> Path:
    p = today_dir() / "episodes.jsonl"
    line = json.dumps(ep, ensure_ascii=False) + "\n"
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
    return p


def _iter_episodes():
    if not DATA.is_dir():
        return
    for f in sorted(DATA.glob("*/episodes.jsonl")):
        try:
            with open(f, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except Exception:                   # noqa: BLE001
                        continue
        except Exception:                               # noqa: BLE001
            continue


def stats() -> dict:
    today = time.strftime("%Y-%m-%d")
    per_day, zones, total, today_n, last = {}, set(), 0, 0, None
    for ep in _iter_episodes():
        total += 1
        day = (ep.get("ts") or "")[:10]
        per_day[day] = per_day.get(day, 0) + 1
        zones.add(ep.get("zone"))
        if day == today:
            today_n += 1
        last = ep
    out = {}
    for f in sorted(DATA.glob("*/episodes.jsonl")):
        out[f.parent.name] = f.stat().st_size
    return {
        "episodes_today": today_n,
        "episodes_total": total,
        "bytes_by_day": out,
        "zones_seen": sorted(z for z in zones if z),
        "last_episode": {k: last.get(k) for k in ("id", "ts", "tool", "verdict")} if last else None,
    }


def total_bytes() -> dict:
    raw = sum(f.stat().st_size for f in DATA.rglob("*.jsonl")) if DATA.is_dir() else 0
    frames = sum(f.stat().st_size for f in FRAMES.rglob("*") if f.is_file()) if FRAMES.is_dir() else 0
    return {"raw_bytes": raw, "frame_bytes": frames}


def save_frame(episode_id: str, which: str, jpeg: bytes, max_kb: int = 120) -> str | None:
    """帧落地（超限直接丢）。默认不调用——frames=false。"""
    if len(jpeg) > max_kb * 1024:
        return None
    d = FRAMES / episode_id
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{which}.jpg"
    p.write_bytes(jpeg)
    return str(p.relative_to(ROOT))
