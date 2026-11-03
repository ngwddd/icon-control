"""S5 desktop acceptance batch runner against the dedicated rc2 fixture.

Every desktop action still goes through the product's own permission gates; this
tool only orchestrates the published cases and writes one evidence file per case
in the shape `tools/release_gate.py` expects.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

parser = argparse.ArgumentParser()
parser.add_argument('--state', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--cases', default='all')
parser.add_argument('--wait-grant', type=float, default=240)
args = parser.parse_args()

os.environ.update(PYTHONIOENCODING='utf-8', DSH_E2E='1', ICON_CONTROL_E2E_STATE=str(args.state))
import computer_mcp  # noqa: E402
from computer_mcp import agent_session, appkit, control, execution, live, permission, ui_ext  # noqa: E402
from computer_mcp.actions import keyboard, window  # noqa: E402
import win32gui  # noqa: E402

SOURCE_COMMIT = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
SOURCE_DIRTY = bool(subprocess.check_output(
    ['git', 'status', '--porcelain', '--untracked-files=all', '--',
     '_patched', 'plugin', 'tools', 'tests', '.github', 'pyproject.toml', 'VERSION', 'MANIFEST.in',
     'panic_watch.py', 'constraints-windows-py312.txt', 'macros', 'recipes', 'programs'],
    cwd=ROOT, text=True).strip())
SESSION = agent_session.register('Icon Control S5 batch acceptance')
args.output.mkdir(parents=True, exist_ok=True)
mouse = computer_mcp._default_mouse_controller

CASES = {}


def case(name):
    def register(function):
        CASES[name] = function
        return function
    return register


def fixture_state():
    for _ in range(40):
        try:
            if time.time() - args.state.stat().st_mtime > 5:
                raise RuntimeError('Fixture state is stale')
            return json.loads(args.state.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            time.sleep(0.05)
    raise RuntimeError('Fixture state could not be read')


def fixture_hwnd():
    found = []
    win32gui.EnumWindows(
        lambda hwnd, _: found.append(hwnd) if win32gui.GetWindowText(hwnd) == 'Icon Control rc2 acceptance' else None,
        None)
    if len(found) != 1:
        raise RuntimeError('Exactly one dedicated fixture is required')
    return found[0]


def stage(message):
    args.state.with_suffix(args.state.suffix + '.command').write_text(
        json.dumps(dict(message=message, sequence=time.time_ns()), ensure_ascii=False), encoding='utf-8')


def environment():
    return dict(os=platform.platform(), version=computer_mcp.__version__,
                monitor_dpi=ctypes.windll.user32.GetDpiForWindow(win32gui.FindWindow('Shell_TrayWnd', None)),
                fixture_window_dpi=ctypes.windll.user32.GetDpiForWindow(fixture_hwnd()))


def wait_ready(timeout=15):
    if not permission.status().get('granted'):
        raise permission.PermissionDenied('Human approval required for this session')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if control.claim('S5 batch acceptance').get('ok'):
            break
        time.sleep(0.2)
    if control.status()['owner'] != 'ai':
        raise RuntimeError('User owns control; no input sent')
    if not appkit.activate(fixture_hwnd()).get('ok'):
        raise RuntimeError('Fixture activation failed')


def click(name, index=0):
    result = ui_ext.ui_click(name=name, hwnd=fixture_hwnd(), index=index, mouse=mouse, exact=True)
    if not result.get('success', result.get('ok', False)):
        raise RuntimeError(str(result))
    time.sleep(0.2)


def record(name, passed, **extra):
    payload = dict(kind='real_desktop', simulated=False, source_commit=SOURCE_COMMIT,
                   source_dirty=SOURCE_DIRTY, case_id=name,
                   status='passed' if passed else 'failed', timestamp=time.time(),
                   elapsed_ms=float(extra.pop('elapsed_ms', 0.0)),
                   environment=environment(),
                   application_state=extra.pop('application_state', {}),
                   result=extra.pop('result', {}), extra=extra)
    path = args.output / f'{name}.json'
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(case=name, status=payload['status'], evidence=str(path)), ensure_ascii=False), flush=True)
    return payload['status'] == 'passed'


def clear_input():
    ui_ext.ui_set_text(name='Input', text='', hwnd=fixture_hwnd(), exact=True)
    click('Input')


def combo(letter):
    keyboard.key_down('ctrl')
    try:
        keyboard.key_press(letter)
    finally:
        keyboard.key_up('ctrl')
    time.sleep(0.1)


_state = [None]


def tool(name, arguments):
    """Call a product tool through the real dispatch gate (permission included)."""
    from computer_mcp.zones import dispatch as zone_dispatch
    if _state[0] is None:
        _state[0] = zone_dispatch.ComputerState()
    return zone_dispatch.dispatch(name, arguments, computer_state=_state[0],
                                  mouse_controller=mouse,
                                  keyboard_controller=computer_mcp._default_keyboard_controller)


def canvas_probe_rect(hwnd=None):
    """The fixture's painted probe strip, in screen coordinates."""
    hwnd = hwnd or fixture_hwnd()
    left, top = win32gui.ClientToScreen(hwnd, (int(20 + 720 * 0.86), int(540 + 58 * 0.15)))
    return dict(x=left, y=top, w=int(58 * 0.7), h=int(58 * 0.7))



