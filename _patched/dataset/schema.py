"""dataset/schema.py — episode 的结构与轻量解析。"""

from __future__ import annotations

import hashlib
import json
import time

from . import redact

FIELDS = (
    "id", "ts", "tool", "zone", "args", "args_hash", "target",
    "result", "verdict", "latency_ms", "labels", "redactions",
)


def _uid() -> str:
    t = time.strftime("%Y%m%d-%H%M%S")
    r = hashlib.sha1(str(time.time_ns()).encode()).hexdigest()[:6]
    return f"{t}-{r}"


def text_of(resp) -> str:
    """从 MCP 返回值里抽文本（list[TextContent/ImageContent]）。"""
    if resp is None:
        return ""
    if isinstance(resp, str):
        return resp
    parts = []
    try:
        for item in resp:
            t = getattr(item, "text", None)
            if t:
                parts.append(t)
    except TypeError:
        return str(resp)
    return "\n".join(parts)


def ok_of(text: str):
    """从返回 JSON 里读 success/blocked；读不到返回 None（不确定）。"""
    if not text:
        return None
    s = text.strip()
    if not s.startswith("{"):
        return None
    try:
        d = json.loads(s)
    except Exception:                                   # noqa: BLE001
        return None
    if not isinstance(d, dict):
        return None
    if d.get("blocked"):
        return False
    if "success" in d:
        return bool(d["success"])
    if "error" in d and d.get("error"):
        return False
    return None


def build_episode(*, tool: str, arguments, zone: str, result_text,
                  ok, latency_ms: float, error, labels=None) -> dict:
    safe_args, redactions = redact.redact_args(arguments or {})
    if ok is True:
        verdict = "success"
    elif ok is False:
        verdict = "denied" if (result_text or "").find('"blocked"') >= 0 else "failed"
    else:
        verdict = "unknown"
    if error:
        verdict = "error"
    return {
        "id": _uid(),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "tool": tool,
        "zone": zone or "?",
        "args": safe_args,
        "args_hash": hashlib.sha1(
            json.dumps(safe_args, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:16],
        "target": redact.target_of(safe_args),
        "result": {"ok": ok, "error": (error if error in
                   {'ValueError','TypeError','RuntimeError','PermissionDenied','OSError','TimeoutError'}
                   else 'operation_error') if error else None,
                   "bytes": len(result_text or "")},
        "verdict": verdict,
        "latency_ms": round(latency_ms, 1),
        "labels": [label for label in (labels or []) if label in {'explore','regression','manual'}],
        "redactions": redactions,
    }
