"""dataset/triage.py — 把失败样本分拣成回归用例（R7）。

规则：同一 (tool, 错误签名) 在窗口内出现 ≥ min_count 次 → 生成一条 case。
去重：已存在同签名 case 就跳过，不重复写。
"""

from __future__ import annotations

import hashlib
import json
import re
import time

from . import promote, writer

SIG_NOISE = re.compile(r"\d+")


def signature(ep: dict) -> str:
    """把错误信息里的数字抹掉，聚成「同类失败」。"""
    err = (ep.get("result") or {}).get("error") or ep.get("verdict") or "?"
    err = SIG_NOISE.sub("N", str(err))[:120]
    raw = f"{ep.get('tool')}|{ep.get('verdict')}|{err}"
    return hashlib.sha1(raw.encode()).hexdigest()[:10]


def existing_signatures() -> set:
    """已生成 case 的签名集合（去重键，存在 case JSON 里）。"""
    sigs = set()
    if not promote.CASES.is_dir():
        return sigs
    for p in promote.CASES.glob("*.json"):
        try:
            sigs.add(json.loads(p.read_text(encoding="utf-8")).get("signature") or "")
        except Exception:                               # noqa: BLE001
            continue
    sigs.discard("")
    return sigs


def run(days: int = 1, min_count: int = 3, dry_run: bool = False) -> dict:
    since = time.strftime("%Y-%m-%d", time.localtime(time.time() - int(days) * 86400))
    groups: dict = {}
    for ep in writer._iter_episodes():
        if (ep.get("ts") or "")[:10] < since:
            continue
        if ep.get("verdict") in (None, "success", "unknown"):
            continue
        groups.setdefault(signature(ep), []).append(ep)

    existing_sigs = existing_signatures()
    made, skipped = [], []
    for sig, eps in groups.items():
        if len(eps) < int(min_count):
            continue
        eps.sort(key=lambda e: e.get("ts") or "")
        if sig in existing_sigs:
            skipped.append({"signature": sig, "reason": "已有同签名 case"})
            continue
        ep = eps[-1]
        if dry_run:
            made.append({"signature": sig, "would_promote": ep.get("id"), "count": len(eps)})
            continue
        r = promote.promote(ep.get("id"),
                            note=f"triage: {len(eps)} 次同类失败（{sig}）",
                            signature=sig)
        existing_sigs.add(sig)
        made.append({"signature": sig, "case": r.get("case"), "count": len(eps)})

    return {"success": True, "days": days, "min_count": min_count,
            "groups": len(groups), "generated": made, "skipped": skipped,
            "dry_run": dry_run}
