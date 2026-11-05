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
TDF_NO_DEFAULT_RADIO_BUTTON = 0x4000
TDF_VERIFICATION_FLAG_CHECKED = 0x0100
TD_INFORMATION_ICON = 65533

BUTTON_GRANT = 100
BUTTON_CANCEL = 101
BUTTON_ADVANCED = 102
BUTTON_RENEW = 103
BUTTON_REVOKE = 104
BUTTON_QUIT = 105
BUTTON_PENDING = 106
BUTTON_TRUST = 107

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


def _force_foreground(timeout: float = 2.5) -> None:
    """A background process' dialog can open behind the active window.

    Windows only grants foreground rights after real user input, so ask for the
    window as soon as it exists and let the OS decide whether to honour it.
    """
    import threading
    import time

    def work():
        import win32gui
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            hwnd = win32gui.FindWindow(None, 'Icon Control')
            if hwnd:
                try:
                    win32gui.BringWindowToTop(hwnd)
                    win32gui.SetForegroundWindow(hwnd)
                except Exception:
                    pass
                return
            time.sleep(0.05)

    threading.Thread(target=work, daemon=True).start()


def preset_for(scopes) -> int:
    """Tightest preset that still covers the requested scopes (2 = 全部)."""
    wanted = set(scopes or ())
    if not wanted:
        return 0
    best = None
    for index, (_name, _detail, preset_scopes) in enumerate(PRESETS):
        candidate = set(preset_scopes)
        if wanted <= candidate and (best is None or len(candidate) < len(PRESETS[best][2])):
            best = index
    return -1 if best is None else best


def ask_grant(agent_label: str, target_text: str, *, default_preset: int = 0,
              lease_minutes: int = 60, note: str = '', needs=None) -> dict | None:
    """Show the single approval window. Returns None when unavailable."""
    if not available():
        return None
    library = _common_controls()
    library.TaskDialogIndirect.argtypes = [
        ctypes.POINTER(TASKDIALOGCONFIG), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(wintypes.BOOL)]
    library.TaskDialogIndirect.restype = ctypes.c_long

    buttons = (TASKDIALOG_BUTTON * 2)(
        TASKDIALOG_BUTTON(BUTTON_GRANT, '一键授权'),
        TASKDIALOG_BUTTON(BUTTON_CANCEL, '取消'),
    )
    from computer_mcp import capabilities
    requested = sorted(set(needs or []))
    if not set(requested) <= capabilities.SCOPES:
        raise ValueError('Requested capability is not supported')
    choices = list(PRESETS)
    if requested:
        choices.append(('本次所需', '仅授予：' + '、'.join(requested), tuple(requested)))
        default_preset = len(choices) - 1
    radios = (TASKDIALOG_BUTTON * len(choices))(
        *[TASKDIALOG_BUTTON(200 + index, f'{name}：{detail}')
          for index, (name, detail, _scopes) in enumerate(choices)])

    needed = ''
    if needs:
        needed = '\r\n本次调用需要：' + '、'.join(str(item) for item in needs)
    content = (
        f'Agent：{agent_label}\r\n'
        f'目标：{target_text}{needed}\r\n\r\n'
        '批准范围（单选）：'
    )
    if note:
        content += '\r\n' + note
    verification = f'{lease_minutes} 分钟内，仅此 Agent 会话和所选应用可使用本次授权'
    expanded = ('请核对请求方、目标和缺少的能力。切换 Agent 会原子替换原授权，不会授权给其他会话。\r\n'
                '授权只覆盖这一次列出的范围；60 分钟到期或托盘撤销后立即失效。')

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

    _force_foreground()
    button = ctypes.c_int(BUTTON_CANCEL)
    radio = ctypes.c_int(200 + default_preset)
    checked = wintypes.BOOL(1)
    result = library.TaskDialogIndirect(ctypes.byref(config), ctypes.byref(button),
                                        ctypes.byref(radio), ctypes.byref(checked))
    if result != 0:
        raise OSError(result, 'TaskDialogIndirect failed')
    chosen = radio.value - 200
    if not 0 <= chosen < len(choices):
        raise ValueError("Invalid capability selection")
    return dict(button=button.value, preset=chosen,
                scopes=list(choices[chosen][2]),
                lease_minutes=lease_minutes if checked.value else None,
                accepted=button.value == BUTTON_GRANT)


