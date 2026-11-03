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

def readable_path(name, root=None):
    from computer_mcp import capabilities, permission
    if not capabilities.has_scope('file_read'):
        raise permission.PermissionDenied('Dedicated file read approval required')
    try:
        return owned_path(root or data_home() / 'workspace' / 'files', str(name))
    except ValueError:
        if root is not None:
            raise
        state = permission.status()
        if capabilities.file_record(name) not in state.get('authorization', {}).get('read_files', []):
            raise permission.PermissionDenied('External file needs an exact native approval')
        return Path(name).absolute()


def read_text(name, root=None, encoding='utf-8'):
    from computer_mcp import permission, execution
    before = execution.authority_stamp(permission.status())
    path = readable_path(name, root)
    with path.open('rb') as source:
        data = source.read(1048577)
    if len(data) > 1048576:
        raise ValueError('File exceeds the 1 MiB read limit')
    if execution.authority_stamp(permission.status()) != before:
        raise permission.PermissionDenied('File read authority changed')
    readable_path(name, root)
    return data.decode(encoding, errors='replace')


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
