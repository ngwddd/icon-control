"""Native one-window approval: a Windows task dialog instead of a Tk form.

TaskDialogIndirect lives in comctl32 v6, which Python only sees after an
activation context is created from a manifest. When that is unavailable the
caller falls back to the existing Tk control center.
"""
from __future__ import annotations

import ctypes
import os
import tempfile
from ctypes import wintypes
from pathlib import Path

TDF_ALLOW_DIALOG_CANCELLATION = 0x0008
TDF_SIZE_TO_CONTENT = 0x01000000
TDF_VERIFICATION_FLAG_CHECKED = 0x0100
TD_INFORMATION_ICON = 65533

BUTTON_GRANT = 100
BUTTON_CANCEL = 101
BUTTON_ADVANCED = 102

PRESETS = (
    ('常用', '读取整个桌面 + 鼠标键盘 + 文字输入',
     ('screen_read', 'input', 'text_entry')),
    ('只读', '只读取整个桌面与窗口信息',
     ('screen_read',)),
    ('全部', '再加剪贴板读写、文件读写、启动/关闭程序',
     ('screen_read', 'input', 'text_entry', 'clipboard_read', 'clipboard_write',
      'file_read', 'file_write', 'file_delete', 'window_close', 'process', 'config_write')),
)


class TASKDIALOG_BUTTON(ctypes.Structure):
    # commctrl.h declares this inside the same pshpack1 block as the config:
    # the element is 12 bytes on x64, not 16. Getting this wrong crashes the
    # dialog with an access violation on the second button's text pointer.
    _pack_ = 1
    _fields_ = [('nButtonID', ctypes.c_int), ('pszButtonText', wintypes.LPCWSTR)]


class TASKDIALOGCONFIG(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ('cbSize', wintypes.UINT),
        ('hwndParent', wintypes.HWND),
        ('hInstance', wintypes.HINSTANCE),
        ('dwFlags', wintypes.DWORD),
        ('dwCommonButtons', wintypes.DWORD),
        ('pszWindowTitle', wintypes.LPCWSTR),
        ('pszMainIcon', ctypes.c_void_p),
        ('pszMainInstruction', wintypes.LPCWSTR),
        ('pszContent', wintypes.LPCWSTR),
        ('cButtons', wintypes.UINT),
        ('pButtons', ctypes.POINTER(TASKDIALOG_BUTTON)),
        ('nDefaultButton', ctypes.c_int),
        ('cRadioButtons', wintypes.UINT),
        ('pRadioButtons', ctypes.POINTER(TASKDIALOG_BUTTON)),
        ('nDefaultRadioButton', ctypes.c_int),
        ('pszVerificationText', wintypes.LPCWSTR),
        ('pszExpandedInformation', wintypes.LPCWSTR),
        ('pszExpandedControlText', wintypes.LPCWSTR),
        ('pszCollapsedControlText', wintypes.LPCWSTR),
        ('hFooterIcon', ctypes.c_void_p),
        ('pszFooter', wintypes.LPCWSTR),
        ('pfCallback', ctypes.c_void_p),
        ('lpCallbackData', ctypes.c_ssize_t),
        ('cxWidth', wintypes.UINT),
    ]


_library = None


def _common_controls():
    """comctl32 that actually exports TaskDialogIndirect.

    Modern Windows ships a v6 comctl32 that most processes already have mapped,
    so a plain load usually works. When it does not, fall back to the side-by-side
    v6 assembly on disk instead of relying on an activation context (which cannot
    replace a DLL that is already loaded in the process).
    """
    global _library
    if _library is not None:
        return _library
    candidates = ['comctl32']
    try:
        import glob
        found = sorted(glob.glob(r'C:\Windows\WinSxS\amd64_microsoft.windows.common-controls_*\comctl32.dll'))
        candidates += found[-3:]
    except OSError:
        pass
    for name in candidates:
        try:
            library = ctypes.WinDLL(name, use_last_error=True)
            library.TaskDialogIndirect
            _library = library
            return library
        except (OSError, AttributeError):
            continue
    _library = False
    return False


