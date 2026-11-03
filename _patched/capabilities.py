"""Human-selected scopes and application limits, independent of agent config."""
from __future__ import annotations
import os
import hashlib
from pathlib import Path
import psutil
from computer_mcp import agent_session

SCOPES = frozenset({'screen_read','input_observe','input','text_entry','window_close',
                    'clipboard_read','clipboard_write','file_write',
                    'file_delete','file_read','config_write','process'})

def required(spec, args):
    effects = set(spec.effects_for(args))
    needed = effects & SCOPES
    if effects & {'window','clipboard_write','control','compose'}: needed.add('input')
    return needed

def has_scope(scope):
    from computer_mcp import permission
    state = permission.status()
    return bool(state.get('granted') and scope in state.get('authorization',{}).get('scopes',[]))

def validate(authorization):
    if not isinstance(authorization, dict): return False
    return (isinstance(authorization.get('agent_session'), str) and
            len(authorization['agent_session']) == 48 and
            isinstance(authorization.get('scopes'), list) and
            set(authorization['scopes']) <= SCOPES and
            isinstance(authorization.get('applications'), list) and
            (authorization.get('agent_id') is None or
             (isinstance(authorization['agent_id'], str) and
              len(authorization['agent_id']) == 32)))

def launch_record(executable, arguments=''):
    path = Path(executable).resolve(strict=True)
    if path.suffix.lower() != '.exe': raise ValueError('Choose an executable file')
    with path.open('rb') as source:
        digest = hashlib.file_digest(source,'sha256').hexdigest()
    return dict(exe=str(path),arguments=str(arguments),sha256=digest)

def require_launch(executable, arguments=''):
    from computer_mcp import permission
    permission.require('run_script')
    if not has_scope('process'):
        raise permission.PermissionDenied('Process launch approval required')
    record = launch_record(executable, arguments)
    if record not in permission.status().get('authorization',{}).get('launches',[]):
        raise permission.PermissionDenied('Executable and arguments require exact human approval')
    return record

def check_scope(state, spec, args):
    auth = state.get('authorization', {})
    if not validate(auth):
        return 'Approval is missing or invalid; open the native control center'
    if auth['agent_session'] != agent_session.current():
        # A time-boxed lease covers every new process of the same identity.
        leased = auth.get('agent_id') and auth['agent_id'] == agent_session.identity()
        if not leased:
            return 'Approval belongs to a different Agent session; open the native control center'
    missing = required(spec, args) - set(auth['scopes'])
    if missing: return 'Human approval required for: '+', '.join(sorted(missing))
    return None

def process_record(pid):
    process = psutil.Process(int(pid))
    return {'pid': process.pid, 'created': process.create_time(), 'exe': process.exe()}

def check_target(state, hwnd=None, point=None):
    """Resolve at the execution point; title matches and config cannot expand this."""
    import win32gui
    import win32process
    if point is not None:
        hwnd = win32gui.WindowFromPoint(tuple(map(int, point)))
    if not hwnd: hwnd = win32gui.GetForegroundWindow()
    if not hwnd: return 'No target application'
    _, pid = win32process.GetWindowThreadProcessId(int(hwnd))
    try:
        process = psutil.Process(pid)
        command = process.cmdline()
        if ('computer_mcp.consent' in command or any(str(a).endswith('open-permissions.py') for a in command) or
                win32gui.GetWindowText(win32gui.GetAncestor(hwnd, 2)).startswith('Icon Control — Permissions')):
            return 'The native permission UI cannot be automated'
        record = process_record(pid)
        auth = state.get('authorization', {})
        if record not in auth.get('applications', []):
            return 'Target application is outside the human-approved application list'
    except (OSError, ValueError, psutil.Error):
        return 'Target application identity unavailable'
    return None

def require_target(hwnd=None, point=None):
    from computer_mcp import permission
    why = check_target(permission.status(), hwnd=hwnd, point=point)
    if why: raise permission.PermissionDenied(why)


def file_record(path):
    """Identity for one explicitly chosen external read, capped at one MiB."""
    from computer_mcp.workspace import owned_path
    path = Path(path).absolute()
    owned_path(path.parent, str(path))
    if path.stat().st_size > 1048576:
        raise ValueError('File exceeds the 1 MiB read limit')
    with path.open('rb') as source:
        data = source.read(1048577)
        stat = os.fstat(source.fileno())
    if len(data) > 1048576:
        raise ValueError('File exceeds the 1 MiB read limit')
    return dict(path=str(path), size=stat.st_size, mtime=stat.st_mtime_ns,
                sha256=hashlib.sha256(data).hexdigest())
