"""dataset/redact.py — 落盘前脱敏。

六类：身份证 / 银行卡 / 手机号 / 邮箱 / 凭据 token / 家目录路径。
剪贴板与键盘原文不在这里处理——它们根本不采集。
"""

from __future__ import annotations

import hashlib
import os
import re

PATTERNS = (
    ("id_card", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
    ("bank_card", re.compile(r"(?<!\d)\d{16,19}(?!\d)")),
    ("phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")),
    ("token", re.compile(r"(?:sk-|ghp_|gho_|xoxb-|AKIA)[A-Za-z0-9_\-]{8,}")),
)

MAX_STR = 400          # 单个字符串参数最多留这么多字符
# Drop content by semantic field, even if it contains no recognizable secret.
PRIVATE_KEYS = frozenset({'text','value','content','clipboard','password','passwd',
    'secret','token','authorization','body','input','keys','key','script','source',
    'query','title','window','command','cmd','condition','expect','labels','facts','params','variables'})
HOME = os.path.expanduser("~")
USER = os.path.basename(HOME)


def redact_text(s: str) -> tuple:
    """返回 (脱敏后的文本, 命中类型列表)。"""
    hits = []
    out = s
    for kind, pat in PATTERNS:
        if pat.search(out):
            hits.append(kind)
            out = pat.sub(f"<{kind}>", out)
    if HOME and HOME in out:
        out = out.replace(HOME, "~")
        hits.append("home_path")
    if USER and USER in out and len(USER) >= 3:
        out = out.replace(USER, "<user>")
        hits.append("username")
    return out, hits


def redact_args(args: dict) -> tuple:
    """递归脱敏参数字典，返回 (新字典, 命中类型集合)。"""
    hits = set()

    def walk(v):
        if isinstance(v, str):
            t, h = redact_text(v)
            hits.update(h)
            from computer_mcp import tool_registry
            safe_values = {'click','wait','type','move','left','right','middle','start','stop','status',
                           'text','template','baseline','stable','file','true','false'} | set(tool_registry.TOOLS)
            if not h and v not in safe_values:
                hits.add('private_content')
                return '<private>'
            return t if len(t) <= MAX_STR else t[:MAX_STR] + "…"
        if isinstance(v, dict):
            out = {}
            for k, x in v.items():
                normalized = str(k).lower().replace('-', '_')
                if normalized in PRIVATE_KEYS or any(s in normalized for s in ('password','secret','token','clipboard')):
                    out[k] = '<private>'
                    hits.add('private_content')
                else:
                    out[k] = walk(x)
            return out
        if isinstance(v, (list, tuple)):
            return [walk(x) for x in v]
        return v

    return walk(args or {}), sorted(hits)


def target_of(args: dict) -> dict:
    """只留可公开的定位信息：hwnd / process / 标题哈希。"""
    out = {}
    for k in ("hwnd", "pid", "process", "window", "title"):
        if k in (args or {}):
            v = args[k]
            if k in ("title", "window") and isinstance(v, str):
                out[k + "_hash"] = hashlib.sha1(v.encode()).hexdigest()[:12]
            elif isinstance(v, (int, str)):
                out[k] = v if not isinstance(v, str) else v[:40]
    return out


def is_sensitive(text: str) -> bool:
    return any(p.search(text or "") for _, p in PATTERNS)
