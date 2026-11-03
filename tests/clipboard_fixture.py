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

def snapshot():
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
        return saved

def restore(saved):
    with opened():
        clip.EmptyClipboard()
        for fmt,data in saved:
            # CF_UNICODETEXT is the one format whose pywin32 setter expects str.
            clip.SetClipboardData(fmt,data.decode('utf-16-le','surrogatepass').rstrip('\x00') if fmt==13 else data)
        for fmt,data in saved:
            actual=memory_data(fmt)
            if fmt==13:
                if actual.decode('utf-16-le','surrogatepass').rstrip('\x00')!=data.decode('utf-16-le','surrogatepass').rstrip('\x00'):
                    raise RuntimeError('Clipboard text restoration mismatch')
            # pywin32 may append a terminator (CF_TEXT). Require the entire
            # original allocation to remain intact; extra storage is harmless.
            elif len(actual)<len(data) or actual[:len(data)]!=data:
                raise RuntimeError('Clipboard format '+str(fmt)+' restoration mismatch ('+str(len(data))+' / '+str(len(actual))+' bytes)')

@contextmanager
def preserve_clipboard():
    saved=snapshot()  # Failure must precede any clipboard mutation.
    try:yield
    finally:restore(saved)