@case('B01')
def b01_blocked():
    """Unauthorised click must not change the application."""
    if permission.status().get('granted'):
        raise RuntimeError('Revoke authorization before B01')
    before = fixture_state()['counts']
    blocked = False
    try:
        click('Counter')
    except permission.PermissionDenied:
        blocked = True
    after = fixture_state()['counts']
    return blocked and after == before, dict(application_state=dict(before=before, after=after),
                                             result=dict(blocked=blocked))


@case('B02')
def b02_authorized_click():
    wait_ready()
    before = fixture_state()['counts']
    click('Counter')
    after = fixture_state()['counts']
    return (after['Counter'] == before['Counter'] + 1 and control.status()['takeovers'] == 0,
            dict(application_state=dict(before=before, after=after),
                 result=dict(takeovers=control.status()['takeovers'])))


@case('B11')
def b11_short_text():
    wait_ready()
    target = 'S5-B11 hello 123'
    clear_input()
    keyboard.type_text(target)
    time.sleep(0.3)
    actual = fixture_state()['text']
    return actual == target, dict(application_state=dict(target=target, actual=actual))


@case('B12')
def b12_long_text():
    wait_ready()
    target = 'S5-B12 中文与符号：你好，世界！123 [] {} @#$% ✓ 长文本重复' * 2
    clear_input()
    keyboard.type_text(target)
    time.sleep(0.5)
    actual = fixture_state()['text']
    return actual == target, dict(application_state=dict(target=target, actual=actual))


@case('B13')
def b13_copy_paste():
    import win32clipboard
    wait_ready()
    target = 'S5-B13 复制粘贴 roundtrip ✓'
    clear_input()
    keyboard.type_text(target)
    time.sleep(0.3)
    combo('a')
    combo('c')
    time.sleep(0.4)
    win32clipboard.OpenClipboard()
    try:
        copied = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()
    clear_input()
    combo('v')
    time.sleep(0.4)
    pasted = fixture_state()['text']
    return copied == target and pasted == target, dict(
        application_state=dict(target=target, copied=copied, pasted=pasted))


@case('B14')
def b14_scroll():
    wait_ready()
    click('Scroll')
    before = fixture_state()['scroll']
    result = live.tool_run_script({'ops': [{'op': 'scroll', 'dy': -5}, {'op': 'sleep', 'ms': 300}]})
    after = fixture_state()['scroll']
    return after > before, dict(application_state=dict(before=before, after=after),
                                result=dict(status=result.get('status')))


@case('B15')
def b15_uia_first_button():
    wait_ready()
    before = fixture_state()['counts']
    click('Confirm', 0)
    after = fixture_state()['counts']
    return (after['Confirm1'] == before['Confirm1'] + 1 and after['Confirm2'] == before['Confirm2'],
            dict(application_state=dict(before=before, after=after)))


@case('B16')
def b16_uia_second_button():
    wait_ready()
    before = fixture_state()['counts']
    click('Confirm', 1)
    after = fixture_state()['counts']
    return (after['Confirm2'] == before['Confirm2'] + 1 and after['Confirm1'] == before['Confirm1'],
            dict(application_state=dict(before=before, after=after)))


@case('B17')
def b17_snapshot_ref():
    wait_ready()
    tree = ui_ext.ui_tree(hwnd=fixture_hwnd())
    nodes = tree.get('nodes', [])
    candidate = next((n for n in nodes if n.get('name') == 'Counter' and n.get('ref')), None)
    if not candidate:
        raise RuntimeError('Counter snapshot ref unavailable')
    before = fixture_state()['counts']['Counter']
    ui_ext.ui_click(name='', hwnd=fixture_hwnd(), ref=candidate['ref'], mouse=mouse)
    time.sleep(0.2)
    after = fixture_state()['counts']['Counter']
    return after == before + 1, dict(application_state=dict(before=before, after=after))


