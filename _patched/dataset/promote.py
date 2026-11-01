"""dataset/promote.py — 把失败样本提升为回归用例（R7 的输入）。"""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import writer

CASES = writer.ROOT / "cases"


def promote(episode_id: str, note: str = "", signature: str = "") -> dict:
    """写 cases/<tool>-<id>.json，供 verify_flow / 测试复跑。"""
    target = None
    for ep in writer._iter_episodes():
        if ep.get("id") == episode_id:
            target = ep
            break
    if target is None:
        return {"success": False, "error": f"找不到样本 {episode_id}"}

    CASES.mkdir(parents=True, exist_ok=True)
    case = {
        "case_id": f"{target['tool']}-{target['id']}",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "note": note,
        "tool": target["tool"],
        "zone": target["zone"],
        "args": target["args"],
        "expected": {"verdict": "success"},
        "observed": {"verdict": target["verdict"],
                     "error": target.get("result", {}).get("error")},
        "source_episode": target["id"],
        "signature": signature or "",
    }
    p = CASES / f"{case['case_id']}.json"
    p.write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"success": True, "case": str(p), "case_id": case["case_id"]}


def list_cases() -> list:
    if not CASES.is_dir():
        return []
    return sorted(p.name for p in CASES.glob("*.json"))
