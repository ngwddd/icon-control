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

def require_clipboard_scopes(scopes):
    from computer_mcp import capabilities, permission, execution
    state = permission.status()
    missing = set(scopes) - set((state.get('authorization') or {}).get('scopes') or [])
    if not state.get('granted') or missing:
        permission._request_consent(missing=set(scopes) | {'input'})
        raise permission.PermissionDenied('Clipboard shortcut requires: ' + ', '.join(sorted(scopes)))
    execution.authority_stamp(state)


def normalized_key_tokens(key):
    """Normalize enum, character and VK-only forms at the input boundary.

    Use both char and vk when both are supplied: a contradictory char must not
    hide the virtual key that Windows will actually receive.
    """
    from pynput.keyboard import Key
    value = key.value if isinstance(key, Key) else key
    char = value if isinstance(value, str) else getattr(value, 'char', None)
    tokens = {char.lower()} if isinstance(char, str) and char else set()
    vk = getattr(value, 'vk', None)
    virtual = {0x41: 'a', 0x43: 'c', 0x58: 'x', 0x56: 'v',
               0x11: 'ctrl', 0xA2: 'ctrl', 0xA3: 'ctrl',
               0x10: 'shift', 0xA0: 'shift', 0xA1: 'shift',
               0x12: 'alt', 0xA4: 'alt', 0xA5: 'alt',
               0x2D: 'insert', 0x2E: 'delete'}
    if vk in virtual:
        tokens.add(virtual[vk])
    # Also handle enum names on backends whose modifier values lack a VK.
    if isinstance(key, Key):
        name = key.name
        tokens.add(name.split('_', 1)[0] if name.startswith(('ctrl', 'shift', 'alt')) else name)
    return tokens


def check_clipboard_chord(key, modifiers):
    """Clipboard scopes apply equally to named and numeric shortcut keys."""
    modifier_tokens = set()
    for modifier in modifiers:
        modifier_tokens.update(normalized_key_tokens(modifier))
    keys = normalized_key_tokens(key)
    ctrl, shift = 'ctrl' in modifier_tokens, 'shift' in modifier_tokens
    scopes = set()
    if ctrl and keys & {'c', 'x', 'insert'}:
        scopes.add('clipboard_write')
    if (ctrl and 'v' in keys) or (shift and 'insert' in keys):
        scopes.add('clipboard_read')
    if shift and 'delete' in keys:
        scopes.add('clipboard_write')
    if scopes:
        require_clipboard_scopes(scopes)


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
    if letter in ('c', 'x'):
        require_clipboard_scopes({'clipboard_write'})
    elif letter == 'v':
        require_clipboard_scopes({'clipboard_read'})
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
