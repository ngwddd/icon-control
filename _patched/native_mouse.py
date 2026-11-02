"""Windows movement through SendInput, retaining the OS injected-event flag."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import math
import sys
from contextlib import contextmanager

MOVE = 0x0001
VIRTUALDESK = 0x4000
ABSOLUTE = 0x8000
EXTRA_INFO = 0x49434F4E

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG),
                ('mouseData', wintypes.DWORD), ('dwFlags', wintypes.DWORD),
                ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.c_size_t)]

class _INPUTUNION(ctypes.Union):
    _fields_ = [('mi', MOUSEINPUT)]

class INPUT(ctypes.Structure):
    _fields_ = [('type', wintypes.DWORD), ('u', _INPUTUNION)]

def absolute_packet(x, y, desktop):
    left, top, width, height = desktop
    if width <= 0 or height <= 0 or not all(math.isfinite(float(v)) for v in (x,y)):
        raise ValueError('Invalid virtual desktop or position')
    x,y=int(x),int(y)
    if not (left <= x < left+width and top <= y < top+height):
        raise ValueError('Position is outside the virtual desktop')
    # SendInput maps 0..65535 across the virtual desktop. Aim inside the
    # destination pixel, including negative monitor origins and edge pixels.
    dx=min(65535, ((x-left)*65536+32768)//width)
    dy=min(65535, ((y-top)*65536+32768)//height)
    return INPUT(0, _INPUTUNION(mi=MOUSEINPUT(dx,dy,0,MOVE|ABSOLUTE|VIRTUALDESK,0,EXTRA_INFO)))

@contextmanager
def physical_coordinates():
    """Scope physical coordinates to this thread, including unaware hosts."""
    if sys.platform != 'win32':
        yield;return
    user32=ctypes.WinDLL('user32',use_last_error=True)
    setter=user32.SetThreadDpiAwarenessContext
    setter.argtypes=(ctypes.c_void_p,);setter.restype=ctypes.c_void_p
    previous=setter(ctypes.c_void_p(-4))
    if not previous:raise OSError(ctypes.get_last_error(),'Cannot establish physical coordinate context')
    try:yield
    finally:setter(previous)

def cursor_position():
    user32=ctypes.WinDLL('user32',use_last_error=True)
    point=wintypes.POINT()
    if not user32.GetPhysicalCursorPos(ctypes.byref(point)):
        raise OSError(ctypes.get_last_error(),'GetPhysicalCursorPos failed')
    return point.x,point.y

def move_absolute(x, y):
    with physical_coordinates():
        user32=ctypes.WinDLL('user32',use_last_error=True)
        desktop=tuple(user32.GetSystemMetrics(index) for index in (76,77,78,79))
        packet=absolute_packet(x,y,desktop)
        user32.SendInput.argtypes=(wintypes.UINT,ctypes.POINTER(INPUT),ctypes.c_int)
        user32.SendInput.restype=wintypes.UINT
        if user32.SendInput(1,ctypes.byref(packet),ctypes.sizeof(INPUT)) != 1:
            raise OSError(ctypes.get_last_error(),'SendInput failed; no cursor fallback is allowed')
