"""Single-window consent host: one native dialog, one click, then a 60 min lease.

This replaces the two-window Tk flow on the normal path. The Tk control center
stays only as the "advanced" detail editor behind the dialog's 高级… button.
"""
from __future__ import annotations

import os
import sys
import time

from computer_mcp import agent_session, capabilities, consent_ipc, native_dialog, permission

LEASE_MINUTES = 60
HEARTBEAT_S = 4.0


def _foreground_app() -> dict | None:
    """The app the human is looking at *before* the dialog takes focus."""
    try:
        import win32gui
        import win32process
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None
        title = win32gui.GetWindowText(hwnd)
        if title.startswith('Icon Control'):
            return None
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        record = capabilities.process_record(pid)
        record['title'] = title[:80]
        return record
    except Exception:
        return None


def _pick_agent(agents):
    """Newest live session; the dialog shows exactly who gets the approval."""
    live = [a for a in agents if a.get('pid') != os.getpid()]
    if not live:
        return None
    return max(live, key=lambda a: a.get('created', 0))


def _native_loop(nonce: str) -> int:
    def ipc(command, **fields):
        return consent_ipc.request(command, ui_nonce=nonce, **fields)

    status = ipc('status')
    agent = _pick_agent(status.get('agents', []))
    if agent is None:
        print('没有活跃的 Agent 会话；先在宿主里发起一次操作再授权。', file=sys.stderr)
        return 2
    app = _foreground_app()
    if app is None:
        print('找不到前台应用；先把要操作的应用切到前台，再打开授权窗口。', file=sys.stderr)
        return 3

    answer = native_dialog.ask_grant(
        agent_label=f"{agent.get('label', 'Agent')} · {agent['id'][:10]}",
        target_text=f"{os.path.basename(app['exe'])} · PID {app['pid']}",
        default_preset=0,
        lease_minutes=LEASE_MINUTES,
        note=app.get('title', ''),
    )
    if answer is None:
        print('TaskDialogIndirect unavailable', file=sys.stderr)
        return 4
    if not answer['accepted']:
        return 0
    if answer['button'] == native_dialog.BUTTON_ADVANCED:
        from computer_mcp import consent
        return consent.main(['--broker-session', nonce])

    result = ipc('grant', agent_session=agent['id'], scopes=answer['scopes'],
                 applications=[{k: app[k] for k in ('pid', 'created', 'exe')}],
                 launches=[], read_files=[], lease_minutes=answer['lease_minutes'])
    if result.get('granted') is not True:
        print('后端未确认授权：' + str(result), file=sys.stderr)
        return 5

    deadline = time.monotonic() + (answer['lease_minutes'] or LEASE_MINUTES) * 60
    while time.monotonic() < deadline:
        time.sleep(HEARTBEAT_S)
        try:
            state = ipc('heartbeat', granted=True)
        except Exception:
            return 0
        auth = (state or {}).get('authorization') or {}
        if not (state or {}).get('granted') or not auth:
            return 0
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
    try:
        return _native_loop(nonce)
    finally:
        try:
            consent_ipc.request('heartbeat', ui_nonce=nonce, granted=False)
        except Exception:
            pass


if __name__ == '__main__':
    raise SystemExit(main())
