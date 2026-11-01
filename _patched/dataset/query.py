"""dataset/query.py — 只读查询（供 dataset_query 用）。"""

from __future__ import annotations

import time

from . import writer


def search(tool=None, zone=None, verdict=None, days=None, limit=20) -> list:
    """按条件筛样本，新的在前。"""
    since = None
    if days:
        since = time.strftime("%Y-%m-%d", time.localtime(time.time() - int(days) * 86400))
    out = []
    for ep in writer._iter_episodes():
        if tool and ep.get("tool") != tool:
            continue
        if zone and ep.get("zone") != zone:
            continue
        if verdict and ep.get("verdict") != verdict:
            continue
        if since and (ep.get("ts") or "")[:10] < since:
            continue
        out.append(ep)
    out.reverse()
    limit = max(1, min(int(limit or 20), 200))
    return out[:limit]


def group_by(field: str, days=None) -> dict:
    counts = {}
    for ep in search(days=days, limit=100000):
        k = ep.get(field) or "?"
        counts[k] = counts.get(k, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
