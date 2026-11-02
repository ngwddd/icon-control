"""Bounded, process-local element references bound to window and rendered state."""
from __future__ import annotations
import copy
import hashlib
import threading
import time
import uuid

_snapshots={}
_lock=threading.RLock()
TTL_SECONDS=5.0
MAX_SNAPSHOTS=64

class StaleReference(ValueError): pass

def window_identity(hwnd):
    import win32gui, win32process, psutil
    if not hwnd or not win32gui.IsWindow(hwnd): raise StaleReference('Window no longer exists')
    _,pid=win32process.GetWindowThreadProcessId(hwnd)
    import ctypes
    from ctypes import wintypes
    function=ctypes.windll.user32.GetDpiForWindow
    function.argtypes=[wintypes.HWND];function.restype=wintypes.UINT
    return (int(hwnd),pid,psutil.Process(pid).create_time(),win32gui.GetWindowText(hwnd),
            tuple(win32gui.GetWindowRect(hwnd)),function(hwnd))

def screen_fingerprint(identity):
    from computer_mcp.core.screenshot import _grab
    l,t,r,b=identity[4]
    image,_,_=_grab({'x':l,'y':t,'w':r-l,'h':b-t})
    return hashlib.sha256(image.tobytes()).hexdigest()

def attach(hwnd,candidates):
    identity=window_identity(hwnd)
    digest=screen_fingerprint(identity)
    now=time.monotonic();key=uuid.uuid4().hex
    nodes=copy.deepcopy(candidates[:1000])
    for index,node in enumerate(nodes):node['ref']=key+':'+str(index)
    with _lock:
        for old in list(_snapshots):
            if now-_snapshots[old]['created']>TTL_SECONDS:_snapshots.pop(old)
        while len(_snapshots)>=MAX_SNAPSHOTS:_snapshots.pop(next(iter(_snapshots)))
        _snapshots[key]=dict(created=now,identity=identity,digest=digest,nodes=copy.deepcopy(nodes))
    return dict(snapshot_id=key,expires_in_s=TTL_SECONDS,hwnd=int(hwnd),candidates=nodes)

def resolve(ref,hwnd=None):
    try:key,index=ref.split(':');index=int(index)
    except (AttributeError,ValueError):raise StaleReference('Invalid element reference') from None
    with _lock: item=copy.deepcopy(_snapshots.get(key))
    if not item or time.monotonic()-item['created']>TTL_SECONDS:
        raise StaleReference('Element reference expired; observe again')
    if index<0 or index>=len(item['nodes']):raise StaleReference('Unknown element reference')
    expected=item['identity']
    if hwnd is not None and int(hwnd)!=expected[0]:raise StaleReference('Reference belongs to another window')
    current=window_identity(expected[0])
    if current!=expected or screen_fingerprint(current)!=item['digest']:
        raise StaleReference('Window, DPI or content changed; observe again')
    target=item['nodes'][index];target['hwnd']=expected[0]
    target.setdefault('cx',target['x']+target['w']//2)
    target.setdefault('cy',target['y']+target['h']//2)
    l,t,r,b=expected[4]
    if not l<=target['cx']<r or not t<=target['cy']<b:raise StaleReference('Target outside window')
    return target
