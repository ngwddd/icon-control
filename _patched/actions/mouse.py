"""Mouse actions."""

import time
from typing import Any

from computer_mcp.input_guard import Button, MouseController as Controller

from computer_mcp.core.utils import button_from_string


def click(button: str = "left", controller: Controller | None = None, *, x: float | None = None, y: float | None = None, expected_hwnd: int | None = None) -> dict[str, Any]:
    """Perform a mouse click.
    
    Args:
        button: Mouse button ("left", "right", "middle")
        controller: Mouse controller instance (creates one if None)
    
    Returns:
        Dictionary with action result
    """
    if controller is None:
        controller = Controller()
    
    import math
    if (x is None) != (y is None):
        raise ValueError('click requires both x and y, or neither')
    if expected_hwnd is not None and x is None:
        raise ValueError('A window-bound click requires explicit x/y coordinates')
    target = None
    if x is not None:
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (x, y)):
            raise ValueError('click coordinates must be finite numbers')
        import win32gui, win32process
        from computer_mcp import capabilities
        point = (int(x), int(y))
        hwnd = win32gui.WindowFromPoint(point)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        target = capabilities.process_record(pid)
        if expected_hwnd is not None and win32gui.GetAncestor(hwnd, 2) != expected_hwnd:
            raise ValueError('Point is outside the expected top-level window')
        capabilities.require_target(point=point)
        controller.position = point
        current_hwnd = win32gui.WindowFromPoint(point)
        _, current_pid = win32process.GetWindowThreadProcessId(current_hwnd)
        if capabilities.process_record(current_pid) != target or tuple(controller.position) != point:
            raise ValueError('Target changed while positioning the pointer')
        capabilities.require_target(point=point)
    btn = button_from_string(button)
    if target is None:
        controller.click(btn)
    else:
        controller.click(btn, expected_target=target, expected_point=point, expected_hwnd=expected_hwnd)
    return {"success": True, "action": "click", "button": button,
            "status": "executed_unverified", "verified": False,
            "verification_method": "not_performed",
            "next_action": "Observe the intended page or control after this click; process identity does not prove navigation succeeded.",
            **({"x": int(x), "y": int(y)} if x is not None else {})}


def double_click(button: str = "left", controller: Controller | None = None) -> dict[str, Any]:
    """Perform a double mouse click.
    
    Args:
        button: Mouse button ("left", "right", "middle")
        controller: Mouse controller instance (creates one if None)
    
    Returns:
        Dictionary with action result
    """
    if controller is None:
        controller = Controller()
    
    btn = button_from_string(button)
    controller.click(btn, 2)
    return {"success": True, "action": "double_click", "button": button}


def triple_click(button: str = "left", controller: Controller | None = None) -> dict[str, Any]:
    """Perform a triple mouse click.
    
    Args:
        button: Mouse button ("left", "right", "middle")
        controller: Mouse controller instance (creates one if None)
    
    Returns:
        Dictionary with action result
    """
    if controller is None:
        controller = Controller()
    
    btn = button_from_string(button)
    controller.click(btn, 3)
    return {"success": True, "action": "triple_click", "button": button}


def button_down(button: str = "left", controller: Controller | None = None) -> dict[str, Any]:
    """Press and hold a mouse button.
    
    Args:
        button: Mouse button ("left", "right", "middle")
        controller: Mouse controller instance (creates one if None)
    
    Returns:
        Dictionary with action result
    """
    if controller is None:
        controller = Controller()
    
    btn = button_from_string(button)
    controller.press(btn)
    return {"success": True, "action": "button_down", "button": button}


def button_up(button: str = "left", controller: Controller | None = None) -> dict[str, Any]:
    """Release a mouse button.
    
    Args:
        button: Mouse button ("left", "right", "middle")
        controller: Mouse controller instance (creates one if None)
    
    Returns:
        Dictionary with action result
    """
    if controller is None:
        controller = Controller()
    
    btn = button_from_string(button)
    controller.release(btn)
    return {"success": True, "action": "button_up", "button": button}


def drag(start: dict[str, int], end: dict[str, int], button: str = "left", controller: Controller | None = None) -> dict[str, Any]:
    """Drag mouse from start to end position.
    
    Args:
        start: Start position with "x" and "y" keys
        end: End position with "x" and "y" keys
        button: Mouse button to use ("left", "right", "middle")
        controller: Mouse controller instance (creates one if None)
    
    Returns:
        Dictionary with action result
    """
    if controller is None:
        controller = Controller()
    
    btn = button_from_string(button)
    
    # Move to start, press button, move to end, release button
    controller.position = (start["x"], start["y"])
    controller.press(btn)
    time.sleep(0.01)  # Small delay
    controller.position = (end["x"], end["y"])
    time.sleep(0.01)
    controller.release(btn)
    
    return {"success": True, "action": "drag", "start": start, "end": end, "button": button}


def move_mouse(x: int, y: int, controller: Controller | None = None) -> dict[str, Any]:
    """Move the mouse cursor to specified coordinates.
    
    Args:
        x: X coordinate
        y: Y coordinate
        controller: Mouse controller instance (creates one if None)
    
    Returns:
        Dictionary with action result
    """
    if controller is None:
        controller = Controller()
    
    controller.position = (x, y)
    return {"success": True, "action": "mouse_move", "x": x, "y": y}



def scroll(dy: int, dx: int = 0, controller: Controller | None = None, *, x=None, y=None):
    """Scroll wheel steps: positive dy up, negative down; dx positive right.

    A single call pins the point's process before movement and rechecks it at
    injection. Sending wheel events does not prove that content moved.
    """
    import math
    if any(isinstance(v, bool) or not isinstance(v, int) or abs(v) > 100 for v in (dx, dy)):
        raise ValueError('scroll dx/dy must be integer wheel steps in [-100, 100]')
    if dx == 0 and dy == 0:
        raise ValueError('scroll requires a nonzero delta')
    if (x is None) != (y is None):
        raise ValueError('scroll requires both x and y, or neither')
    controller = controller or Controller()
    if x is None:
        point = tuple(controller.position)
    else:
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (x, y)):
            raise ValueError('scroll coordinates must be finite numbers')
        point = (int(x), int(y))
    import win32gui, win32process
    from computer_mcp import capabilities
    hwnd = win32gui.WindowFromPoint(point)
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    target = capabilities.process_record(pid)
    capabilities.require_target(point=point)
    if x is not None:
        controller.position_for_scroll(point)
    controller.scroll(dx, dy, expected_target=target, expected_point=point)
    return dict(success=True, action='scroll', x=point[0], y=point[1], dx=dx, dy=dy,
                status='executed_unverified', verified=False, verification_method='not_performed',
                next_action='Compare the target content before and after scrolling; a wheel event alone does not prove movement.')
