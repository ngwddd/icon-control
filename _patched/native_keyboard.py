"""Checked Windows keyboard packets and IME-independent standard-edit shortcuts."""
import ctypes
from ctypes import wintypes
from computer_mcp.native_mouse import MOUSEINPUT

UNICODE = 0x0004
KEYUP = 0x0002

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk',wintypes.WORD),('wScan',wintypes.WORD),('dwFlags',wintypes.DWORD),
                ('time',wintypes.DWORD),('dwExtraInfo',ctypes.c_size_t)]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [('uMsg',wintypes.DWORD),('wParamL',wintypes.WORD),('wParamH',wintypes.WORD)]

class INPUTUNION(ctypes.Union):
    _fields_ = [('ki',KEYBDINPUT),('mi',MOUSEINPUT),('hi',HARDWAREINPUT)]

class INPUT(ctypes.Structure):
    _fields_ = [('type',wintypes.DWORD),('u',INPUTUNION)]

def send_key(vk=0, scan=0, flags=0):
    user32=ctypes.WinDLL('user32',use_last_error=True)
    user32.SendInput.argtypes=(wintypes.UINT,ctypes.POINTER(INPUT),ctypes.c_int)
    user32.SendInput.restype=wintypes.UINT
    packet=INPUT(1,INPUTUNION(ki=KEYBDINPUT(vk,scan,flags,0,0x49434F4E)))
    if user32.SendInput(1,ctypes.byref(packet),ctypes.sizeof(INPUT))!=1:
        raise OSError(ctypes.get_last_error(),'Keyboard SendInput was rejected')

def unicode_units(character):
    data=character.encode('utf-16-le')
    return [int.from_bytes(data[i:i+2],'little') for i in range(0,len(data),2)]

def send_unicode(character, pressed):
    for unit in unicode_units(character):
        send_key(scan=unit,flags=UNICODE | (0 if pressed else KEYUP))

class GUITHREADINFO(ctypes.Structure):
    _fields_=[('cbSize',wintypes.DWORD),('flags',wintypes.DWORD),
              *[(name,wintypes.HWND) for name in ('hwndActive','hwndFocus','hwndCapture','hwndMenuOwner','hwndMoveSize','hwndCaret')],
              ('rcCaret',wintypes.RECT)]

def edit_shortcut(letter):
    """Use explicit edit commands only on the actual focused standard edit."""
    import win32gui,win32process
    from computer_mcp import execution,capabilities,permission
    messages={'a':(0xB1,0,-1),'c':(0x301,0,0),'x':(0x300,0,0),'v':(0x302,0,0)}
    if letter not in messages:
        return False
    foreground=win32gui.GetForegroundWindow()
    thread,_=win32process.GetWindowThreadProcessId(foreground)
    info=GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
    user32=ctypes.WinDLL('user32',use_last_error=True)
    if not user32.GetGUIThreadInfo(thread,ctypes.byref(info)):
        raise OSError(ctypes.get_last_error(),'Cannot resolve keyboard focus')
    hwnd=info.hwndFocus
    if not hwnd:
        return False
    kind=win32gui.GetClassName(hwnd).lower()
    # Windows Forms prefixes the native Edit class with its runtime generation.
    if not (kind=='edit' or kind.startswith('richedit') or kind.startswith('windowsforms10.edit.')):
        return False
    if win32gui.GetAncestor(hwnd,2)!=foreground:
        raise permission.PermissionDenied('Focused edit belongs to another window')
    execution.check('key_press')
    capabilities.require_target(hwnd=hwnd)
    if win32gui.GetForegroundWindow()!=foreground:
        raise permission.PermissionDenied('Foreground changed before shortcut')
    current=GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
    if not user32.GetGUIThreadInfo(thread,ctypes.byref(current)) or current.hwndFocus!=hwnd:
        raise permission.PermissionDenied('Focused edit changed before shortcut')
    message,wparam,lparam=messages[letter]
    user32.SendMessageTimeoutW.argtypes=(wintypes.HWND,wintypes.UINT,ctypes.c_size_t,ctypes.c_ssize_t,
                                        wintypes.UINT,wintypes.UINT,ctypes.POINTER(ctypes.c_size_t))
    user32.SendMessageTimeoutW.restype=ctypes.c_ssize_t
    result=ctypes.c_size_t()
    if not user32.SendMessageTimeoutW(hwnd,message,wparam,lparam,2,300,ctypes.byref(result)):
        raise OSError(ctypes.get_last_error(),'Edit shortcut timed out')
    return True