@case('B18')
def b18_stale_ref():
    wait_ready()
    tree = ui_ext.ui_tree(hwnd=fixture_hwnd())
    candidate = next((n for n in tree.get('nodes', []) if n.get('name') == 'Counter' and n.get('ref')), None)
    if not candidate:
        raise RuntimeError('Counter snapshot ref unavailable')
    stage('S5-B18 recreate the window handle before the stale click')
    time.sleep(0.6)
    args.state.with_suffix(args.state.suffix + '.command').write_text(
        json.dumps(dict(message='S5-B18', action='recreate', sequence=time.time_ns())), encoding='utf-8')
    time.sleep(1.2)
    before = fixture_state()['counts']['Counter']
    refused = False
    try:
        result = ui_ext.ui_click(name='', hwnd=fixture_hwnd(), ref=candidate['ref'], mouse=mouse)
        refused = not result.get('success', result.get('ok', False))
    except Exception:
        refused = True
    time.sleep(0.2)
    after = fixture_state()['counts']['Counter']
    return refused and after == before, dict(application_state=dict(before=before, after=after),
                                             result=dict(refused=refused))


@case('B19')
def b19_moved_window():
    wait_ready()
    tree = ui_ext.ui_tree(hwnd=fixture_hwnd())
    candidate = next((n for n in tree.get('nodes', []) if n.get('name') == 'Counter' and n.get('ref')), None)
    if not candidate:
        raise RuntimeError('Counter snapshot ref unavailable')
    hwnd = fixture_hwnd()
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    win32gui.SetWindowPos(hwnd, 0, left + 40, top + 20, right - left, bottom - top, 0x0004)
    time.sleep(0.6)
    before = fixture_state()['counts']['Counter']
    refused = False
    try:
        result = ui_ext.ui_click(name='', hwnd=hwnd, ref=candidate['ref'], mouse=mouse)
        refused = not result.get('success', result.get('ok', False))
    except Exception:
        refused = True
    time.sleep(0.2)
    after = fixture_state()['counts']['Counter']
    win32gui.SetWindowPos(hwnd, 0, left, top, right - left, bottom - top, 0x0004)
    return refused and after == before, dict(application_state=dict(before=before, after=after,
                                                                    moved_to=[left + 40, top + 20]),
                                             result=dict(refused=refused))


@case('B24')
def b24_dpi():
    wait_ready()
    dpi = environment()['fixture_window_dpi']
    if dpi != 144:
        raise RuntimeError(f'This case requires a 150% monitor, current fixture DPI is {dpi}')
    before = fixture_state()['counts']['Counter']
    click('Counter')
    after = fixture_state()['counts']['Counter']
    return after == before + 1, dict(application_state=dict(before=before, after=after, dpi=dpi))


@case('B29')
def b29_photo():
    import base64
    from io import BytesIO
    from computer_mcp.core.screenshot import capture_screenshot
    from PIL import Image
    wait_ready()
    hwnd = fixture_hwnd()
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    shot = capture_screenshot(dict(x=left, y=top, w=right - left, h=bottom - top))
    encoded = shot.get('data') or shot.get('image') or shot.get('base64')
    if not isinstance(encoded, str):
        raise RuntimeError('Screenshot did not return image data')
    target = args.output / 'B29-capture.png'
    raw = base64.b64decode(encoded)
    target.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    with Image.open(BytesIO(raw)) as image:
        width, height = image.size
        uniform = all(low == high for low, high in image.convert('RGB').getextrema())
    return width > 0 and height > 0 and not uniform, dict(
        application_state=dict(region=[left, top, right, bottom], width=width, height=height),
        result=dict(sha256=digest, path=str(target), encoded_bytes=len(raw)))


@case('B30')
def b30_no_false_success():
    """A request that cannot be carried out must not report success."""
    wait_ready()
    before = fixture_state()['counts']
    try:
        result = ui_ext.ui_click(name='S5-B30-NO-SUCH-CONTROL', hwnd=fixture_hwnd(), mouse=mouse)
    except Exception as exc:  # noqa: BLE001 - a refusal is the expected outcome
        result = dict(error=f'{type(exc).__name__}: {exc}')
    after = fixture_state()['counts']
    claimed_ok = bool(result.get('success', result.get('ok', False)))
    return (not claimed_ok and after == before,
            dict(application_state=dict(before=before, after=after),
                 result=dict(claimed_ok=claimed_ok, status=result.get('status'),
                             error=str(result.get('error'))[:200])))


@case('B20')
def b20_recreated_handle():
    """A stale reference must not click the recreated window."""
    wait_ready()
    old = fixture_hwnd()
    tree = ui_ext.ui_tree(hwnd=old)
    candidate = next((n for n in tree.get('nodes', []) if n.get('name') == 'Counter' and n.get('ref')), None)
    if not candidate:
        raise RuntimeError('Counter snapshot ref unavailable')
    args.state.with_suffix(args.state.suffix + '.command').write_text(
        json.dumps(dict(message='S5-B20 recreate', action='recreate', sequence=time.time_ns())), encoding='utf-8')
    time.sleep(1.2)
    new = fixture_hwnd()
    before = fixture_state()['counts']['Counter']
    refused = False
    try:
        result = ui_ext.ui_click(name='', hwnd=new, ref=candidate['ref'], mouse=mouse)
        refused = not result.get('success', result.get('ok', False))
    except Exception:
        refused = True
    time.sleep(0.2)
    after = fixture_state()['counts']['Counter']
    return (new != old and refused and after == before,
            dict(application_state=dict(before=before, after=after, old_hwnd=old, new_hwnd=new),
                 result=dict(refused=refused)))


