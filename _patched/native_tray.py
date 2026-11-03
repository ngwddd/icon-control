"""Tray icon helpers on top of Shell_NotifyIcon.

Kept separate from the consent host so a broken shell integration degrades to
"no tray icon" instead of taking the approval window down with it.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_INFO = 0x00000010
NIIF_INFO = 0x00000001
NIIF_WARNING = 0x00000002


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('hWnd', wintypes.HWND),
        ('uID', wintypes.UINT),
        ('uFlags', wintypes.UINT),
        ('uCallbackMessage', wintypes.UINT),
        ('hIcon', wintypes.HICON),
        ('szTip', wintypes.WCHAR * 128),
        ('dwState', wintypes.DWORD),
        ('dwStateMask', wintypes.DWORD),
        ('szInfo', wintypes.WCHAR * 256),
        ('uVersion', wintypes.UINT),
        ('szInfoTitle', wintypes.WCHAR * 64),
        ('dwInfoFlags', wintypes.DWORD),
    ]


def _shell():
    return ctypes.WinDLL('shell32', use_last_error=True)


def _default_icon():
    # IDI_INFORMATION: always present, no resource file needed.
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    return user32.LoadIconW(None, wintypes.LPCWSTR(32516))


def add(hwnd: int, uid: int, callback_message: int, tip: str) -> bool:
    data = NOTIFYICONDATAW()
    data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
    data.hWnd = hwnd
    data.uID = uid
    data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
    data.uCallbackMessage = callback_message
    data.hIcon = _default_icon()
    data.szTip = tip[:127]
    return bool(_shell().Shell_NotifyIconW(NIM_ADD, ctypes.byref(data)))


def update(hwnd: int, uid: int, tip: str) -> bool:
    data = NOTIFYICONDATAW()
    data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
    data.hWnd = hwnd
    data.uID = uid
    data.uFlags = NIF_TIP
    data.szTip = tip[:127]
    return bool(_shell().Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(data)))


def balloon(hwnd: int, uid: int, title: str, text: str, warning: bool = False) -> bool:
    data = NOTIFYICONDATAW()
    data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
    data.hWnd = hwnd
    data.uID = uid
    data.uFlags = NIF_INFO
    data.szInfoTitle = title[:63]
    data.szInfo = text[:255]
    data.dwInfoFlags = NIIF_WARNING if warning else NIIF_INFO
    return bool(_shell().Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(data)))


def remove(hwnd: int, uid: int) -> bool:
    data = NOTIFYICONDATAW()
    data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
    data.hWnd = hwnd
    data.uID = uid
    return bool(_shell().Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data)))
