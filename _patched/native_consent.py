"""Single-window consent host: tray icon, global hotkey, native approval dialog.

The host is a long-lived background process. It owns the approval window, keeps
the lease alive with heartbeats, and can be woken from the tray or a hotkey.
"""
from __future__ import annotations

import ctypes
import os
import sys
import time
import threading
import queue
from functools import wraps
from ctypes import wintypes

from computer_mcp import agent_session, capabilities, consent_ipc, native_dialog, native_tray, permission

WM_APP = 0x8000
WM_TRAY = WM_APP + 1
WM_SHOW = WM_APP + 2
WM_HEARTBEAT_RESULT = WM_APP + 3
WM_TIMER_HEARTBEAT = 1
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_QUERYENDSESSION = 0x0011
WM_HOTKEY = 0x0312
WM_RBUTTONUP = 0x0205
WM_LBUTTONDBLCLK = 0x0203
TIMER_MS = 4000
LEASE_MINUTES = 60
CLASS_NAME = 'IconControlConsentHost'
MUTEX_NAME = 'IconControl.ConsentHost'
MOD_ALT, MOD_CONTROL, MOD_SHIFT = 0x0001, 0x0002, 0x0004
HOTKEYS = (
    ('Ctrl+Alt+Shift+F9', MOD_CONTROL | MOD_ALT | MOD_SHIFT, 0x78),
    ('Ctrl+Alt+Shift+F7', MOD_CONTROL | MOD_ALT | MOD_SHIFT, 0x76),
    ('Ctrl+Alt+Shift+F12', MOD_CONTROL | MOD_ALT | MOD_SHIFT, 0x7B),
    ('Ctrl+Alt+Shift+G', MOD_CONTROL | MOD_ALT | MOD_SHIFT, 0x47),
)
ID_OPEN, ID_REVOKE, ID_QUIT = 1, 2, 3

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [('style', wintypes.UINT), ('lpfnWndProc', WNDPROC),
                ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int),
                ('hInstance', wintypes.HINSTANCE), ('hIcon', wintypes.HICON),
                ('hCursor', wintypes.HANDLE), ('hbrBackground', wintypes.HBRUSH),
                ('lpszMenuName', wintypes.LPCWSTR), ('lpszClassName', wintypes.LPCWSTR)]


class POINT(ctypes.Structure):
    _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]


class MSG(ctypes.Structure):
    _fields_ = [('hwnd', wintypes.HWND), ('message', wintypes.UINT),
                ('wParam', wintypes.WPARAM), ('lParam', wintypes.LPARAM),
                ('time', wintypes.DWORD), ('pt', POINT)]


