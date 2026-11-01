"""importers/local_fixture.py — 最小可用导入器（P1-8）。

读一个 JSONL fixture，每行形如：
    {"key": "1", "tool": "click", "x": 800, "y": 600, "w": 1920, "h": 1080, "ok": true}

用途：在没有网络/没拿到许可前，先验证「转换 → 落盘 → 统计」这条链路。
"""

from __future__ import annotations

import json

from . import base


def load(path: str, source: str = "fixture", license_: str = "test-only") -> list:
    eps = []
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            eps.append(base.to_episode(
                source=source,
                key=str(row.get("key", i)),
                tool=row.get("tool", "click"),
                zone=row.get("zone", "Z3"),
                args={"x": row.get("x", 0), "y": row.get("y", 0)},
                screen=(row.get("w", 0), row.get("h", 0)),
                verdict="success" if row.get("ok", True) else "failed",
                license_=license_,
            ))
    return eps