def ask_trust(days: int = 30, subject: str = '') -> bool:
    """One-click trust prompt. Returns True only when the user clicks trust.

    This is the only supported way to create a long-lived trust record: the
    record itself is written by ``trust.grant(confirm=...)`` with this answer,
    so no code path can mint trust without a real click.
    """
    if not available():
        return False
    library = _common_controls()
    library.TaskDialogIndirect.argtypes = [
        ctypes.POINTER(TASKDIALOGCONFIG), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(wintypes.BOOL)]
    library.TaskDialogIndirect.restype = ctypes.c_long
    buttons = (TASKDIALOG_BUTTON * 2)(
        TASKDIALOG_BUTTON(BUTTON_GRANT, f'信任 {days} 天'),
        TASKDIALOG_BUTTON(BUTTON_CANCEL, '取消'),
    )
    content = (f'允许此安装的助手在 {days} 天内直接操作普通桌面应用？'
               '\r\n\r\n'
               '信任只对当前安装、当前工作区和当前工具版本有效：'
               '升级助手、更换工作区、点「撤销」或急停后都需要重新授权。'
               '\r\n权限 UI 与撤销入口始终不会被自动化。')
    if subject:
        content += f'\r\n\r\n主体指纹：{subject[:16]}…'
    config = TASKDIALOGCONFIG()
    config.cbSize = ctypes.sizeof(TASKDIALOGCONFIG)
    config.dwFlags = TDF_ALLOW_DIALOG_CANCELLATION | TDF_SIZE_TO_CONTENT
    config.pszWindowTitle = 'Icon Control'
    config.pszMainIcon = ctypes.c_void_p(TD_INFORMATION_ICON)
    config.pszMainInstruction = f'信任此助手 {days} 天'
    config.pszContent = content
    config.cButtons = 2
    config.pButtons = buttons
    config.nDefaultButton = BUTTON_CANCEL
    _force_foreground()
    button = ctypes.c_int(BUTTON_CANCEL)
    radio = ctypes.c_int(0)
    checked = wintypes.BOOL(0)
    result = library.TaskDialogIndirect(ctypes.byref(config), ctypes.byref(button),
                                        ctypes.byref(radio), ctypes.byref(checked))
    if result != 0:
        raise OSError(result, 'TaskDialogIndirect failed')
    return button.value == BUTTON_GRANT


def ask_notice(title: str, message: str) -> None:
    """Plain native notice: no presets, no grant button."""
    if not available():
        return
    library = _common_controls()
    library.TaskDialogIndirect.argtypes = [
        ctypes.POINTER(TASKDIALOGCONFIG), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(wintypes.BOOL)]
    library.TaskDialogIndirect.restype = ctypes.c_long
    buttons = (TASKDIALOG_BUTTON * 1)(TASKDIALOG_BUTTON(BUTTON_CANCEL, '知道了'))
    config = TASKDIALOGCONFIG()
    config.cbSize = ctypes.sizeof(TASKDIALOGCONFIG)
    config.dwFlags = TDF_ALLOW_DIALOG_CANCELLATION | TDF_SIZE_TO_CONTENT
    config.pszWindowTitle = 'Icon Control'
    config.pszMainIcon = ctypes.c_void_p(TD_INFORMATION_ICON)
    config.pszMainInstruction = title
    config.pszContent = message
    config.cButtons = 1
    config.pButtons = buttons
    config.nDefaultButton = BUTTON_CANCEL
    _force_foreground()
    button = ctypes.c_int(BUTTON_CANCEL)
    radio = ctypes.c_int(0)
    checked = wintypes.BOOL(0)
    library.TaskDialogIndirect(ctypes.byref(config), ctypes.byref(button),
                               ctypes.byref(radio), ctypes.byref(checked))


