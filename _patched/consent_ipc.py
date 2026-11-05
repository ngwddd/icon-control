"""Current-user Windows pipe. Only the native consent process can mutate grants."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import subprocess
import time
from collections import deque
import psutil
from computer_mcp import security, agent_session, capabilities

def pipe_name():
    digest = hashlib.sha256(str(security.data_home().resolve()).lower().encode()).hexdigest()[:24]
    return r'\\.\pipe\IconControl-Consent-' + digest

_native_instances = {}

class _ConnectionQueue:
    """FIFO prevents a busy caller repeatedly overtaking an older permission check."""
    def __init__(self):
        self.condition=threading.Condition();self.pending=deque()
    def acquire(self,deadline):
        ticket=object()
        with self.condition:
            self.pending.append(ticket)
            try:
                while self.pending[0] is not ticket:
                    remaining=deadline-time.monotonic()
                    if remaining<=0:raise TimeoutError('Permission IPC connection deadline exceeded')
                    self.condition.wait(remaining)
                return ticket
            except BaseException:
                self.pending.remove(ticket);self.condition.notify_all()
                raise
    def release(self,ticket):
        with self.condition:
            self.pending.remove(ticket);self.condition.notify_all()

_request_queue=_ConnectionQueue()

def _matches_consent_command(command, nonce):
    """True when ``command`` is this bridge's consent host for ``nonce``.

    The trailing intent is optional so hosts started before v1.3.9 keep
    validating, but an unknown intent is never accepted.
    """
    base = ['-I', '-m', 'computer_mcp.consent', '--broker-session', nonce]
    tail = list(command[1:])
    if tail[:len(base)] != base:
        return False
    rest = tail[len(base):]
    if not rest:
        return True
    return rest in (['--intent=background'], ['--intent=show'])


def _native_instance(pid):
    try:
        process = psutil.Process(pid)
        command = process.cmdline()
        for nonce, record in list(_native_instances.items()):
            root = record['process']
            if not root.is_running():
                _native_instances.pop(nonce,None);continue
            # A Windows venv launcher may have exactly one interpreter child.
            if process.pid != root.pid and process.ppid() != root.pid: continue
            if not _matches_consent_command(command, nonce): continue
            allowed = {Path(sys.executable).with_name('pythonw.exe').resolve(),
                       Path(getattr(sys,'_base_executable',sys.executable)).with_name('pythonw.exe').resolve()}
            if Path(process.exe()).resolve() in allowed: return nonce
    except (psutil.Error, OSError): pass
    return None

def _native_client(pid,nonce=None):
    actual = _native_instance(pid)
    return bool(actual and isinstance(nonce,str) and __import__('hmac').compare_digest(actual,nonce))

def _post_show():
    """Wake a running consent host instead of spawning a second one."""
    try:
        import win32gui
        hwnd = win32gui.FindWindow('IconControlConsentHost', None)
        if hwnd:
            win32gui.PostMessage(hwnd, 0x8000 + 2, 0, 0)      # WM_APP+2: show
            return True
    except Exception:
        pass
    return False


def _host_window_exists():
    try:
        import win32gui
        return bool(win32gui.FindWindow('IconControlConsentHost', None))
    except Exception:
        return False


def open_native(intent='show'):
    """Start (or wake) the consent host.

    ``intent='show'`` is the explicit user path (protocol handler, tray, a tool
    request that needs approval) and may raise the window. ``background`` starts
    the host for its tray icon and lease upkeep only: it never wakes an existing
    window and the new host starts silently.
    """
    if intent not in ('background', 'show'):
        raise ValueError('Unknown consent intent: ' + str(intent)[:32])
    if intent == 'background' and _host_window_exists():
        return {'opened':True,'woken':False}
    for nonce, record in list(_native_instances.items()):
        if record['process'].is_running():
            if intent == 'show':
                _post_show()
            return {'opened':True,'woken':intent=='show'}
        _native_instances.pop(nonce,None)
    nonce=secrets.token_urlsafe(32)
    interpreter=Path(sys.executable).with_name('pythonw.exe')
    env=dict(os.environ,ICON_CONTROL_HOME=str(security.data_home()))
    env.pop('PYTHONPATH',None)
    process=subprocess.Popen([str(interpreter),'-I','-m','computer_mcp.consent','--broker-session',nonce,
                              '--intent='+intent],
        env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,cwd=str(interpreter.parent))
    _native_instances[nonce]={'process':psutil.Process(process.pid)}
    return {'opened':True,'woken':False}


def ensure_background_host():
    """Best-effort silent host so the tray exists without a window."""
    try:
        return open_native('background')
    except Exception:
        return {'opened':False}

def _io(pipe, payload=None, timeout_ms=200):
    import pywintypes, win32event, win32file
    operation = pywintypes.OVERLAPPED()
    operation.hEvent = win32event.CreateEvent(None, True, False, None)
    try:
        if payload is None:
            _, buffer = win32file.ReadFile(pipe, 65536, operation)
        else:
            buffer = payload
            win32file.WriteFile(pipe, buffer, operation)
        if win32event.WaitForSingleObject(operation.hEvent, timeout_ms) != win32event.WAIT_OBJECT_0:
            # This function owns every I/O on this handle in the issuing thread.
            win32file.CancelIo(pipe)
            try: win32file.GetOverlappedResult(pipe,operation,True)
            except pywintypes.error: pass
            raise TimeoutError('Permission IPC deadline exceeded')
        count = win32file.GetOverlappedResult(pipe, operation, False)
        return bytes(buffer[:count]) if payload is None else None
    finally: operation.hEvent.Close()

from computer_mcp.consent_requests import RequestQueue
_requests = RequestQueue()
_grant_operations = {}
GRANT_RECEIPT_TTL = 600


def _prune_operations():
    now = time.time()
    for key, record in list(_grant_operations.items()):
        if now - record['created_at'] > GRANT_RECEIPT_TTL:
            del _grant_operations[key]


def confirmed_grant(ipc, **fields):
    """A lost reply is unknown until read-back; cancel by ID on any failure."""
    operation_id = secrets.token_hex(24)
    try:
        ipc('grant', operation_id=operation_id, **fields)
        receipt = ipc('grant_status', operation_id=operation_id)
        if receipt.get('status') != 'confirmed':
            raise PermissionError('Grant read-back did not confirm this operation')
        return receipt['state']
    except Exception:
        try:
            ipc('cancel_grant', operation_id=operation_id)
        except Exception:
            pass
        raise


def dispatch(message, pid):
    from computer_mcp import permission_bridge as bridge
    # Requests and grants are serialized together. A dialog cannot approve a
    # replaced snapshot or interleave grant ownership with another request.
    with bridge._lock:
        return _dispatch(message, pid)


def _dispatch(message, pid):
    from computer_mcp import permission_bridge as bridge
    command = message.get('command')
    if command == 'open':
        session = message.get('prefer_session')
        request_id = None
        if session is not None:
            record = _requests.create(pid, session, message.get('prefer_app'),
                                      message.get('prefer_scopes'))
            request_id = record['request_id']
        elif any(key in message for key in ('prefer_app', 'prefer_scopes')):
            raise PermissionError('An application request requires a verified caller')
        return {**open_native(), 'request_id': request_id}
    if command == 'request_status':
        # Caller-scoped, read-only lookup; never expose another Agent's request
        # or let a cache turn a terminal request back into a pending one.
        session = message.get('agent_session')
        if agent_session.lookup(session, pid) is None:
            raise PermissionError('Requested Agent does not belong to this pipe peer')
        record = _requests.get(message.get('request_id'))
        if record['agent_session'] != session or record['peer']['pid'] != pid:
            raise PermissionError('Consent request belongs to another caller')
        return dict(request_id=record['request_id'], status=record['status'])
    if command == 'diagnose':
        return _diagnose(message, pid)
    if command == 'authority':
        with bridge._lock:
            granted, _ = bridge.effective_state()
            ident = message.get('agent_session')
            matches = agent_session.lookup(ident, pid) is not None
            auth = bridge._authorization or {}
            same_session = auth.get('agent_session') == ident
            return dict(granted=bool(granted and matches and same_session and
                message.get('session') == bridge._session and
                message.get('revision') == bridge._revision))
    if command == 'emergency':
        # Any current-user caller may downgrade; no credentials can upgrade here.
        try: return bridge.write_state(False, client='emergency', event='action')
        except OSError: return dict(granted=False)
    if not _native_client(pid,message.get('ui_nonce')):
        raise PermissionError('Broker-launched native consent instance required')
    owner = 'native-'+str(pid)+'-'+str(psutil.Process(pid).create_time())
    if command in ('grant_status', 'cancel_grant'):
        _prune_operations()
        operation_id = message.get('operation_id')
        if not isinstance(operation_id, str) or len(operation_id) != 48:
            raise ValueError('Invalid grant operation ID')
        receipt = _grant_operations.get(operation_id)
        if receipt and receipt['owner'] != owner:
            raise PermissionError('Grant receipt belongs to another native client')
        if command == 'cancel_grant':
            if receipt is None and len(_grant_operations) >= 256:
                raise ValueError('Grant receipt queue is full')
            _grant_operations[operation_id] = dict(owner=owner, status='cancelled', created_at=time.time())
            if bridge._authorization.get('grant_operation') == operation_id:
                bridge.write_state(False, client=owner, event='action')
            return dict(status='cancelled')
        state = bridge.current_state()
        confirmed = (receipt and receipt['status'] == 'confirmed' and
                     state.get('granted') and
                     state.get('authorization', {}).get('grant_operation') == operation_id)
        return dict(status='confirmed' if confirmed else 'unavailable',
                    **({'state': state} if confirmed else {}))
    if command == 'status':
        return dict(state=bridge.current_state(), agents=list(agent_session.active()),
                    requests=_requests.pending())
    if command == 'request_show':
        return _requests.get(message['request_id'], display=True)
    if command == 'request_target':
        app = message['application']
        if _native_instance(app['pid']):
            raise PermissionError('Permission UI is never a target')
        return _requests.bind_target(message['request_id'], app)
    if command == 'request_deny':
        return _requests.finish(message['request_id'], 'denied')
    if command == 'request_satisfied':
        request_id = message['request_id']
        satisfied, _ = _requests.satisfies(request_id, bridge.current_state())
        if not satisfied:
            raise PermissionError('The current authorization does not satisfy this request')
        return _requests.finish(request_id, 'consumed')
    if command == 'grant':
        operation_id = message.get('operation_id')
        if operation_id is not None:
            _prune_operations()
            if not isinstance(operation_id, str) or len(operation_id) != 48:
                raise ValueError('Invalid grant operation ID')
            if operation_id in _grant_operations:
                raise PermissionError('Grant operation has already been used or cancelled')
            if len(_grant_operations) >= 256:
                raise ValueError('Grant receipt queue is full')
            _grant_operations[operation_id] = dict(owner=owner, status='pending', created_at=time.time())
        session = message.get('agent_session')
        live = list(agent_session.active())
        record = next((a for a in live if a['id'] == session), None)
        if record is None:
            raise ValueError('Agent session is no longer active')
        scopes = message.get('scopes')
        applications = message.get('applications')
        launches = message.get('launches', [])
        if not isinstance(launches, list) or len(launches)>20: raise ValueError('Invalid launch approvals')
        for item in launches:
            if capabilities.launch_record(item['exe'],item.get('arguments','')) != item:
                raise ValueError('Executable changed; approve it again')
        read_files = message.get('read_files', [])
        if not isinstance(read_files, list) or len(read_files) > 20:
            raise ValueError('Invalid file approvals')
        for record_file in read_files:
            if capabilities.file_record(record_file['path']) != record_file:
                raise ValueError('External file changed; approve again')
        request_id = message.get('request_id')
        if request_id is not None:
            pending = _requests.get(request_id)
            if (pending['status'] != 'displayed' or pending['agent_session'] != session or
                    pending['application'] is None or applications != [pending['application']] or
                    not set(pending['scopes']) <= set(scopes or [])):
                raise PermissionError('Grant does not match the displayed request')
        auth = dict(agent_session=session, scopes=scopes, applications=applications,
                    launches=launches, read_files=read_files,
                    agent_peer={'pid': record['pid'], 'created': record['created']},
                    grant_operation=operation_id)
        lease_minutes = message.get('lease_minutes')
        if lease_minutes is not None:
            if not isinstance(lease_minutes, int) or not 1 <= lease_minutes <= 240:
                raise ValueError('Invalid lease length')
            # The lease names this exact transport session within its workspace.
            auth['agent_id'] = agent_session.identity(record['pid'], session)
            auth['lease_expires_at'] = time.time() + lease_minutes * 60
        if not capabilities.validate(auth): raise ValueError('Invalid scope selection')
        # Validate actual PID/create-time/executable, not caller supplied display names.
        for app in applications:
            if capabilities.process_record(app['pid']) != app:
                raise ValueError('Application identity changed; select it again')
            if _native_instance(app['pid']): raise ValueError('Permission UI is never a target')
        # Approve the displayed snapshot under the same broker lock as the
        # grant write. Approved requests are consumed once, never re-displayed.
        if request_id is not None:
            _requests.finish(request_id, 'approved')
        try:
            state = bridge.write_state(True, client=owner, event='action', authorization=auth)
        except Exception:
            if request_id is not None:
                try:
                    _requests.finish(request_id, 'denied')
                except Exception:
                    pass
            try:
                bridge.write_state(False, client=owner, event='action')
            except Exception:
                pass
            raise
        if request_id is not None:
            _requests.finish(request_id, 'consumed' if state.get('granted') else 'denied')
        if operation_id is not None:
            _grant_operations[operation_id]['status'] = 'confirmed' if state.get('granted') else 'denied'
        return state
    if command == 'revoke': return bridge.write_state(False, client=owner, event='action')
    if command == 'heartbeat':
        return bridge.write_state(message.get('granted') is True, client=owner, event='hb')
    raise ValueError('Unsupported consent request')

def _diagnose(message, pid):
    from computer_mcp import permission_bridge as bridge
    session = message.get('agent_session')
    peer = agent_session.lookup(session, pid)
    if peer is None:
        raise PermissionError('Diagnostics must originate from the actual Agent')
    scopes = message.get('scopes', [])
    if not isinstance(scopes, list) or not set(scopes) <= capabilities.SCOPES:
        raise ValueError('Unknown diagnostic capabilities')
    app = message.get('application')
    if app is not None and capabilities.process_record(app['pid']) != app:
        raise PermissionError('Diagnostic target identity changed')
    state = bridge.current_state()
    auth = state.get('authorization') or {}
    same = auth.get('agent_session') == session
    missing = sorted(set(scopes) - set(auth.get('scopes', []))) if same else sorted(set(scopes))
    target_ok = app is None or app in auth.get('applications', [])
    granted = bool(state.get('granted') and same and target_ok and not missing)
    reason = ('approved' if granted else 'bridge_not_authorized' if not state.get('granted')
              else 'different_agent' if not same else 'target_not_approved' if not target_ok
              else 'missing_scopes')
    return dict(agent_session=session, peer_pid=pid, peer_created=peer['created'],
                workspace_id=agent_session.workspace_identity(pid, session),
                caller_identity=agent_session.identity(pid, session),
                approved_agent=(auth.get('agent_session') or '')[:10],
                requested_scopes=sorted(set(scopes)), approved_scopes=auth.get('scopes', []),
                missing_scopes=missing, target=app, bridge_granted=bool(state.get('granted')),
                caller_granted=granted, reason=reason, checked_at=time.time())


def serve(ready=None, failures=None):
    import pywintypes
    import win32api, win32con, win32file, win32pipe, win32security, win32event
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    sddl = 'D:P(A;;GA;;;SY)(A;;GA;;;'+win32security.ConvertSidToStringSid(sid)+')'
    attributes = pywintypes.SECURITY_ATTRIBUTES()
    attributes.SECURITY_DESCRIPTOR = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(sddl, 1)
    get_pid = ctypes.windll.kernel32.GetNamedPipeClientProcessId
    get_pid.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
    get_pid.restype = wintypes.BOOL
    # Keep one server handle for the entire lifetime; reject remote clients.
    pipe = win32pipe.CreateNamedPipe(pipe_name(), win32pipe.PIPE_ACCESS_DUPLEX | 0x00080000 | win32con.FILE_FLAG_OVERLAPPED,
        win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT | 0x8,
        1, 65536, 65536, 2000, attributes)
    if ready is not None: ready.set()
    try:
        while True:
            try:
                connection = pywintypes.OVERLAPPED()
                connection.hEvent = win32event.CreateEvent(None,True,False,None)
                try: win32pipe.ConnectNamedPipe(pipe, connection)
                except pywintypes.error as exc:
                    if exc.winerror == 535: win32event.SetEvent(connection.hEvent)
                    elif exc.winerror != 997: raise
                win32event.WaitForSingleObject(connection.hEvent, win32event.INFINITE)
                connection.hEvent.Close()
                pid = wintypes.ULONG()
                if not get_pid(int(pipe), ctypes.byref(pid)): raise PermissionError('Unknown pipe peer')
                raw = _io(pipe)
                request = json.loads(raw.decode('utf-8'))
                response = dict(ok=True, result=dispatch(request, pid.value))
            except Exception as exc:
                from computer_mcp.permission_bridge import log
                log('IPC read/dispatch failure '+type(exc).__name__+' '+str(getattr(exc,'winerror','')))
                response = dict(ok=False, error=type(exc).__name__)
            try:
                _io(pipe, json.dumps(response).encode('utf-8'))
                # DisconnectNamedPipe discards unread replies. A bounded ACK
                # establishes delivery without FlushFileBuffers blocking forever.
                if _io(pipe) != b'ACK': raise ValueError('Missing delivery acknowledgement')
            except (pywintypes.error, TimeoutError, ValueError) as exc:
                from computer_mcp.permission_bridge import log
                log('IPC response failure '+type(exc).__name__+' '+str(getattr(exc,'winerror','')))
            finally:
                try: win32pipe.DisconnectNamedPipe(pipe)
                except pywintypes.error: pass
    finally: win32file.CloseHandle(pipe)

def request(command, timeout_ms=200, **fields):
    import pywintypes,win32con,win32file,win32pipe
    deadline=time.monotonic()+max(1,timeout_ms)/1000
    def remaining():
        milliseconds=int((deadline-time.monotonic())*1000)
        if milliseconds<=0:raise TimeoutError('Permission IPC deadline exceeded')
        return milliseconds
    ticket=_request_queue.acquire(deadline)
    pipe=None
    try:
        while pipe is None:
            win32pipe.WaitNamedPipe(pipe_name(),remaining())
            try:
                pipe=win32file.CreateFile(pipe_name(),win32con.GENERIC_READ|win32con.GENERIC_WRITE,
                    0,None,win32con.OPEN_EXISTING,win32con.FILE_FLAG_OVERLAPPED,None)
            except pywintypes.error as exc:
                if exc.winerror!=231:raise
                # WaitNamedPipe is advisory: another client can win CreateFile.
                # Retry only that connection race, within the original deadline.
                time.sleep(min(.001,remaining()/1000))
        win32pipe.SetNamedPipeHandleState(pipe, win32pipe.PIPE_READMODE_MESSAGE, None, None)
        _io(pipe,json.dumps(dict(command=command,**fields)).encode('utf-8'),remaining())
        raw=_io(pipe,timeout_ms=remaining())
        _io(pipe,b'ACK',remaining())
        response = json.loads(raw.decode('utf-8'))
        if not response.get('ok'): raise PermissionError(response.get('error','Consent request failed'))
        return response['result']
    finally:
        try:
            if pipe is not None:win32file.CloseHandle(pipe)
        finally:_request_queue.release(ticket)

def live_valid(state, identity):
    try:
        return request('authority',timeout_ms=80,agent_session=identity,session=state.get('session'),
                       revision=state.get('revision')).get('granted') is True
    except Exception: return False
