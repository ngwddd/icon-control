"""One policy boundary for MCP, nested composition and direct Python calls."""
from __future__ import annotations
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import importlib
import inspect
import time
import threading

_current = ContextVar('icon_execution', default=None)
_operation_lock = threading.RLock()
_UNSET = object()

def check(tool, arguments=_UNSET):
    from computer_mcp import permission, control
    task = _current.get()
    if arguments is _UNSET:
        arguments = task.get('arguments') if task and task['tool']==tool else None
    permission.require(tool, arguments)
    authority = permission.status() if task else {}
    if task and (control.status()['generation'] != task['generation'] or
                 (authority.get('session'), authority.get('revision')) != task['revision']):
        raise permission.PermissionDenied('Execution cancelled by takeover or authority change')

@contextmanager
def operation(tool, arguments=None):
    from computer_mcp import permission, control, tool_registry
    previous = _current.get()
    spec = tool_registry.get(tool)
    locked = previous is None and spec is not None and spec.needs_authority(arguments)
    if locked:
        _operation_lock.acquire()
    token = None
    try:
        check(tool, arguments)
        if previous is None:
            authority = permission.status()
            token = _current.set(dict(generation=control.status()['generation'],
                                      revision=(authority.get('session'), authority.get('revision')),
                                      tool=tool, arguments=arguments))
        from computer_mcp.native_mouse import physical_coordinates
        with physical_coordinates():
            yield
    except BaseException:
        from computer_mcp.input_guard import release_all
        release_all()
        raise
    finally:
        if token is not None:
            _current.reset(token)
        if locked:
            _operation_lock.release()

def checkpoint(default_tool, hwnd=None):
    """Recheck a composed operation immediately before a native side effect."""
    check(default_tool, None)
    if hwnd is not None:
        from computer_mcp.capabilities import require_target
        require_target(hwnd=hwnd)

def boundary(tool):
    def decorate(function):
        if getattr(function, '_icon_guarded', False):
            return function
        @wraps(function)
        def guarded(*args, **kwargs):
            bound = inspect.signature(function).bind(*args, **kwargs)
            policy_args = next((bound.arguments[n] for n in ('args','arguments','kwargs')
                                if isinstance(bound.arguments.get(n),dict)), None)
            with operation(tool, policy_args):
                from computer_mcp import capabilities, tool_registry
                spec = tool_registry.get(tool)
                if (spec and set(spec.effects_for(policy_args)) & {'window','window_close'}) or tool in ('ui_invoke','ui_set_text'):
                    hwnd = bound.arguments.get('hwnd') or bound.arguments.get('window_id')
                    if not hwnd and policy_args: hwnd = policy_args.get('hwnd')
                    capabilities.require_target(hwnd=hwnd)
                from computer_mcp.input_guard import MouseController, KeyboardController
                for name, value in list(bound.arguments.items()):
                    if value is None:
                        continue
                    if name in ('mouse', 'mouse_controller') and not isinstance(value, MouseController):
                        bound.arguments[name] = MouseController(value)
                    elif name in ('keyboard', 'keyboard_controller') and not isinstance(value, KeyboardController):
                        bound.arguments[name] = KeyboardController(value)
                    elif name == 'controller':
                        wrapper = MouseController if function.__module__.endswith('.mouse') else KeyboardController
                        if not isinstance(value, wrapper):
                            bound.arguments[name] = wrapper(value)
                return function(*bound.args, **bound.kwargs)
        guarded._icon_guarded = True
        return guarded
    return decorate

def guard_module(module, names):
    for name, tool in names.items():
        function = getattr(module, name, None)
        if callable(function):
            setattr(module, name, boundary(tool)(function))

def sleep(seconds):
    task = _current.get()
    if not task:
        return time.sleep(seconds)
    deadline = time.monotonic() + max(0, seconds)
    while True:
        check(task['tool'])
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.02, remaining))

def install_boundaries():
    """Legacy public APIs share the registry policy, without adding MCP tools."""
    tables = {
        'actions.mouse': {n: ('mouse_move' if n == 'move_mouse' else n) for n in
                          ('click','double_click','triple_click','button_down','button_up','drag','move_mouse')},
        'actions.keyboard': {n: ('type' if n.startswith('type_text') else n.replace('_to_window','')) for n in
                             ('type_text','key_down','key_up','key_press','type_text_to_window',
                              'key_down_to_window','key_up_to_window','key_press_to_window')},
        'actions.window': {n: n for n in ('list_windows','get_window_info','screenshot_window','list_virtual_desktops','switch_to_window','move_window','resize_window','minimize_window',
                             'maximize_window','restore_window','set_window_topmost','close_window',
                             'snap_window_left','snap_window_right','snap_window_top','snap_window_bottom',
                             'switch_virtual_desktop','move_window_to_virtual_desktop')},
        'actions.config': {'set_config':'set_config'},
        'ui_ext': {'ui_tree':'ui_tree','ui_find':'ui_find','ui_click':'ui_click','ui_invoke':'ui_invoke','ui_set_text':'ui_set_text','run_batch':'batch'},
        'ocr_ext': {'ocr_read':'ocr_read','find_text':'find_text','click_text':'click_text'},
        'actions.focused_app': {'get_focused_app':'list_windows'},
        'actions.accessibility_tree': {'get_accessibility_tree':'ui_tree'},
        'macro_ext': {'run_macro':'macro_run','macro_save':'macro_save','_force_foreground':'switch_to_window'},
        'vision_state': {n:n for n in ('click_template','hover_probe','capture_template','set_baseline')},
        'appkit': {'launch':'run_script','activate':'switch_to_window','exit_app':'close_window','close_windows':'close_window'},
        'winutil': {'activate':'switch_to_window','ensure_front':'switch_to_window'},
        'program': {'run':'run_script'},
        'core.screenshot': {'set_capture_config':'capture_config'},
        'live': {'tool_capture':'capture_daemon', 'tool_snapshot':'snapshot',
                 'tool_run_script':'run_script', 'tool_act_until':'act_until',
                 'tool_frame_mark':'frame_mark', 'tool_glyph':'glyph',
                 'tool_record':'record', 'tool_housekeeping':'housekeeping',
                 'tool_servo':'servo', 'tool_navigate':'navigate',
                 'tool_layout_mem':'layout_mem', 'tool_track':'track','tool_trace':'trace'},
    }
    for path, names in tables.items():
        module = importlib.import_module('computer_mcp.' + path)
        guard_module(module, names)
