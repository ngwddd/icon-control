"""importers/base.py — 外部数据 → 我们的 episode 格式（P1-8）

三条硬规则（写在代码里，不靠自觉）：
  1. 一律打 labels:["external", <source>]，与自家样本分开统计
  2. **绝不**写 dataset/cases/ —— 回归用例必须是我们环境真实复现的
  3. 坐标必须连 (w,h) 一起存，跨分辨率不可复用
"""

from __future__ import annotations

import hashlib
import json
import os
import time

from .. import writer

MANIFEST = writer.ROOT / "importers" / "manifest.json"
EXTERNAL_DIR = writer.DATA / "external"


def _uid(source: str, key: str) -> str:
    h = hashlib.sha1(f"{source}|{key}".encode()).hexdigest()[:8]
    return f"ext-{source}-{h}"


def to_episode(*, source: str, key: str, tool: str, zone: str, args: dict,
               screen: tuple = (0, 0), verdict: str = "success",
               license_: str = "", note: str = "") -> dict:
    """把一条外部样本压成我们的 episode。"""
    w, h = (screen + (0, 0))[:2]
    return {
        "id": _uid(source, key),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tool": tool,
        "zone": zone,
        "args": dict(args or {}),
        "args_hash": hashlib.sha1(
            json.dumps(args or {}, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:16],
        "target": {"screen_w": int(w), "screen_h": int(h)},
        "result": {"ok": verdict == "success", "error": None, "bytes": 0},
        "verdict": verdict,
        "latency_ms": 0.0,
        "labels": ["external", source] + ([note] if note else []),
        "redactions": [],
        "meta": {"license": license_},
    }


def write(episodes: list, source: str, license_: str) -> dict:
    """写到 dataset/raw/external/<source>/episodes.jsonl，并更新清单。"""
    EXTERNAL_DIR.mkdir(parents=True, exist_ok=True)
    out = EXTERNAL_DIR / source
    out.mkdir(parents=True, exist_ok=True)
    p = out / "episodes.jsonl"
    with open(p, "a", encoding="utf-8") as fh:
        for ep in episodes:
            fh.write(json.dumps(ep, ensure_ascii=False) + "\n")
    update_manifest(source, len(episodes), license_, str(p))
    return {"ok": True, "source": source, "count": len(episodes), "path": str(p)}


def update_manifest(source: str, added: int, license_: str, path: str) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if MANIFEST.is_file():
        try:
            data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        except Exception:                                # noqa: BLE001
            data = {}
    rec = data.setdefault(source, {"total": 0})
    rec["total"] = rec.get("total", 0) + added
    rec["license"] = license_
    rec["path"] = path
    rec["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def stats() -> dict:
    """外部样本统计（与自家样本分开看）。"""
    if not EXTERNAL_DIR.is_dir():
        return {"sources": {}, "total": 0}
    out, total = {}, 0
    for p in EXTERNAL_DIR.glob("*/episodes.jsonl"):
        n = sum(1 for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip())
        out[p.parent.name] = n
        total += n
    return {"sources": out, "total": total}