def ask_status(headline: str, detail: str, *, remaining: str = '') -> dict | None:
    """Show the lease that is currently in force, with renew/revoke actions."""
    if not available():
        return None
    library = _common_controls()
    library.TaskDialogIndirect.argtypes = [
        ctypes.POINTER(TASKDIALOGCONFIG), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(wintypes.BOOL)]
    library.TaskDialogIndirect.restype = ctypes.c_long
    buttons = (TASKDIALOG_BUTTON * 6)(
        TASKDIALOG_BUTTON(BUTTON_PENDING, '处理当前待授权请求'),
        TASKDIALOG_BUTTON(BUTTON_RENEW, '续 60 分钟'),
        TASKDIALOG_BUTTON(BUTTON_TRUST, '信任此助手 30 天'),
        TASKDIALOG_BUTTON(BUTTON_REVOKE, '立即撤销'),
        TASKDIALOG_BUTTON(BUTTON_QUIT, '退出 Icon Control'),
        TASKDIALOG_BUTTON(BUTTON_CANCEL, '关闭'),
    )
    config = TASKDIALOGCONFIG()
    config.cbSize = ctypes.sizeof(TASKDIALOGCONFIG)
    config.dwFlags = TDF_ALLOW_DIALOG_CANCELLATION | TDF_SIZE_TO_CONTENT
    config.pszWindowTitle = 'Icon Control'
    config.pszMainIcon = ctypes.c_void_p(TD_INFORMATION_ICON)
    config.pszMainInstruction = headline
    config.pszContent = detail + (f'\r\n\r\n{remaining}' if remaining else '')
    config.cButtons = len(buttons)
    config.pButtons = buttons
    config.nDefaultButton = BUTTON_CANCEL
    _force_foreground()
    button = ctypes.c_int(BUTTON_CANCEL)
    radio = ctypes.c_int(0)
    checked = wintypes.BOOL(0)
    result = library.TaskDialogIndirect(ctypes.byref(config), ctypes.byref(button),
                                        ctypes.byref(radio), ctypes.byref(checked))
    if result != 0:
        raise OSError(result, 'TaskDialogIndirect failed')
    action = {BUTTON_RENEW: 'renew', BUTTON_TRUST: 'trust', BUTTON_REVOKE: 'revoke', BUTTON_QUIT: 'quit', BUTTON_PENDING: 'pending'}.get(button.value, 'close')
    return dict(button=button.value, action=action)


def _choose_record(agents, headline, descriptions, *, auto_single=True, selection_label='选择此会话'):
    """Explicit radio selection for a manually opened window without a request."""
    if not agents or not available():
        return None
    if len(agents) == 1 and auto_single:
        return agents[0]
    library = _common_controls()
    buttons = (TASKDIALOG_BUTTON * 2)(
        TASKDIALOG_BUTTON(BUTTON_GRANT, selection_label),
        TASKDIALOG_BUTTON(BUTTON_CANCEL, '取消'))
    radios = (TASKDIALOG_BUTTON * len(agents))(*[
        TASKDIALOG_BUTTON(300+i, descriptions[i])
        for i, a in enumerate(agents)])
    config = TASKDIALOGCONFIG()
    config.cbSize = ctypes.sizeof(config)
    config.dwFlags = TDF_ALLOW_DIALOG_CANCELLATION | TDF_SIZE_TO_CONTENT | TDF_NO_DEFAULT_RADIO_BUTTON
    config.pszWindowTitle = 'Icon Control'
    config.pszMainInstruction = headline
    config.pszContent = '请选择实际目标，随后将显示完整授权范围。'
    config.cButtons, config.pButtons = len(buttons), buttons
    config.cRadioButtons, config.pRadioButtons = len(radios), radios
    config.nDefaultButton = BUTTON_CANCEL
    config.nDefaultRadioButton = 0
    button, radio, checked = ctypes.c_int(BUTTON_CANCEL), ctypes.c_int(0), wintypes.BOOL(0)
    library.TaskDialogIndirect.argtypes = [
        ctypes.POINTER(TASKDIALOGCONFIG), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(wintypes.BOOL)]
    library.TaskDialogIndirect.restype = ctypes.c_long
    result = library.TaskDialogIndirect(ctypes.byref(config), ctypes.byref(button),
                                        ctypes.byref(radio), ctypes.byref(checked))
    if result != 0:
        raise OSError(result, 'Agent selection failed')
    index = radio.value - 300
    return agents[index] if button.value == BUTTON_GRANT and 0 <= index < len(agents) else None


def choose_agent(agents):
    return _choose_record(agents, '请选择需要授权的实际 Agent',
                          [f"{a.get('label', 'Agent')} · {a['id'][:10]} · PID {a['pid']}" for a in agents])


def choose_application(applications):
    return _choose_record(applications, '尚未确定要操作的应用，请明确选择',
                          [f"{a.get('title', '')} · PID {a['pid']} · {os.path.basename(a['exe'])}" for a in applications],
                          auto_single=False, selection_label='选择此应用')


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
