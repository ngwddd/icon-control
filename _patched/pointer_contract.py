"""One fail-closed contract for UIA/OCR/template clicks; never retry input.

Window identity is captured before observation. The existing guarded controller
rechecks authority, pointer position, process and top-level HWND at button-down.
These checks reduce, but cannot eliminate, the OS scheduling race.
"""
from __future__ import annotations

from dataclasses import dataclass
import inspect

from computer_mcp import execution


@dataclass(frozen=True)
class WindowBinding:
    hwnd: int
    process: dict
    rect: tuple


def bind_window(hwnd: int | None = None, *, point=None) -> WindowBinding:
    import win32gui
    import win32process
    from computer_mcp import capabilities
    from computer_mcp.core.argument_error import ArgumentError

    window = hwnd or (win32gui.WindowFromPoint(tuple(point)) if point is not None
                      else win32gui.GetForegroundWindow())
    if not window or not win32gui.IsWindow(window):
        raise ArgumentError('No live target window', code='target_unverified')
    window = int(win32gui.GetAncestor(window, 2) or window)
    _, pid = win32process.GetWindowThreadProcessId(window)
    record = capabilities.process_record(pid)
    rect = tuple(win32gui.GetWindowRect(window))
    # Refuse a handle replaced while its identity was being read.
    if (not win32gui.IsWindow(window)
            or win32process.GetWindowThreadProcessId(window)[1] != pid):
        raise ArgumentError('Target changed during resolution', code='target_changed')
    return WindowBinding(window, record, rect)


def _validate(binding, point):
    from computer_mcp import capabilities
    from computer_mcp.core.argument_error import ArgumentError
    import win32gui
    import win32process

    if binding:
        current = bind_window(binding.hwnd)
        if current != binding:
            raise ArgumentError('Target identity or geometry changed; observe again',
                                code='target_changed')
        under = win32gui.WindowFromPoint(point)
        _, pid = win32process.GetWindowThreadProcessId(under)
        if (int(win32gui.GetAncestor(under, 2) or under) != binding.hwnd
                or capabilities.process_record(pid) != binding.process):
            raise ArgumentError('Target point is obscured or was replaced',
                                code='target_occluded')


def click_at(mouse, point, button, *, binding=None, move_delay=0.06, settle_ms=0,
             hold_ms=0):
    """Return execution evidence even when release/settle raises after injection.

An exception after entering click cannot prove no event was sent. Report unknown
execution, clean up only held inputs, and require observation before any retry.
"""
    from computer_mcp.core.argument_error import ArgumentError
    from computer_mcp.permission import PermissionDenied

    point = tuple(map(int, point))
    attempted = completed = False
    try:
        from computer_mcp.input_guard import MouseController
        if not isinstance(mouse, MouseController):
            mouse = MouseController(mouse)
        binding = binding or bind_window(point=point)
        constraints = dict(expected_point=point, expected_hwnd=binding.hwnd,
                           expected_target=binding.process)
        try:
            if hold_ms:
                inspect.signature(mouse.press).bind(button, **constraints)
            else:
                inspect.signature(mouse.click).bind(button, 1, **constraints)
        except (TypeError, ValueError):
            return dict(ok=False, success=False, outcome='refused',
                        code='pointer_contract_unsupported', action_executed=False,
                        error='Mouse controller does not support constrained clicks')
        _validate(binding, point)
        mouse.position = point
        execution.sleep(max(0, move_delay))
        _validate(binding, point)
        attempted = True
        if hold_ms:
            mouse.press(button, **constraints)
            completed = True  # At least button-down definitely occurred.
            execution.sleep(max(0, hold_ms) / 1000.0)
            mouse.release(button)
        else:
            mouse.click(button, 1, **constraints)
            completed = True
        execution.sleep(max(0, settle_ms) / 1000.0)
    except Exception as exc:
        cleanup_failed = False
        if attempted:
            try:
                mouse.cleanup()
                cleanup_failed = bool(getattr(mouse, 'held', ()))
            except Exception:
                cleanup_failed = True
        refusal = isinstance(exc, (ArgumentError, PermissionDenied)) and not attempted
        cancelled = isinstance(exc, PermissionDenied)
        return dict(ok=False, success=False,
                    outcome=('refused' if refusal else 'cancelled' if cancelled else 'failed'),
                    code=getattr(exc, 'code', 'execution_cancelled' if cancelled else 'pointer_action_failed'),
                    error='Constrained click did not complete; observe before retrying',
                    error_type=type(exc).__name__,
                    action_executed=True if completed else None if attempted else False,
                    input_attempted=attempted, cleanup_failed=cleanup_failed,
                    verified=False, retry_safe=not attempted,
                    next_action='Observe the target and check held input; do not automatically repeat the click')
    return dict(outcome='executed_unverified', status='executed_unverified',
                action_executed=True, verified=False, verification_method='not_performed',
                retry_safe=False,
                next_action='Observe the intended control or application result before continuing')
