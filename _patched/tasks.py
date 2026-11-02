"""Bounded instruction execution with explicit evidence and terminal states."""
from __future__ import annotations
import hashlib
from pathlib import Path
import re
import time
import uuid
from computer_mcp import execution, security

def photo(name, rect):
    from computer_mcp.core.screenshot import _grab
    from PIL import Image
    execution.check('snapshot')
    if not isinstance(name, str) or not re.fullmatch(r'[\w-]{1,64}', name):
        raise ValueError('photo name must contain 1-64 letters, digits, underscores or hyphens')
    image, width, height = _grab(dict(zip(('x','y','w','h'),rect)))
    if width <= 0 or height <= 0:
        raise RuntimeError('Empty capture')
    folder = security.data_home()/'artifacts'
    execution.check('snapshot'); folder.mkdir(parents=True,exist_ok=True)
    path=folder/(name+'-'+uuid.uuid4().hex+'.png')
    execution.check('snapshot'); image.save(path,format='PNG')
    with Image.open(path) as saved:
        saved.verify()
    return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                width=width,height=height)

class Task:
    def __init__(self, instructions, facts, hwnd, rect, stop_on_fail, wheel):
        self.instructions=instructions; self.facts=facts;self.hwnd=hwnd;self.rect=rect
        self.stop_on_fail=stop_on_fail;self.wheel=wheel
        self.rows=[];self.log=[];self.done=0;self.failed=[];self.artifacts=[]
        self.deadline=time.monotonic()+120;self.steps=0

    def check(self):
        execution.check('run_script')
        if self.steps>=512 or time.monotonic()>self.deadline:
            raise RuntimeError('Task budget exceeded')

    def verify(self, condition, timeout_ms, mark=None):
        from computer_mcp import train
        if not isinstance(condition,dict) or not condition.get('kind'):
            raise ValueError('A supported postcondition is required')
        end=min(self.deadline,time.monotonic()+max(0,min(30000,float(timeout_ms)))/1000)
        while True:
            self.check()
            value=train.check_expect(condition,self.wheel,self.rect,self.hwnd,mark)
            if value is True: return True
            if time.monotonic()>=end: return False
            execution.sleep(min(.12,max(0,end-time.monotonic())))

    def execute(self,instructions,depth=0):
        from computer_mcp import program, train
        if depth>16: raise ValueError('Branch nesting limit exceeded')
        if not isinstance(instructions,list): raise ValueError('Instructions must be a list')
        for instruction in instructions:
            self.check(); self.steps+=1
            row=dict(line=instruction.get('_line','?'),op=instruction.get('op'),state='running',verified=False)
            self.rows.append(row)
            try:
                params=program.expand({k:v for k,v in instruction.items() if k!='op'},self.facts)
                op=instruction.get('op');expected=params.pop('expect',None);mark=time.time()
                if op=='branch':
                    condition=params.get('if')
                    if not isinstance(condition,dict): raise ValueError('branch requires if')
                    result=train.check_expect(condition,self.wheel,self.rect,self.hwnd)
                    if type(result) is not bool: raise RuntimeError('Branch condition is unknown')
                    row['condition']=result
                    self.execute(params.get('then' if result else 'else',[]),depth+1)
                    row['verified']=True
                elif op=='photo':
                    evidence=photo(params.get('name','capture'),self.rect)
                    row['evidence']=evidence;self.artifacts.append(evidence);row['verified']=True
                elif op=='focus':
                    hit=train._find_window(str(params.get('title','')),same_pid=None)
                    if not hit: raise RuntimeError('Requested focus window does not exist')
                    hwnd,bounds=hit
                    from computer_mcp import winutil
                    import win32gui
                    if not winutil.activate(hwnd) or win32gui.GetForegroundWindow()!=hwnd:
                        raise RuntimeError('Foreground window could not be verified')
                    self.hwnd=hwnd
                    l,t,r,b=bounds;self.rect=(l,t,r-l,b-t);row['verified']=True
                elif op=='assert':
                    row['state']='verifying'
                    if not self.verify(expected,params.get('timeout_ms',3000)):
                        raise RuntimeError('Assertion failed or could not be verified')
                    row['verified']=True
                    # A final assertion can verify the resulting state of a sequence.
                    for earlier in self.rows[:-1]:
                        if earlier['state']=='executed_unverified':
                            earlier.update(verified=True,state='succeeded',verified_by=row['line'])
                else:
                    action=program._as_action(dict(params,op=op))
                    if not action: raise ValueError('Unsupported instruction: '+str(op))
                    result=train.do_action(action,self.rect,self.hwnd)
                    if not isinstance(result,dict) or result.get('ok') is not True:
                        raise RuntimeError('Action failed: '+str(result))
                    if expected:
                        row['state']='verifying'
                        if not self.verify(expected,params.get('timeout_ms',8000),mark):
                            raise RuntimeError('Postcondition failed or timed out')
                        row['verified']=True
                self.done+=1
                row['state']='succeeded' if row['verified'] else 'executed_unverified'
            except Exception as exc:
                from computer_mcp.permission import PermissionDenied
                row.update(state='cancelled' if isinstance(exc,PermissionDenied) else 'failed',error=str(exc))
                self.failed.append(str(exc))
                if isinstance(exc,PermissionDenied) or (self.stop_on_fail and instruction.get('on_fail','stop')!='continue'):
                    raise
            finally:
                self.log.append('L%s %s: %s'%(row['line'],row['op'],row['state']))

    def run(self):
        state='running'
        try:
            with execution.operation('run_script'):
                self.execute(self.instructions)
            state='failed' if self.failed else ('succeeded' if all(r['verified'] for r in self.rows) else 'executed_unverified')
        except Exception as exc:
            from computer_mcp.permission import PermissionDenied
            state='cancelled' if isinstance(exc,PermissionDenied) else 'failed'
            if not self.failed:self.failed.append(str(exc))
        return dict(ok=state=='succeeded',state=state,verified=state=='succeeded',done=self.done,
                    failed='; '.join(self.failed),log=self.log,steps=self.rows,artifacts=self.artifacts)
