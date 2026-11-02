"""Persistent developer test console; every desktop action still uses product gates."""
import argparse
import code
import json
import os
from pathlib import Path
import subprocess
import sys
import time

parser=argparse.ArgumentParser()
parser.add_argument('--home',type=Path,required=True)
parser.add_argument('--state',type=Path,required=True)
parser.add_argument('--evidence',type=Path,required=True)
args=parser.parse_args()
ROOT=Path(__file__).resolve().parents[1]
SOURCE_COMMIT=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
os.environ.update(ICON_CONTROL_HOME=str(args.home),DSH_MOUSE_STATE=str(args.home/'state'/'mouse-permission.json'),
                  DSH_E2E='1',ICON_CONTROL_E2E_STATE=str(args.state),PYTHONIOENCODING='utf-8')
import computer_mcp
from computer_mcp import agent_session,permission,control,execution,ui_ext,input_guard,consent_ipc
from computer_mcp.actions import keyboard,window
import win32gui
for source in (ROOT/'_patched').rglob('*.py'):
    if '__pycache__' in source.parts:continue
    installed=Path(computer_mcp.__file__).parent/source.relative_to(ROOT/'_patched')
    if not installed.is_file() or source.read_bytes()!=installed.read_bytes():
        raise RuntimeError('Installed candidate differs from source: '+str(source.relative_to(ROOT)))
args.evidence.mkdir(parents=True,exist_ok=True)
SESSION=agent_session.register('Desktop acceptance: persistent test session')
sys.path.insert(0,str(ROOT/'tests'))
mouse=computer_mcp._default_mouse_controller
keys=computer_mcp._default_keyboard_controller

def fixture_state():
    for _ in range(20):
        try:
            if time.time()-args.state.stat().st_mtime>3:raise RuntimeError('Fixture state is stale')
            return json.loads(args.state.read_text(encoding='utf-8-sig'))
        except (OSError,ValueError):time.sleep(.05)
    raise RuntimeError('Fixture state could not be read')

def fixture_hwnd():
    candidates=[]
    win32gui.EnumWindows(lambda hwnd,_:candidates.append(hwnd) if
        win32gui.GetWindowText(hwnd)=='Icon Control rc2 acceptance' else None,None)
    if len(candidates)!=1:raise RuntimeError('Exactly one dedicated fixture is required')
    return candidates[0]

def verify_source():
    if subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()!=SOURCE_COMMIT:
        raise RuntimeError('Source revision changed; previous acceptance session cannot certify it')
    if subprocess.check_output(['git','status','--porcelain','--untracked-files=all','--',
        '_patched','plugin','tools','tests','.github','pyproject.toml','VERSION','MANIFEST.in',
        'panic_watch.py','constraints-windows-py312.txt','macros','recipes','programs'],cwd=ROOT,text=True).strip():
        raise RuntimeError('Source or test harness is dirty; commit before acceptance')

def ready():
    verify_source()
    if not permission.status().get('granted'):raise permission.PermissionDenied('Human approval required for this session')
    deadline=time.monotonic()+15
    while not control.claim('Desktop acceptance').get('ok') and time.monotonic()<deadline:time.sleep(.2)
    if control.status()['owner']!='ai':raise RuntimeError('User owns control')
    from computer_mcp import appkit
    if not appkit.activate(fixture_hwnd()).get('ok'):raise RuntimeError('Fixture activation failed')

def stage(message,action=None):
    command=dict(message=message,action=action,sequence=time.time_ns()) if action else message
    args.state.with_suffix(args.state.suffix+'.command').write_text(
        json.dumps(command,ensure_ascii=False) if isinstance(command,dict) else command,encoding='utf-8')

def save_case(case,passed,*,before=None,after=None,result=None,elapsed_ms=None,extra=None):
    verify_source()
    import ctypes,platform
    record=dict(kind='real_desktop',simulated=False,source_commit=SOURCE_COMMIT,case_id=case,source_dirty=False,
        status='passed' if passed else 'failed',timestamp=time.time(),elapsed_ms=elapsed_ms,
        environment=dict(os=platform.platform(),version=computer_mcp.__version__,
            monitor_dpi=ctypes.windll.user32.GetDpiForWindow(win32gui.FindWindow('Shell_TrayWnd',None)),
            fixture_window_dpi=ctypes.windll.user32.GetDpiForWindow(fixture_hwnd())),
        application_state=dict(before=before,after=after),result=result,extra=extra or {})
    path=args.evidence/(case+'.json')
    if path.exists():path=args.evidence/(case+'-'+str(time.time_ns())+'.json')
    path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(case=case,status=record['status'],evidence=str(path)),ensure_ascii=False),flush=True)
    return record

print(json.dumps(dict(source_commit=SOURCE_COMMIT,session=SESSION['id'][:10],
    label=SESSION['label'],fixture_pid=fixture_state().get('pid'),granted=permission.status().get('granted'))),flush=True)
try:
    code.interact(banner='Acceptance console ready. Human approval is required; no tests run automatically.',local=globals())
finally:
    input_guard.release_all()
    if permission.status().get('granted'):
        try:consent_ipc.request('emergency')
        except Exception:pass
    control.release('Acceptance console ended')
