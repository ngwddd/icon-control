"""One policy boundary for MCP, nested composition and direct Python calls."""
from __future__ import annotations
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import importlib
import inspect
import time

_current = ContextVar('icon_execution', default=None)

def check(tool):
    from computer_mcp import permission, control
    permission.require(tool)
    task = _current.get()
    authority = permission.status() if task else {}
    if task and (control.status()['generation'] != task['generation'] or
                 (authority.get('session'), authority.get('revision')) != task['revision']):
        raise permission.PermissionDenied('Execution cancelled by takeover or authority change')

@contextmanager
def operation(tool):
    from computer_mcp import permission, control
    check(tool)
    previous = _current.get()
    token = None
    if previous is None:
        authority = permission.status()
        token = _current.set(dict(generation=control.status()['generation'],
                                  revision=(authority.get('session'), authority.get('revision')), tool=tool))
    try:
        yield
    except BaseException:
        from computer_mcp.input_guard import release_all
        release_all()
        raise
    finally:
        if token is not None:
            _current.reset(token)

def boundary(tool):
    def decorate(function):
        if getattr(function, '_icon_guarded', False):
            return function
        @wraps(function)
        def guarded(*args, **kwargs):
            with operation(tool):
                bound = inspect.signature(function).bind(*args, **kwargs)
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
        'actions.window': {n: n for n in ('switch_to_window','move_window','resize_window','minimize_window',
                             'maximize_window','restore_window','set_window_topmost','close_window',
                             'snap_window_left','snap_window_right','snap_window_top','snap_window_bottom',
                             'switch_virtual_desktop','move_window_to_virtual_desktop')},
        'actions.config': {'set_config':'set_config'},
        'ui_ext': {'ui_click':'ui_click','ui_invoke':'ui_invoke','ui_set_text':'ui_set_text','run_batch':'batch'},
        'ocr_ext': {'click_text':'click_text'},
        'macro_ext': {'run_macro':'macro_run','macro_save':'macro_save','_force_foreground':'switch_to_window'},
        'vision_state': {n:n for n in ('click_template','hover_probe','capture_template','set_baseline')},
        'appkit': {'launch':'run_script','activate':'switch_to_window','exit_app':'close_window','close_windows':'close_window'},
        'winutil': {'activate':'switch_to_window','ensure_front':'switch_to_window'},
        'program': {'run':'run_script'},
    }
    for path, names in tables.items():
        module = importlib.import_module('computer_mcp.' + path)
        guard_module(module, names)
