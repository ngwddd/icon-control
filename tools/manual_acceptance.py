"""Real product input against one dedicated fixture; never provisions or grants authority."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import time
import ctypes

parser=argparse.ArgumentParser()
parser.add_argument('case',choices=['blocked','baseline','drag','revoke'])
parser.add_argument('--state',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--wait-grant',type=float,default=0)
args=parser.parse_args()
from computer_mcp import __version__,permission,control,execution,ui_ext,live
from computer_mcp import agent_session
import subprocess
source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=Path(__file__).resolve().parents[1],text=True).strip()
agent_session.register('Icon Control dedicated desktop acceptance')
from computer_mcp.input_guard import MouseController,Button
import win32gui

def state():
    for _ in range(20):
        try:return json.loads(args.state.read_text(encoding='utf-8-sig'))
        except (OSError,ValueError):time.sleep(.05)
    raise RuntimeError('Fixture did not provide state')

def stage(text):
    args.state.with_suffix(args.state.suffix+'.command').write_text(text,encoding='utf-8')
    print(text,flush=True)

windows=[]
win32gui.EnumWindows(lambda hwnd,_:windows.append(hwnd) if win32gui.GetWindowText(hwnd)=='Icon Control rc2 acceptance' else None,None)
if len(windows)!=1:raise RuntimeError('Exactly one rc2 fixture window is required')
hwnd=windows[0]
mouse=MouseController()
report=dict(case=args.case,version=__version__,source_commit=source_commit,kind='real_desktop',simulated=False,
            started=time.time(),dpi=state().get('dpi'),results=[])
report['monitor_dpi']=ctypes.windll.user32.GetDpiForWindow(win32gui.FindWindow('Shell_TrayWnd',None))
case_started=time.perf_counter()

def record(case,passed,**evidence):
    global case_started
    finished=time.perf_counter()
    report['results'].append(dict(id=case,status='passed' if passed else 'failed',
                                 elapsed_ms=round((finished-case_started)*1000,3),evidence=evidence))
    case_started=finished

def ready():
    if not permission.status().get('granted'):
        raise RuntimeError('User must explicitly authorize the installed candidate first')
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        if control.claim('rc2 fixture acceptance').get('ok'):
            from computer_mcp import appkit
            result=appkit.activate(hwnd)
            if not result.get('ok'):raise RuntimeError('Fixture could not be activated')
            return
        time.sleep(.2)
    raise RuntimeError('User owns input or listener startup failed; no input sent')

def click(name,index=0):
    result=ui_ext.ui_click(name=name,hwnd=hwnd,index=index,mouse=mouse,exact=True)
    if not result.get('success',result.get('ok',False)):raise RuntimeError(str(result))
    time.sleep(.2)
    return result

try:
    if args.case!='blocked' and args.wait_grant:
        stage('Waiting for human authorization and two live heartbeats; no input yet')
        deadline=time.monotonic()+args.wait_grant;stable=None
        while time.monotonic()<deadline:
            if permission.status().get('granted'):
                stable=stable or time.monotonic()
                if time.monotonic()-stable>=8:break
            else:stable=None
            time.sleep(.25)
        else:raise RuntimeError('Authorization/heartbeat did not become stable')
    if args.case=='blocked':
        if permission.status().get('granted'):raise RuntimeError('Please revoke authorization before B01')
        before=state()['counts'].copy();blocked=False
        try:click('Counter')
        except permission.PermissionDenied:blocked=True
        record('B01',blocked and state()['counts']==before,before=before,after=state()['counts'],blocked=blocked)
    else:
        if args.case!='drag':ready()
        if args.case=='baseline':
            before=state()['counts'].copy()
            click('Counter')
            after=state()['counts']
            record('B02',after['Counter']==before['Counter']+1 and control.status()['takeovers']==0,
                   before=before,after=after,takeovers=control.status()['takeovers'])
            for index,key in [(0,'Confirm1'),(1,'Confirm2')]:
                before=state()['counts'].copy();click('Confirm',index);after=state()['counts']
                other='Confirm2' if index==0 else 'Confirm1'
                record('B15' if index==0 else 'B16',after[key]==before[key]+1 and after[other]==before[other],before=before,after=after)
            tree=ui_ext.ui_tree(hwnd=hwnd)
            nodes=tree.get('nodes',[])
            candidates=[n for n in nodes if n.get('name')=='Counter' and n.get('ref')]
            if not candidates:raise RuntimeError('Counter snapshot ref unavailable')
            before=state()['counts']['Counter']
            ui_ext.ui_click(name='',hwnd=hwnd,ref=candidates[0]['ref'],mouse=mouse)
            time.sleep(.2)
            record('B17',state()['counts']['Counter']==before+1,before=before,after=state()['counts']['Counter'])
            click('Input')
            from computer_mcp.actions.keyboard import type_text
            from computer_mcp import ui_ext as ui
            target='S5-B11 hello 123'
            cleared=ui.ui_set_text(name='Input',text='',hwnd=hwnd,exact=True)
            if not cleared.get('ok'):raise RuntimeError(str(cleared))
            click('Input')
            type_text(target)
            time.sleep(.3)
            record('B11',state()['text']==target,target=target,actual=state()['text'])
            click('Scroll');before=state()['scroll']
            result=live.tool_run_script({'ops':[{'op':'scroll','dy':-5},{'op':'sleep','ms':300}]})
            after=state()['scroll']
            record('B14',after>before,before=before,after=after,execution=result['status'])
            dpi=report['monitor_dpi']
            if dpi in (96,144,192):
                case={96:'B23',144:'B24',192:'B25'}[dpi]
                before=state()['counts']['Counter'];click('Counter')
                record(case,state()['counts']['Counter']==before+1,dpi=dpi,before=before,after=state()['counts']['Counter'])
        elif args.case=='drag':
            tree=ui_ext.ui_tree(hwnd=hwnd,max_nodes=200)
            nodes=tree.get('nodes',[])
            pad=next(n for n in nodes if n.get('name')=='Drag')
            x,y,w,h=(pad[k] for k in ('x','y','w','h'))
            controller=MouseController();moves=0;stopped=False;drag_seen=False
            if ctypes.windll.user32.GetAsyncKeyState(1)&0x8000:
                stage('请先松开鼠标左键；助手会自己按住鼠标拖拽')
                deadline=time.monotonic()+10
                while ctypes.windll.user32.GetAsyncKeyState(1)&0x8000 and time.monotonic()<deadline:time.sleep(.05)
                if ctypes.windll.user32.GetAsyncKeyState(1)&0x8000:raise RuntimeError('Physical left mouse button is still held')
            stage('B05：倒计时 12 秒。请等待“正在自动拖拽”提示，不要按鼠标键。')
            time.sleep(12)
            ready()
            started=time.monotonic()
            try:
                with execution.operation('drag'):
                    controller.position=(x+w//3,y+h//2)
                    controller.press(Button.left)
                    execution.sleep(.2)
                    drag_seen=state()['dragging']
                    stage('正在自动拖拽：现在请持续移动鼠标超过 1 秒，不要点击或按键。')
                    for index in range(800):
                        controller.position=(x+w//3+(index%40),y+h//2)
                        moves+=1;execution.sleep(.03)
            except permission.PermissionDenied:stopped=True
            finally:controller.cleanup()
            time.sleep(.3)
            held=bool(ctypes.windll.user32.GetAsyncKeyState(1)&0x8000)
            confirmed_motion='sustained for 1 second' in control.status()['reason']
            record('B05',stopped and drag_seen and moves>0 and confirmed_motion and control.status()['takeovers']>0 and not held and not state()['dragging'],
                   stopped=stopped,drag_seen=drag_seen,moves=moves,elapsed_s=round(time.monotonic()-started,3),
                   control=control.status(),mouse_button_held=held,fixture=state())
        elif args.case=='revoke':
            click('Input')
            from computer_mcp.actions.keyboard import type_text
            stage('B04: revoke authorization in the candidate UI while typing runs')
            stopped=False;chunks=0
            try:
                with execution.operation('run_script'):
                    for _ in range(400):
                        type_text(' S5');chunks+=1;execution.sleep(.05)
            except permission.PermissionDenied:stopped=True
            deadline=time.monotonic()+30
            while permission.status().get('granted') and time.monotonic()<deadline:time.sleep(.2)
            before=state()['text'];time.sleep(2);after=state()['text']
            granted=permission.status().get('granted')
            record('B04',stopped and not granted and before==after,stopped=stopped,granted=granted,
                   chunks=chunks,len_at_stop=len(before),len_after_2s=len(after))
except Exception as exc:
    report['error']=f'{type(exc).__name__}: {exc}'
finally:
    report['finished']=time.time()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True),flush=True)
raise SystemExit(0 if not report.get('error') and report['results'] and all(r['status']=='passed' for r in report['results']) else 1)
