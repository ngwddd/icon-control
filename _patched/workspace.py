"""Bound tool output to owned storage; external user files need native consent."""
from __future__ import annotations
import os
from pathlib import Path, PureWindowsPath
import re
from computer_mcp.security import data_home

_RESERVED = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', re.I)

def component(value: str) -> str:
    if (not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{0,79}', value)
            or value.endswith(('.', ' ')) or _RESERVED.match(value) or value in ('.', '..')):
        raise ValueError('Expected one safe output name; paths are not permitted')
    return value

def owned_path(root: Path, name: str) -> Path:
    """Reject traversal, alternate streams and reparse points, including parents."""
    root = Path(root).absolute()
    raw = str(name)
    win = PureWindowsPath(raw)
    if not raw or '\x00' in raw or '..' in win.parts:
        raise ValueError('Output must remain inside the dedicated workspace')
    candidate = Path(raw) if win.is_absolute() else root / raw
    # Reject drive-relative names and alternate data streams.
    if (win.drive and not win.is_absolute()) or ':' in str(candidate)[len(candidate.anchor):]:
        raise ValueError('Drive-relative paths and streams are forbidden')
    candidate = candidate.absolute()
    try:
        candidate.relative_to(root)
        candidate.resolve().relative_to(root.resolve())
    except ValueError:
        raise ValueError('Output must remain inside the dedicated workspace') from None
    for part in (candidate, *candidate.parents):
        if part.exists() and (part.is_symlink() or getattr(part, 'is_junction', lambda: False)()):
            raise ValueError('Reparse points are forbidden in output paths')
    for part in candidate.relative_to(root).parts:
        component(part)
    return candidate

def report_path(name: str) -> Path:
    return owned_path(data_home() / 'workspace' / 'reports', name)

def create_text(path: Path, text: str) -> None:
    """Exclusive creation prevents accidentally replacing an existing artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    owned_path(path.parent, str(path))
    with path.open('x', encoding='utf-8') as output:
        output.write(text)
        output.flush()
        os.fsync(output.fileno())
