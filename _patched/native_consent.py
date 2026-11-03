"""Single-window consent host: tray icon, global hotkey, native approval dialog.

The host is a long-lived background process. It owns the approval window, keeps
the lease alive with heartbeats, and can be woken from the tray or a hotkey.
"""
from __future__ import annotations

import ctypes
import os
import sys
import time
from ctypes import wintypes

from computer_mcp import agent_session, capabilities, consent_ipc, native_dialog, native_tray, permission

WM_APP = 0x8000
WM_TRAY = WM_APP + 1
WM_SHOW = WM_APP + 2
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


class ConsentHost:
    def __init__(self, nonce: str):
        self.nonce = nonce
        self.user32 = ctypes.WinDLL('user32', use_last_error=True)
        self.kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        self.hwnd = 0
        self.tray = False
        self.granted = False
        self.lease_until = 0.0
        self.authorization: dict = {}
        self.hotkey = ''
        self._wndproc = WNDPROC(self._on_message)

    # -- plumbing ---------------------------------------------------------
    def ipc(self, command, **fields):
        return consent_ipc.request(command, ui_nonce=self.nonce, **fields)

    def _tip(self) -> str:
        if not self.granted:
            return f'Icon Control · 未授权 · {self.hotkey or "热键"} 打开'
        left = max(0, int(self.lease_until - time.time()))
        return f'Icon Control · 已授权 · 剩 {left // 60}:{left % 60:02d}'

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
                                            granted=self.granted,
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
            for hwnd in candidates:
                title = win32gui.GetWindowText(hwnd)
                if not title or title.startswith('Icon Control'):
                    continue
                if not win32gui.IsWindowVisible(hwnd):
                    continue
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if not pid or pid == os.getpid():
                    continue
                record = capabilities.process_record(pid)
                record['title'] = title[:80]
                return record
        except Exception:
            pass
        return None

    def _pick_agent(self, pending=None):
        live = [a for a in agent_session.active() if a.get('pid') != os.getpid()]
        if not live:
            return None
        preferred = next((a for a in live if a.get('id') == pending), None)
        return preferred or max(live, key=lambda a: a.get('created', 0))

    def show(self):
        if self.granted:
            left = max(0, int(self.lease_until - time.time()))
            answer = native_dialog.ask_status(
                'Icon Control 已授权',
                f'Agent：{(self.authorization.get("agent_session") or "")[:10]}\r\n'
                f'范围：{", ".join(self.authorization.get("scopes") or [])}',
                remaining=f'剩余 {left // 60} 分 {left % 60} 秒')
            if answer is None:
                return
            if answer['action'] == 'revoke':
                self.revoke()
            elif answer['action'] == 'renew':
                self._renew()
            elif answer['action'] == 'quit':
                self.revoke()
                self.user32.DestroyWindow(self.hwnd)
            return

        pending = None
        pending_app = None
        try:
            status = self.ipc('status') or {}
            pending = status.get('pending')
            pending_app = status.get('pending_app')
        except Exception:
            pass
        agent = self._pick_agent(pending)
        if agent is None:
            native_dialog.ask_notice('没有活跃的 Agent 会话',
                                     '先在宿主里发起一次操作，再按热键或点托盘打开授权窗口。')
            return
        app = None
        if pending_app:
            try:
                if capabilities.process_record(pending_app['pid']) == pending_app:
                    app = dict(pending_app)
            except Exception:
                app = None
        if app is None:
            app = self._foreground_app()
        if app is None:
            native_dialog.ask_notice('找不到前台应用',
                                     '先把要操作的应用切到前台，再按热键或点托盘打开授权窗口。')
            return
        answer = native_dialog.ask_grant(
            agent_label=f"{agent.get('label', 'Agent')} · {agent['id'][:10]}",
            target_text=f"{os.path.basename(app['exe'])} · PID {app['pid']}",
            lease_minutes=LEASE_MINUTES, note=app.get('title', ''))
        if answer is None or not answer['accepted']:
            return
        self._apply(agent['id'], answer['scopes'], app, answer['lease_minutes'])

    def _apply(self, agent_session_id, scopes, app, lease_minutes):
        try:
            result = self.ipc('grant', agent_session=agent_session_id, scopes=list(scopes),
                              applications=[{k: app[k] for k in ('pid', 'created', 'exe')}],
                              launches=[], read_files=[], lease_minutes=lease_minutes)
        except Exception as exc:
            native_dialog.ask_grant('授权失败', str(exc)[:300])
            return
        if result.get('granted') is not True:
            native_dialog.ask_grant('后端未确认授权', str(result)[:300])
            return
        auth = result.get('authorization') or {}
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

    def revoke(self):
        try:
            self.ipc('revoke')
        finally:
            self.granted = False
            self.authorization = {}
            self.lease_until = 0.0
            self._refresh_tray()

    # -- message handling -------------------------------------------------
    def _on_message(self, hwnd, message, wparam, lparam):
        if message == WM_SHOW:
            self.show()
            return 0
        if message == WM_HOTKEY:
            self.show()
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

    def _heartbeat(self):
        if not self.granted:
            return
        if time.time() >= self.lease_until:
            self.granted = False
            self.authorization = {}
            self._refresh_tray()
            if self.tray:
                native_tray.balloon(self.hwnd, 1, 'Icon Control', '授权已到期', warning=True)
            return
        try:
            state = self.ipc('heartbeat', granted=True)
        except Exception:
            return
        if not (state or {}).get('granted'):
            self.granted = False
            self.authorization = {}
            self._refresh_tray()
            return
        self._refresh_tray()

    def _menu(self):
        """Tray click opens the same window: grant, or the live lease actions."""
        self.show()

    # -- lifecycle --------------------------------------------------------
    def run(self) -> int:
        handle = self.kernel32.CreateMutexW(None, True, MUTEX_NAME)
        if self.kernel32.GetLastError() == 183:          # ERROR_ALREADY_EXISTS
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
        self.user32.SetTimer(self.hwnd, WM_TIMER_HEARTBEAT, TIMER_MS, None)
        self._write_status()
        self.show()
        message = MSG()
        while self.user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            self.user32.TranslateMessage(ctypes.byref(message))
            self.user32.DispatchMessageW(ctypes.byref(message))
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
