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
import psutil
from computer_mcp import security, agent_session, capabilities

def pipe_name():
    digest = hashlib.sha256(str(security.data_home().resolve()).lower().encode()).hexdigest()[:24]
    return r'\\.\pipe\IconControl-Consent-' + digest

_native_instances = {}

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
            if command[1:] != ['-I','-m','computer_mcp.consent','--broker-session',nonce]: continue
            allowed = {Path(sys.executable).with_name('pythonw.exe').resolve(),
                       Path(getattr(sys,'_base_executable',sys.executable)).with_name('pythonw.exe').resolve()}
            if Path(process.exe()).resolve() in allowed: return nonce
    except (psutil.Error, OSError): pass
    return None

def _native_client(pid,nonce=None):
    actual = _native_instance(pid)
    return bool(actual and isinstance(nonce,str) and __import__('hmac').compare_digest(actual,nonce))

def open_native():
    for nonce, record in list(_native_instances.items()):
        if record['process'].is_running(): return {'opened':True}
        _native_instances.pop(nonce,None)
    nonce=secrets.token_urlsafe(32)
    interpreter=Path(sys.executable).with_name('pythonw.exe')
    env=dict(os.environ,ICON_CONTROL_HOME=str(security.data_home()))
    env.pop('PYTHONPATH',None)
    process=subprocess.Popen([str(interpreter),'-I','-m','computer_mcp.consent','--broker-session',nonce],
        env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,cwd=str(interpreter.parent))
    _native_instances[nonce]={'process':psutil.Process(process.pid)}
    return {'opened':True}

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

def dispatch(message, pid):
    from computer_mcp import permission_bridge as bridge
    command = message.get('command')
    if command == 'open': return open_native()
    if command == 'authority':
        with bridge._lock:
            granted, _ = bridge.effective_state()
            matches = any(a['id'] == message.get('agent_session') and a['pid'] == pid
                          for a in agent_session.active())
            return dict(granted=bool(granted and matches and
                bridge._authorization.get('agent_session') == message.get('agent_session') and
                message.get('session') == bridge._session and
                message.get('revision') == bridge._revision))
    if command == 'emergency':
        # Any current-user caller may downgrade; no credentials can upgrade here.
        try: return bridge.write_state(False, client='emergency', event='action')
        except OSError: return dict(granted=False)
    if not _native_client(pid,message.get('ui_nonce')):
        raise PermissionError('Broker-launched native consent instance required')
    owner = 'native-'+str(pid)+'-'+str(psutil.Process(pid).create_time())
    if command == 'status':
        return dict(state=bridge.current_state(), agents=list(agent_session.active()))
    if command == 'grant':
        session = message.get('agent_session')
        if not any(a['id'] == session for a in agent_session.active()):
            raise ValueError('Agent session is no longer active')
        scopes = message.get('scopes')
        applications = message.get('applications')
        launches = message.get('launches', [])
        if not isinstance(launches, list) or len(launches)>20: raise ValueError('Invalid launch approvals')
        for item in launches:
            if capabilities.launch_record(item['exe'],item.get('arguments','')) != item:
                raise ValueError('Executable changed; approve it again')
        auth = dict(agent_session=session, scopes=scopes, applications=applications, launches=launches)
        if not capabilities.validate(auth): raise ValueError('Invalid scope selection')
        # Validate actual PID/create-time/executable, not caller supplied display names.
        for app in applications:
            if capabilities.process_record(app['pid']) != app:
                raise ValueError('Application identity changed; select it again')
            if _native_instance(app['pid']): raise ValueError('Permission UI is never a target')
        return bridge.write_state(True, client=owner, event='action', authorization=auth)
    if command == 'revoke': return bridge.write_state(False, client=owner, event='action')
    if command == 'heartbeat':
        return bridge.write_state(message.get('granted') is True, client=owner, event='hb')
    raise ValueError('Unsupported consent request')

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
    import win32con, win32file, win32pipe
    win32pipe.WaitNamedPipe(pipe_name(), timeout_ms)
    pipe = win32file.CreateFile(pipe_name(), win32con.GENERIC_READ | win32con.GENERIC_WRITE,
                               0, None, win32con.OPEN_EXISTING, win32con.FILE_FLAG_OVERLAPPED, None)
    try:
        win32pipe.SetNamedPipeHandleState(pipe, win32pipe.PIPE_READMODE_MESSAGE, None, None)
        _io(pipe, json.dumps(dict(command=command, **fields)).encode('utf-8'),timeout_ms)
        raw = _io(pipe,timeout_ms=timeout_ms)
        _io(pipe,b'ACK',timeout_ms)
        response = json.loads(raw.decode('utf-8'))
        if not response.get('ok'): raise PermissionError(response.get('error','Consent request failed'))
        return response['result']
    finally: win32file.CloseHandle(pipe)

def live_valid(state, identity):
    try:
        return request('authority',timeout_ms=80,agent_session=identity,session=state.get('session'),
                       revision=state.get('revision')).get('granted') is True
    except Exception: return False
