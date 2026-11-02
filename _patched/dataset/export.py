"""dataset/export.py — 打包成周包（离线回流用）。"""

from __future__ import annotations

import json
import time
import zipfile
import secrets
from pathlib import Path

from . import writer
from computer_mcp.workspace import component, owned_path


def export(days: int = 7, tag: str | None = None) -> dict:
    """把最近 N 天的 raw 打成一个 zip，返回路径与清单。"""
    days = max(1, min(int(days), 90))
    tag = tag or time.strftime("%Y-W%V")
    component(tag)
    outdir = owned_path(writer.ROOT / 'exports', tag)
    outdir.mkdir(parents=True, exist_ok=True)
    dst = outdir / f"episodes-{days}d-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(6)}.zip"

    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))
    files, count = [], 0
    with zipfile.ZipFile(dst, "x", zipfile.ZIP_DEFLATED) as zf:
        if writer.DATA.is_dir():
            for f in sorted(writer.DATA.glob("*/episodes.jsonl")):
                if f.parent.name < cutoff:
                    continue
                from .schema import sanitize_episode
                owned_path(writer.DATA,str(f))
                records = [sanitize_episode(json.loads(line)) for line in
                           f.read_text(encoding='utf-8').splitlines() if line.strip()]
                zf.writestr(f"raw/{f.parent.name}/episodes.jsonl",
                            '\n'.join(json.dumps(item,ensure_ascii=False) for item in records)+'\n')
                files.append(f.parent.name)
                count += sum(1 for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip())
        manifest = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "days": days, "tag": tag, "days_included": files,
                    "episodes": count, "privacy": "已脱敏；帧默认不采集"}
        zf.writestr("MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return {"zip": str(dst), "bytes": dst.stat().st_size,
            "episodes": count, "days_included": files}
