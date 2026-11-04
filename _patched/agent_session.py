"""Runtime identities are assigned by transport, never by tool arguments."""
from __future__ import annotations
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import json
import os
import secrets
import re
import time
import psutil
from computer_mcp import security

_stdio_id = secrets.token_hex(24)
_context = ContextVar('icon_agent_session', default=None)

def current():
    return _context.get() or _stdio_id


def _workspace_digest(process):
    import hashlib
    workspace = str(Path(process.cwd()).resolve()).lower()
    home = str(security.data_home().resolve()).lower()
    return hashlib.sha256((home + '|' + workspace).encode('utf-8')).hexdigest()[:32]


def workspace_identity(pid=None, session=None) -> str:
    record = lookup(session or current(), pid or os.getpid())
    if record is None or not record.get('workspace_id'):
        raise PermissionError('Register this transport session before requesting its workspace')
    return record['workspace_id']


def identity(pid=None, session=None) -> str:
    """Freeze a subject to its first signed registration, independent of chdir."""
    import hashlib
    pid, session = pid or os.getpid(), session or current()
    workspace = workspace_identity(pid, session)
    return hashlib.sha256((workspace + '|' + session).encode('utf-8')).hexdigest()[:32]

@contextmanager
def bind(identity):
    token = _context.set(identity)
    try: yield
    finally: _context.reset(token)

def register(label=None):
    process = psutil.Process(os.getpid())
    previous = lookup(current(), process.pid)
    workspace_id = (previous or {}).get('workspace_id') or _workspace_digest(process)
    record = dict(workspace_id=workspace_id, id=current(), pid=process.pid, created=process.create_time(), exe=process.exe(),
                  label=(label or 'MCP process '+str(process.pid))[:120], checked_at=time.time())
    record['signature'] = security.signature(record, security.load_token())
    folder = security.data_home()/'state'/'sessions'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder/(current()+'.json')
    import tempfile
    with tempfile.NamedTemporaryFile(dir=folder, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        temporary.write_text(json.dumps(record), encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return record

def active():
    for path in (security.data_home()/'state'/'sessions').glob('*.json'):
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
            if lookup(record['id'], record['pid']) is not None:
                yield record
        except (OSError, ValueError, KeyError, psutil.Error):
            continue

def lookup(identity, pid):
    """Fresh verification of one peer; historical sessions cannot slow each event."""
    if not isinstance(identity, str) or not re.fullmatch(r'[0-9a-f]{48}', identity):
        return None
    try:
        path = security.data_home()/'state'/'sessions'/(identity+'.json')
        record = json.loads(path.read_text(encoding='utf-8'))
        if (record.get('id') == identity and record.get('pid') == pid and
                security.authentic(record) and
                psutil.Process(pid).create_time() == record['created'] and
                (not record.get('exe') or psutil.Process(pid).exe() == record['exe'])):
            return record
    except (OSError, ValueError, KeyError, TypeError, psutil.Error):
        pass
    return None