@case('B21')
def b21_content_changed():
    """Content changed but the window sits still: the old reference must die."""
    wait_ready()
    hwnd = fixture_hwnd()
    tree = ui_ext.ui_tree(hwnd=hwnd)
    candidate = next((n for n in tree.get('nodes', []) if n.get('name') == 'Counter' and n.get('ref')), None)
    if not candidate:
        raise RuntimeError('Counter snapshot ref unavailable')
    clear_input()
    keyboard.type_text('S5-B21 content changed')
    time.sleep(0.4)
    before = fixture_state()['counts']['Counter']
    refused = False
    try:
        result = ui_ext.ui_click(name='', hwnd=hwnd, ref=candidate['ref'], mouse=mouse)
        refused = not result.get('success', result.get('ok', False))
    except Exception:
        refused = True
    time.sleep(0.2)
    after = fixture_state()['counts']['Counter']
    return (refused and after == before,
            dict(application_state=dict(before=before, after=after),
                 result=dict(refused=refused)))


@case('B26')
def b26_ocr_text():
    """OCR locates the painted label; the application state proves the click."""
    wait_ready()
    hwnd = fixture_hwnd()
    before = fixture_state()['counts']['OcrTarget']
    result = tool('click_text', {'query': 'CANITY TEST TARGET', 'hwnd': hwnd})
    time.sleep(0.4)
    after = fixture_state()['counts']['OcrTarget']
    ok = bool(result.get('ok', result.get('success', False)))
    return (ok and after == before + 1,
            dict(application_state=dict(before=before, after=after),
                 result=dict(ok=ok, response=str(result)[:300])))


@case('B28')
def b28_branch():
    """Both sides of a visual branch must actually run."""
    wait_ready()
    rect = canvas_probe_rect()
    box = [rect['x'], rect['y'], rect['w'], rect['h']]
    click('Scroll')
    before = fixture_state()['scroll']
    live.tool_run_script({'ops': [
        {'op': 'if', 'cond': {'kind': 'color', 'box': box, 'color': 'green', 'tol': 90},
         'then': [{'op': 'scroll', 'dy': -3}], 'else': [{'op': 'scroll', 'dy': 3}]}]})
    after_true = fixture_state()['scroll']
    live.tool_run_script({'ops': [
        {'op': 'if', 'cond': {'kind': 'color', 'box': box, 'color': 'red', 'tol': 20},
         'then': [{'op': 'scroll', 'dy': -3}], 'else': [{'op': 'scroll', 'dy': 3}]}]})
    after_false = fixture_state()['scroll']
    return (after_true > before and after_false < after_true,
            dict(application_state=dict(scroll_before=before, scroll_true=after_true,
                                        scroll_false=after_false)))


def main():
    requested = [name.strip().upper() for name in args.cases.split(',')] if args.cases != 'all' else list(CASES)
    unknown = [name for name in requested if name not in CASES]
    if unknown:
        raise SystemExit('Unknown cases: ' + ', '.join(unknown))
    print(json.dumps(dict(source_commit=SOURCE_COMMIT, source_dirty=SOURCE_DIRTY,
                          session=SESSION['id'][:10], cases=requested,
                          granted=permission.status().get('granted'))), flush=True)
    if 'B01' not in requested and not permission.status().get('granted') and args.wait_grant:
        print('Waiting for human authorization; no input sent yet', flush=True)
        deadline = time.monotonic() + args.wait_grant
        while time.monotonic() < deadline and not permission.status().get('granted'):
            time.sleep(0.3)
        if not permission.status().get('granted'):
            raise SystemExit('Authorization not received')
        time.sleep(12)
    results = {}
    for name in requested:
        started = time.perf_counter()
        try:
            passed, evidence = CASES[name]()
        except Exception as exc:  # noqa: BLE001
            passed, evidence = False, dict(application_state={},
                                           result=dict(error=f'{type(exc).__name__}: {exc}'))
        evidence['elapsed_ms'] = round((time.perf_counter() - started) * 1000, 3)
        results[name] = record(name, passed, **evidence)
    print(json.dumps(dict(passed=sum(results.values()), total=len(results)), ensure_ascii=False), flush=True)
    return 0 if all(results.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
