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


def identity(pid=None) -> str:
    """Stable agent identity: installation home + workspace.

    A restart keeps the same identity, so a time-boxed lease can cover a whole
    work session instead of one process. The workspace is the process cwd, which
    is what the host sets for an MCP child.
    """
    import hashlib
    home = str(security.data_home().resolve()).lower()
    workspace = ''
    try:
        workspace = str(Path(psutil.Process(pid or os.getpid()).cwd()).resolve()).lower()
    except (psutil.Error, OSError):
        try:
            workspace = str(Path.cwd().resolve()).lower()
        except OSError:
            workspace = ''
    return hashlib.sha256((home + '|' + workspace).encode('utf-8')).hexdigest()[:32]

@contextmanager
def bind(identity):
    token = _context.set(identity)
    try: yield
    finally: _context.reset(token)

def register(label=None):
    process = psutil.Process(os.getpid())
    record = dict(id=current(), pid=process.pid, created=process.create_time(),
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
            if (security.authentic(record) and
                    psutil.Process(record['pid']).create_time() == record['created']):
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
                psutil.Process(pid).create_time() == record['created']):
            return record
    except (OSError, ValueError, KeyError, TypeError, psutil.Error):
        pass
    return None