def available() -> bool:
    if os.name != 'nt':
        return False
    return bool(_common_controls())


def ask_grant(agent_label: str, target_text: str, *, default_preset: int = 0,
              lease_minutes: int = 60, note: str = '') -> dict | None:
    """Show the single approval window. Returns None when unavailable."""
    if not available():
        return None
    library = _common_controls()
    library.TaskDialogIndirect.argtypes = [
        ctypes.POINTER(TASKDIALOGCONFIG), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(wintypes.BOOL)]
    library.TaskDialogIndirect.restype = ctypes.c_long

    buttons = (TASKDIALOG_BUTTON * 3)(
        TASKDIALOG_BUTTON(BUTTON_GRANT, '一键授权'),
        TASKDIALOG_BUTTON(BUTTON_CANCEL, '取消'),
        TASKDIALOG_BUTTON(BUTTON_ADVANCED, '高级…'),
    )
    radios = (TASKDIALOG_BUTTON * len(PRESETS))(
        *[TASKDIALOG_BUTTON(200 + index, f'{name}：{detail}')
          for index, (name, detail, _scopes) in enumerate(PRESETS)])

    content = (
        f'Agent：{agent_label}\r\n'
        f'目标：{target_text}\r\n\r\n'
        '批准范围（单选）：'
    )
    verification = f'{lease_minutes} 分钟内，本工作区的新进程自动沿用这次授权'
    expanded = ('目标不对？先关掉这个窗口，把要操作的应用切到前台，再按热键重新打开。\r\n'
                '「高级…」打开逐项勾选（旧的 Tk 控制中心）。')

    config = TASKDIALOGCONFIG()
    config.cbSize = ctypes.sizeof(TASKDIALOGCONFIG)
    config.dwFlags = TDF_ALLOW_DIALOG_CANCELLATION | TDF_SIZE_TO_CONTENT | TDF_VERIFICATION_FLAG_CHECKED
    config.pszWindowTitle = 'Icon Control'
    config.pszMainIcon = ctypes.c_void_p(TD_INFORMATION_ICON)
    config.pszMainInstruction = 'Icon Control 请求授权'
    config.pszContent = content
    config.cButtons = len(buttons)
    config.pButtons = buttons
    config.nDefaultButton = BUTTON_GRANT
    config.cRadioButtons = len(radios)
    config.pRadioButtons = radios
    config.nDefaultRadioButton = 200 + default_preset
    config.pszVerificationText = verification
    config.pszExpandedInformation = expanded
    config.pszExpandedControlText = '说明'
    config.pszCollapsedControlText = '说明'

    button = ctypes.c_int(BUTTON_CANCEL)
    radio = ctypes.c_int(200 + default_preset)
    checked = wintypes.BOOL(1)
    result = library.TaskDialogIndirect(ctypes.byref(config), ctypes.byref(button),
                                        ctypes.byref(radio), ctypes.byref(checked))
    if result != 0:
        raise OSError(result, 'TaskDialogIndirect failed')
    chosen = max(0, min(len(PRESETS) - 1, radio.value - 200))
    return dict(button=button.value, preset=chosen,
                scopes=list(PRESETS[chosen][2]),
                lease_minutes=lease_minutes if checked.value else None,
                accepted=button.value == BUTTON_GRANT)


def _probe() -> int:
    """Manual check: python -m computer_mcp.native_dialog --probe"""
    if not available():
        print('TaskDialogIndirect unavailable (comctl32 v6 activation failed)')
        return 2
    answer = ask_grant('DSH · icon-control（探针）', 'notepad.exe · PID 0（探针）')
    print(answer)
    return 0


if __name__ == '__main__':
    import sys
    if '--probe' in sys.argv:
        raise SystemExit(_probe())
    print('usage: python -m computer_mcp.native_dialog --probe')