def _state_action(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with self._state_lock:
            self._state_generation += 1
            return method(self, *args, **kwargs)
    return guarded


class ConsentHost:
    def __init__(self, nonce: str):
        self._state_lock = threading.RLock()
        self._state_generation = 0
        self._heartbeat_results = queue.Queue(maxsize=4)
        self.nonce = nonce
        self.user32 = ctypes.WinDLL('user32', use_last_error=True)
        self.kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        self.hwnd = 0
        self.tray = False
        self.granted = False
        self.lease_until = 0.0
        self.authorization: dict = {}
        self.hotkey = ''
        self._stopping = False
        self._showing = False
        self.state_unknown = False
        self._wndproc = WNDPROC(self._on_message)

    # -- plumbing ---------------------------------------------------------
    def ipc(self, command, **fields):
        return consent_ipc.request(command, ui_nonce=self.nonce, **fields)

    def _tip(self) -> str:
        if self.state_unknown:
            return 'Icon Control · 状态未知 · 请检查连接'
        if not self.granted:
            return f'Icon Control · 未授权 · {self.hotkey or "热键"} 打开'
        left = max(0, int(self.lease_until - time.time()))
        return f'Icon Control · {(self.authorization.get("agent_session") or "")[:10]} 已授权 · 剩 {left // 60}:{left % 60:02d}'

    def _refresh_tray(self):
        if self.tray:
            native_tray.update(self.hwnd, 1, self._tip())
        self._write_status()

    def _write_status(self):
        """Small diagnostic file so doctor.py can see what the host actually bound."""
        try:
            import json
            from computer_mcp import security
            path = security.data_home() / 'state' / 'consent-host.json'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(dict(pid=os.getpid(), hwnd=int(self.hwnd),
                                            hotkey=self.hotkey, tray=bool(self.tray),
                                            granted=self.granted if not self.state_unknown else None,
                                            agent_session=self.authorization.get('agent_session'),
                                            lease_expires_at=self.lease_until),
                                       ensure_ascii=False), encoding='utf-8')
        except Exception:
            pass

    # -- actions ----------------------------------------------------------
    def _foreground_app(self) -> dict | None:
        try:
            import win32gui
            import win32process
            candidates = []
            front = win32gui.GetForegroundWindow()
            if front:
                candidates.append(front)
            hwnd = win32gui.GetTopWindow(None)
            while hwnd:
                candidates.append(hwnd)
                hwnd = win32gui.GetWindow(hwnd, 2)      # GW_HWNDNEXT
            applications, seen = [], set()
            for hwnd in candidates:
                title = win32gui.GetWindowText(hwnd)
                if not title or title.startswith('Icon Control'):
                    continue
                if not win32gui.IsWindowVisible(hwnd):
                    continue
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if not pid or pid == os.getpid() or pid in seen:
                    continue
                record = capabilities.process_record(pid)
                record['title'] = title[:80]
                applications.append(record)
                seen.add(pid)
            return native_dialog.choose_application(applications)
        except Exception:
            pass
        return None

    def _pick_agent(self, pending=None):
        live = [a for a in agent_session.active() if a.get('pid') != os.getpid()]
        if pending is not None:
            return next((a for a in live if a['id'] == pending), None)
        return native_dialog.choose_agent(live)

    @_state_action
    def _sync(self):
        """Trust the bridge, never the local flag, before showing anything."""
        try:
            state = (self.ipc('status') or {}).get('state') or {}
        except Exception:
            self.state_unknown = True
            self.granted = False
            return False
        self.state_unknown = False
        if state.get('granted') and state.get('authorization'):
            self.granted = True
            self.authorization = state['authorization']
            self.lease_until = float(state['authorization'].get('lease_expires_at')
                                     or self.lease_until)
        elif not state.get('granted'):
            self.granted = False
            self.authorization = {}
            self.lease_until = 0.0
        return True

    def show(self):
        if self._showing:
            return
        self._showing = True
        try:
            self._show_once()
        finally:
            self._showing = False

    def _show_once(self):
        if not self._sync():
            native_dialog.ask_notice('授权状态未知', '无法连接授权桥，请稍后重试。')
            return
        try:
            status = self.ipc('status')
            pending = (status.get('requests') or [None])[0]
            if pending:
                pending = self.ipc('request_show', request_id=pending['request_id'])
        except Exception as exc:
            native_dialog.ask_notice('授权请求不可用', str(exc)[:200])
            return
        if pending is None and self.granted:
            left = max(0, int(self.lease_until - time.time()))
            answer = native_dialog.ask_status(
                '已确认的会话授权',
                f"Agent：{self.authorization.get('agent_session', '')[:10]}" + chr(13) + chr(10) +
                f"范围：{', '.join(self.authorization.get('scopes') or [])}",
                remaining=f'剩余 {left // 60} 分 {left % 60} 秒')
            if answer:
                if answer['action'] == 'revoke':
                    self.revoke()
                elif answer['action'] == 'renew':
                    self._renew()
                elif answer['action'] == 'pending':
                    self._show_once()
                elif answer['action'] == 'quit':
                    self.revoke()
                    self.user32.DestroyWindow(self.hwnd)
            return
        agent = self._pick_agent(pending['agent_session'] if pending else None)
        if agent is None:
            native_dialog.ask_notice('请求方不可用', '请选择活跃会话；失效请求不会转交给其他 Agent。')
            return
        app = pending['application'] if pending else None
        if app is not None:
            try:
                if capabilities.process_record(app['pid']) != app:
                    raise ValueError('请求的目标进程已改变')
            except Exception as exc:
                native_dialog.ask_notice('目标应用不可用', str(exc)[:200])
                return
        else:
            app = self._foreground_app()
            if app is None:
                native_dialog.ask_notice('请选择目标应用', '请先切换到目标应用，再处理本次请求。')
                return
            if pending:
                try:
                    app = {k: app[k] for k in ('pid', 'created', 'exe')}
                    pending = self.ipc('request_target', request_id=pending['request_id'], application=app)
                except Exception as exc:
                    native_dialog.ask_notice('目标选择失败', str(exc)[:200])
                    return
        needs = pending['scopes'] if pending else None
        note = ''
        if pending:
            auth = self.authorization
            if self.granted and auth.get('agent_session') != agent['id']:
                note = '授权属于其他会话。确认后将为当前请求方原子替换原授权。'
            elif self.granted and app not in auth.get('applications', []):
                note = '当前请求的应用尚未授权。'
            elif self.granted:
                missing = set(needs) - set(auth.get('scopes', []))
                if not missing:
                    try:
                        self.ipc('request_satisfied', request_id=pending['request_id'])
                        native_dialog.ask_notice('当前请求已满足', '实际请求方、目标应用和权限均已匹配。')
                    except Exception as exc:
                        native_dialog.ask_notice('请求已失效', str(exc)[:200])
                    return
                note = '需要补授权：' + ', '.join(sorted(missing))
        answer = native_dialog.ask_grant(
            agent_label=(f"{agent.get('label', 'Agent')} · {agent['id'][:10]} · PID {agent['pid']}"
                         + (f" · 工作区 {pending['workspace_id'][:10]} · 请求 {pending['request_id'][:10]}" if pending else "")),
            target_text=f"{os.path.basename(app['exe'])} · PID {app['pid']}",
            default_preset=native_dialog.preset_for(needs),
            lease_minutes=LEASE_MINUTES, note=note, needs=needs)
        if answer is None or not answer['accepted']:
            if pending:
                try:
                    self.ipc('request_deny', request_id=pending['request_id'])
                except Exception:
                    pass
            return
        self._apply(agent['id'], answer['scopes'], app, answer['lease_minutes'],
                    request_id=pending['request_id'] if pending else None)

    @_state_action
    def _apply(self, agent_session_id, scopes, app, lease_minutes, request_id=None):
        try:
            result = consent_ipc.confirmed_grant(self.ipc, agent_session=agent_session_id, scopes=list(scopes),
                              applications=[{k: app[k] for k in ('pid', 'created', 'exe')}],
                              launches=[], read_files=[], lease_minutes=lease_minutes, request_id=request_id)
        except Exception as exc:
            self.granted = False
            self.state_unknown = True
            self._refresh_tray()
            native_dialog.ask_notice('授权状态未知', str(exc)[:300])
            return
        if result.get('granted') is not True:
            native_dialog.ask_notice('后端未确认授权', str(result)[:300])
            return
        auth = result.get('authorization') or {}
        self.state_unknown = False
        self.granted = True
        self.authorization = auth
        self.lease_until = float(auth.get('lease_expires_at') or (time.time() + LEASE_MINUTES * 60))
        self._refresh_tray()
        if self.tray:
            native_tray.balloon(self.hwnd, 1, 'Icon Control',
                                f'已授权 {LEASE_MINUTES} 分钟：{os.path.basename(app["exe"])}')

    def _renew(self):
        if not self.authorization:
            return
        apps = self.authorization.get('applications') or []
        agent = self.authorization.get('agent_session')
        scopes = self.authorization.get('scopes') or []
        if not apps or not agent:
            return
        record = dict(apps[0])
        self._apply(agent, scopes, record, LEASE_MINUTES)

    @_state_action
    def revoke(self):
        # Stop positive renewal before the IPC request. A failed revoke is
        # repaired by negative heartbeats and remains visibly unknown meanwhile.
        self.granted = False
        try:
            state = self.ipc('revoke')
            if state.get('granted') is not False:
                raise RuntimeError('Backend did not confirm revocation')
            self.state_unknown = False
            self.authorization = {}
            self.lease_until = 0.0
        except Exception:
            self.state_unknown = True
            native_dialog.ask_notice('撤销状态未知', '通信未确认撤销，已停止正向续期，将重试否定心跳。')
        self._refresh_tray()

    # -- message handling -------------------------------------------------
    def _on_message(self, hwnd, message, wparam, lparam):
        if message == WM_SHOW:
            self.show()
            return 0
        if message == WM_HOTKEY:
            self.show()
            return 0
        if message == WM_HEARTBEAT_RESULT:
            self._receive_heartbeat()
            return 0
        if message == WM_TIMER_HEARTBEAT:
            self._heartbeat()
            return 0
        if message == WM_TRAY:
            if (lparam & 0xFFFF) in (WM_RBUTTONUP, WM_LBUTTONDBLCLK):
                self._menu()
            return 0
        if message == WM_QUERYENDSESSION:
            return 1
        if message == WM_CLOSE:
            self.user32.DestroyWindow(hwnd)
            return 0
        if message == WM_DESTROY:
            self.user32.PostQuitMessage(0)
            return 0
        return self.user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _heartbeat_loop(self):
        """A modal dialog blocks WM_TIMER, so the lease is kept alive off-thread."""
        while not self._stopping:
            time.sleep(TIMER_MS / 1000.0)
            try:
                self._heartbeat()
            except Exception:
                pass

    def _heartbeat(self):
        # Only IPC runs on the worker. UI/tray and local state mutate on the
        # window thread, with a generation fence around grant/revoke/renew.
        with self._state_lock:
            if not self.granted and not self.state_unknown:
                return
            generation = self._state_generation
            desired = self.granted and time.time() < self.lease_until
            try:
                state = self.ipc('heartbeat', granted=desired)
                if not isinstance(state, dict) or type(state.get('granted')) is not bool:
                    raise ValueError('Invalid heartbeat acknowledgement')
                result = (generation, state, None)
            except Exception as exc:
                result = (generation, None, type(exc).__name__)
        try:
            self._heartbeat_results.put_nowait(result)
        except queue.Full:
            try:
                self._heartbeat_results.get_nowait()
            except queue.Empty:
                pass
            self._heartbeat_results.put_nowait(result)
        self.user32.PostMessageW(self.hwnd, WM_HEARTBEAT_RESULT, 0, 0)

    def _receive_heartbeat(self):
        with self._state_lock:
            while True:
                try:
                    generation, state, error = self._heartbeat_results.get_nowait()
                except queue.Empty:
                    return
                if generation != self._state_generation:
                    continue
                if error:
                    self.granted = False
                    self.state_unknown = True
                else:
                    auth = (state or {}).get('authorization') or {}
                    self.granted = bool(state.get('granted') and
                                        auth.get('agent_session') == self.authorization.get('agent_session'))
                    self.state_unknown = False
                    if not self.granted:
                        self.authorization = {}
                        self.lease_until = 0.0
                self._refresh_tray()

    def _menu(self):
        """Tray click opens the same window: grant, or the live lease actions."""
        self.show()

    # -- lifecycle --------------------------------------------------------
    def run(self) -> int:
        self.kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel32.CreateMutexW.restype = wintypes.HANDLE
        self.kernel32.CreateMutexW(None, True, MUTEX_NAME)
        # ctypes.get_last_error(), not kernel32.GetLastError(): the latter is a
        # fresh call whose value is already clobbered by the marshalling.
        if ctypes.get_last_error() == 183:                # ERROR_ALREADY_EXISTS
            existing = self.user32.FindWindowW(CLASS_NAME, None)
            if existing:
                self.user32.PostMessageW(existing, WM_SHOW, 0, 0)
            return 0
        class_ = WNDCLASSW(lpfnWndProc=self._wndproc, hInstance=None,
                           lpszClassName=CLASS_NAME)
        self.user32.RegisterClassW(ctypes.byref(class_))
        self.hwnd = self.user32.CreateWindowExW(0, CLASS_NAME, 'Icon Control', 0,
                                                0, 0, 0, 0, None, None, None, None)
        if not self.hwnd:
            return 3
        for name, modifiers, vk in HOTKEYS:
            if self.user32.RegisterHotKey(self.hwnd, 1, modifiers, vk):
                self.hotkey = name
                break
        self.tray = native_tray.add(self.hwnd, 1, WM_TRAY, self._tip())
        import threading
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()
        self._write_status()
        self.show()
        message = MSG()
        while self.user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            self.user32.TranslateMessage(ctypes.byref(message))
            self.user32.DispatchMessageW(ctypes.byref(message))
        self._stopping = True
        self.revoke()
        if self.tray:
            native_tray.remove(self.hwnd, 1)
        self.user32.UnregisterHotKey(self.hwnd, 1)
        return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    nonce = None
    if '--broker-session' in argv:
        index = argv.index('--broker-session')
        nonce = argv[index + 1] if index + 1 < len(argv) else None
    if not nonce:
        permission._ensure_bridge()
        consent_ipc.request('open')
        return 0
    if not native_dialog.available():
        return 4
    return ConsentHost(nonce).run()


if __name__ == '__main__':
    raise SystemExit(main())
