"""In-memory clipboard preservation for real smoke tests; never persists user data.

Use immediate Win32 memory formats, avoiding this machine's crashing OLE flush.
Windows synthesizes CF_BITMAP from preserved DIB/DIBV5 data. OLE's DataObject
and Ole Private Data entries describe a live owner and are not portable payloads.
https://learn.microsoft.com/en-us/windows/win32/dataxchg/clipboard-formats
"""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import time
import win32clipboard as clip

user32=ctypes.WinDLL('user32',use_last_error=True)
kernel32=ctypes.WinDLL('kernel32',use_last_error=True)
user32.GetClipboardData.argtypes=[wintypes.UINT];user32.GetClipboardData.restype=wintypes.HANDLE
user32.GetClipboardSequenceNumber.argtypes=[];user32.GetClipboardSequenceNumber.restype=wintypes.DWORD
user32.GetClipboardOwner.argtypes=[];user32.GetClipboardOwner.restype=wintypes.HWND
user32.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype=wintypes.DWORD
kernel32.GlobalSize.argtypes=[wintypes.HANDLE];kernel32.GlobalSize.restype=ctypes.c_size_t
kernel32.GlobalLock.argtypes=[wintypes.HANDLE];kernel32.GlobalLock.restype=ctypes.c_void_p
kernel32.GlobalUnlock.argtypes=[wintypes.HANDLE];kernel32.GlobalUnlock.restype=wintypes.BOOL

@contextmanager
def opened():
    deadline=time.monotonic()+3
    while True:
        try:clip.OpenClipboard();break
        except Exception:
            if time.monotonic()>=deadline:raise
            time.sleep(.03)
    try:yield
    finally:clip.CloseClipboard()

def memory_data(fmt,limit=64*1024*1024):
    handle=user32.GetClipboardData(fmt)
    size=kernel32.GlobalSize(handle)
    if not handle or not size or size>limit:
        raise RuntimeError('Clipboard format cannot be preserved safely; no test input sent')
    pointer=kernel32.GlobalLock(handle)
    if not pointer:raise RuntimeError('Clipboard payload unavailable; no test input sent')
    try:return ctypes.string_at(pointer,size)
    finally:kernel32.GlobalUnlock(handle)

class ClipboardConflict(RuntimeError):pass

def sequence():return user32.GetClipboardSequenceNumber()

def owner_pid():
    pid=wintypes.DWORD()
    user32.GetWindowThreadProcessId(user32.GetClipboardOwner(),ctypes.byref(pid))
    return pid.value

def prepare_restore(saved):
    prepared=[]
    for fmt,data in saved:
        if fmt==13 and len(data)%2:raise RuntimeError('Malformed clipboard Unicode data; no test input sent')
        value=data.decode('utf-16-le','surrogatepass').rstrip('\x00') if fmt==13 else data
        prepared.append((fmt,value,data))
    return prepared

def snapshot(with_sequence=False):
    with opened():
        formats=[];fmt=clip.EnumClipboardFormats(0)
        while fmt:formats.append(fmt);fmt=clip.EnumClipboardFormats(fmt)
        saved=[];remaining=64*1024*1024
        for fmt in formats:
            try:name=clip.GetClipboardFormatName(fmt)
            except Exception:name=''
            if name in ('DataObject','Ole Private Data'):continue
            if fmt==2 and (8 in formats or 17 in formats):continue
            if fmt in (2,3,9,14,0x80,0x82,0x83,0x8e):
                raise RuntimeError('Unsupported non-memory clipboard format; no test input sent')
            data=memory_data(fmt,remaining);remaining-=len(data)
            saved.append((fmt,data))
        prepare_restore(saved)  # Validate every representation before admitting a test.
        return (saved,sequence()) if with_sequence else saved

def restore(saved,expected_sequence,expected_owner=None):
    prepared=prepare_restore(saved)  # Decoding must never happen after clearing.
    with opened():
        if sequence()!=expected_sequence or (expected_owner is not None and owner_pid()!=expected_owner):
            raise ClipboardConflict('Clipboard changed outside this test; newer data preserved')
        clip.EmptyClipboard()
        for fmt,value,_ in prepared:clip.SetClipboardData(fmt,value)
        for fmt,_,data in prepared:
            actual=memory_data(fmt)
            if fmt==13:
                if actual.decode('utf-16-le','surrogatepass').rstrip('\x00')!=data.decode('utf-16-le','surrogatepass').rstrip('\x00'):
                    raise RuntimeError('Clipboard text restoration mismatch')
            # pywin32 may append a terminator (CF_TEXT). Require the entire
            # original allocation to remain intact; extra storage is harmless.
            elif len(actual)<len(data) or actual[:len(data)]!=data:
                raise RuntimeError('Clipboard format '+str(fmt)+' restoration mismatch ('+str(len(data))+' / '+str(len(actual))+' bytes)')

class ClipboardLease:
    def __init__(self,saved,initial):
        self.saved=saved;self.initial=initial;self.owned_sequence=None;self.owned_pid=None
    def before_copy(self):
        with opened():
            if sequence()!=self.initial:raise ClipboardConflict('Clipboard changed before test copy; copy cancelled')
    def claim_test_text(self,text,pid):
        with opened():
            if (clip.GetClipboardData(13)!=text or owner_pid()!=pid or sequence()==self.initial):
                raise ClipboardConflict('Clipboard contents or owner do not match this test; not claiming newer data')
            self.owned_sequence=sequence();self.owned_pid=pid
    def finish(self):
        if sequence()==self.initial:return  # Test never changed it; no clearing needed.
        if self.owned_sequence is None:raise ClipboardConflict('Unowned clipboard change preserved')
        restore(self.saved,self.owned_sequence,self.owned_pid)

@contextmanager
def preserve_clipboard():
    saved,initial=snapshot(with_sequence=True)
    prepare_restore(saved)
    lease=ClipboardLease(saved,initial)
    try:yield lease
    finally:lease.finish()
