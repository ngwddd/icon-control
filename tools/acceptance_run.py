"""One command for the S5 acceptance: preflight, run, classify, report.

The point is drift control. Before a single case runs, every precondition that
has silently broken a run before (fixture minimised, stop latch left over, two
consent hosts, stale windows, expired approval) is checked and, where it is
safe, healed. Anything that cannot be healed stops the run with a checklist
instead of producing seven meaningless failures.

    python tools/acceptance_run.py --cases B11,B12,B20,B21,B22,B26,B28
    python tools/acceptance_run.py --cases B11,B12 --repeat 2

Exit codes: 0 all requested cases passed, 1 something failed, 2 preflight.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOME = Path(os.environ.get('ICON_CONTROL_HOME') or Path(os.environ['LOCALAPPDATA']) / 'IconControl')
EVIDENCE = ROOT / 'docs' / 'v1.3' / 'evidence' / 's5'
PORT = os.environ.get('ICON_CONTROL_BRIDGE_PORT', '18766')

HARNESS_SIGNS = ('obscured', 'not found', 'no such window', 'invalid window',
                 'window not found', 'fixture', 'not available', 'timed out')


def say(mark: str, text: str) -> None:
    print(f'[{mark}] {text}', flush=True)


def git_clean() -> bool:
    out = subprocess.check_output(
        ['git', 'status', '--porcelain', '--untracked-files=all'], cwd=ROOT, text=True)
    if out.strip():
        say('fail', '工作区不干净，证据会被标 dirty：\n' + out.strip()[:400])
        return False
    say('ok', 'git 工作区干净')
    return True


def bridge_alive() -> bool:
    import socket
    with socket.socket() as sock:
        sock.settimeout(0.5)
        if sock.connect_ex(('127.0.0.1', int(PORT))) == 0:
            say('ok', f'授权桥在 127.0.0.1:{PORT} 上监听')
            return True
    say('fail', '授权桥没在跑：python -m computer_mcp.permission_bridge')
    return False


def consent_hosts() -> list[int]:
    import psutil
    pids = []
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            cmdline = proc.info.get('cmdline') or []
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        joined = ' '.join(cmdline)
        if '-m computer_mcp.consent' in joined and 'permission_bridge' not in joined:
            # The launcher is python.exe and exits; the host is pythonw.exe.
            try:
                if proc.name().lower() != 'pythonw.exe':
                    continue
            except psutil.Error:
                continue
            pids.append(proc.info['pid'])
    owner = host_window_owner()
    if owner and owner in pids:
        # The venv pythonw re-execs the real interpreter: drop the launcher
        # ancestors so one host is not counted twice.
        import psutil as _ps
        try:
            ancestors = {parent.pid for parent in _ps.Process(owner).parents()}
            pids = [pid for pid in pids if pid not in ancestors]
        except _ps.Error:
            pass
    return sorted(pids)


def single_host() -> bool:
    pids = consent_hosts()
    if len(pids) == 1:
        say('ok', f'授权宿主唯一：pid {pids[0]}')
        return True
    if not pids:
        say('fail', '没有授权宿主：掉托盘和热键了，跑一次 python -m computer_mcp.consent')
        return False
    owner = host_window_owner()
    if owner and owner in pids:
        say('fail', f'有 {len(pids)} 个授权宿主（窗口属于 {owner}，另 {sorted(set(pids) - {owner})} 个多余）。'
                    '多余宿主会叠窗口；结束多余的那个，保留带窗口的')
    else:
        say('fail', f'有 {len(pids)} 个授权宿主 {sorted(pids)}，分不清哪个带窗口；全部结束再重开一个')
    return False


def host_window_owner() -> int | None:
    import win32gui
    import win32process
    hwnd = win32gui.FindWindow('IconControlConsentHost', None)
    if not hwnd:
        return None
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    return pid or None


def stop_latch_clear() -> bool:
    path = HOME / 'state' / 'emergency-stop.json'
    if not path.exists():
        say('ok', '没有残留的停止闩')
        return True
    say('fail', f'存在停止闩 {path}：它会静默否掉任何授权。确认不是紧急停止后删除它')
    return False


def approval() -> bool:
    env = dict(os.environ, ICON_CONTROL_HOME=str(HOME))
    code = ('from computer_mcp import permission;'
            's=permission.status();'
            'print(1 if s.get("granted") else 0)')
    out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, env=env)
    if out.stdout.strip().endswith('1'):
        say('ok', '授权有效')
        return True
    say('fail', '当前没有有效授权：按 Ctrl+Alt+Shift+F9，窗口里回车')
    return False


def fixture_windows() -> list[int]:
    import win32gui
    found = []
    win32gui.EnumWindows(
        lambda hwnd, _: found.append(hwnd)
        if win32gui.GetWindowText(hwnd) == 'Icon Control rc2 acceptance' else None, None)
    return found


def fixture_ready() -> bool:
    import win32con
    import win32gui
    windows = fixture_windows()
    if not windows:
        say('fail', '夹具没在跑：powershell -File tests/manual/fixture_app.ps1 -StatePath <state>')
        return False
    hwnd = windows[0]
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        time.sleep(0.4)
        say('healed', '夹具是收起的，已还原')
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    if right - left < 200 or bottom - top < 200:
        say('fail', f'夹具尺寸异常 {right - left}x{bottom - top}')
        return False
    if win32gui.GetForegroundWindow() != hwnd:
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        time.sleep(0.3)
    foreground = win32gui.GetForegroundWindow() == hwnd
    say('ok' if foreground else 'healed',
        f'夹具窗口 {hwnd} 在 ({left},{top}) {"前台" if foreground else "已恢复（未能置前）"}')
    return True


def stray_dialogs() -> bool:
    import win32con
    import win32gui
    closed = []
    win32gui.EnumWindows(
        lambda hwnd, _: closed.append(hwnd)
        if win32gui.GetWindowText(hwnd) == 'Icon Control'
        and win32gui.IsWindowVisible(hwnd) else None, None)
    for hwnd in closed:
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    if closed:
        time.sleep(0.5)
        say('healed', f'关掉了 {len(closed)} 个残留授权窗口')
    else:
        say('ok', '没有残留授权窗口')
    return True


def preflight() -> bool:
    checks = [git_clean, bridge_alive, single_host, stop_latch_clear, approval,
              fixture_ready, stray_dialogs]
    results = [check() for check in checks]
    return all(results)


def classify(case: dict) -> str:
    if case.get('status') == 'passed':
        return 'passed'
    blob = json.dumps(case.get('result') or {}, ensure_ascii=False).lower()
    if 'permissiondenied' in blob or 'blocked' in blob or 'refused' in blob:
        return 'product'
    if any(sign in blob for sign in HARNESS_SIGNS) or not blob or blob == '{}':
        return 'harness'
    return 'unknown'


def run_cases(cases: list[str], wait_grant: float) -> dict:
    command = [sys.executable, 'tools/desktop_acceptance.py',
               '--state', str(HOME / '.e2e-smoke' / 'fixture-s5.json'),
               '--output', str(EVIDENCE), '--cases', ','.join(cases)]
    if wait_grant:
        command += ['--wait-grant', str(wait_grant)]
    out = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                         env=dict(os.environ, ICON_CONTROL_HOME=str(HOME)))
    status = {}
    for line in out.stdout.splitlines():
        line = line.strip()
        if not line.startswith('{'):
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if 'case' in row:
            status[row['case']] = row['status']
    if not status:
        say('fail', '批次没有产出结果：\n' + (out.stderr or out.stdout)[-500:])
    return status


def evidence_for(case: str) -> dict:
    path = EVIDENCE / f'{case}.json'
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def report(cases: list[str], status: dict) -> dict:
    rows = []
    for case in cases:
        raw = evidence_for(case)
        rows.append(dict(case=case, status=raw.get('status', status.get(case, 'missing')),
                         kind=classify(raw), result=raw.get('result'),
                         application_state=raw.get('application_state')))
    passed = [row for row in rows if row['status'] == 'passed']
    harness = [row for row in rows if row['status'] != 'passed' and row['kind'] == 'harness']
    product = [row for row in rows if row['status'] != 'passed' and row['kind'] == 'product']
    print()
    print(f'{"case":6} {"status":8} {"kind":8} note')
    for row in rows:
        note = ''
        blob = row.get('result') or {}
        if isinstance(blob, dict):
            note = str(blob.get('error') or blob.get('refused') or '')[:60]
        print(f'{row["case"]:6} {row["status"]:8} {row["kind"]:8} {note}')
    print()
    print(f'合计 {len(passed)}/{len(cases)} 通过 · harness 问题 {len(harness)} · 产品拒绝 {len(product)}')
    return dict(cases=rows, passed=len(passed), total=len(cases),
                harness=[row['case'] for row in harness],
                product=[row['case'] for row in product])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--cases', required=True)
    parser.add_argument('--wait-grant', type=float, default=0)
    parser.add_argument('--repeat', type=int, default=1)
    args = parser.parse_args()
    cases = [case.strip() for case in args.cases.split(',') if case.strip()]

    print('== preflight ==')
    if not preflight():
        print('\npreflight 未通过，没有执行任何用例。')
        return 2

    runs = []
    for index in range(max(1, args.repeat)):
        print(f'\n== run {index + 1}/{args.repeat} · {",".join(cases)} ==')
        status = run_cases(cases, args.wait_grant if index == 0 else 0)
        runs.append(report(cases, status))

    summary = dict(timestamp=time.strftime('%Y-%m-%dT%H:%M:%S'), cases=cases,
                   runs=runs, repeat=args.repeat)
    if args.repeat > 1:
        drift = {}
        for case in cases:
            seen = [row['status'] for run in runs for row in run['cases'] if row['case'] == case]
            if len(set(seen)) > 1:
                drift[case] = seen
        summary['drift'] = drift
        print('\ndrift:', json.dumps(drift, ensure_ascii=False) if drift else '没有漂移')

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / 'last-run.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if runs[-1]['passed'] == len(cases) else 1


if __name__ == '__main__':
    raise SystemExit(main())
