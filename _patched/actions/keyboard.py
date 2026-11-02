"""Keyboard actions."""

from typing import Any

from computer_mcp.input_guard import KeyboardController as Controller, KeyCode

from computer_mcp.core.platform import IS_DARWIN, IS_LINUX, IS_WINDOWS
from computer_mcp.core.utils import key_from_string


def type_text(text: str, controller: Controller | None = None) -> dict[str, Any]:
    """Type the specified text.
    
    Args:
        text: Text to type
        controller: Keyboard controller instance (creates one if None)
    
    Returns:
        Dictionary with action result
    """
    if controller is None:
        controller = Controller()
    
    controller.type(text)
    return {"success": True, "action": "type", "text": text}


def key_down(key: str, controller: Controller | None = None) -> dict[str, Any]:
    """Press and hold a key.
    
    Args:
        key: Key to press (e.g., 'ctrl', 'a', 'space')
        controller: Keyboard controller instance (creates one if None)
    
    Returns:
        Dictionary with action result
    """
    if controller is None:
        controller = Controller()
    
    key_obj = key_from_string(key)
    controller.press(key_obj)
    return {"success": True, "action": "key_down", "key": key}


def key_up(key: str, controller: Controller | None = None) -> dict[str, Any]:
    """Release a key.
    
    Args:
        key: Key to release (e.g., 'ctrl', 'a', 'space')
        controller: Keyboard controller instance (creates one if None)
    
    Returns:
        Dictionary with action result
    """
    if controller is None:
        controller = Controller()
    
    key_obj = key_from_string(key)
    controller.release(key_obj)
    return {"success": True, "action": "key_up", "key": key}


def key_press(key: str, controller: Controller | None = None) -> dict[str, Any]:
    """Press and release a key (convenience method).
    
    Args:
        key: Key to press and release (e.g., 'ctrl', 'a', 'space')
        controller: Keyboard controller instance (creates one if None)
    
    Returns:
        Dictionary with action result
    """
    if controller is None:
        controller = Controller()
    
    key_obj = key_from_string(key)
    controller.press(key_obj)
    controller.release(key_obj)
    return {"success": True, "action": "key_press", "key": key}


# Window-targeted keyboard functions
if IS_WINDOWS:
    import threading
    _window_controllers = {}
    _window_lock = threading.RLock()

    class _MessageKeyboard:
        """WM_CHAR for text; tracked WM_KEYDOWN/UP for held keys."""
        def __init__(self, hwnd):
            self.hwnd = hwnd

        def _vk(self, key):
            import win32api
            from pynput.keyboard import Key
            if isinstance(key, Key):
                return key.value.vk
            if getattr(key, 'vk', None) is not None:
                return key.vk
            value = win32api.VkKeyScan(key.char)
            if value == -1:
                raise ValueError('Character has no virtual key; use type_text_to_window')
            return value & 0xff

        def press(self, key):
            import win32gui, win32con
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYDOWN, self._vk(key), 0)

        def release(self, key):
            import win32gui, win32con
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYUP, self._vk(key), 0)

    def _window_controller(hwnd):
        import win32gui
        if not win32gui.IsWindow(hwnd):
            raise ValueError('Invalid window handle')
        with _window_lock:
            if hwnd not in _window_controllers:
                # Inactive cached controllers may be discarded. Held ones stay
                # alive in input_guard until emergency cleanup releases them.
                if len(_window_controllers) >= 64:
                    for handle, controller in list(_window_controllers.items()):
                        if not controller.held:
                            del _window_controllers[handle]
                _window_controllers[hwnd] = Controller(_MessageKeyboard(hwnd))
            return _window_controllers[hwnd]

    def type_text_to_window(text: str, hwnd: int) -> dict[str, Any]:
        """Type Unicode text, checking each posted character, never silently skipping it."""
        try:
            import win32gui, win32con
            from pynput.keyboard import Key
            from computer_mcp.execution import check
            controller = _window_controller(hwnd)
            for char in text:
                check('type')
                if char == '\n':
                    controller.press(Key.enter)
                    controller.release(Key.enter)
                else:
                    # WM_CHAR expects UTF-16 code units on Windows.
                    units = char.encode('utf-16-le')
                    for offset in range(0, len(units), 2):
                        check('type')
                        win32gui.PostMessage(hwnd, win32con.WM_CHAR,
                                             int.from_bytes(units[offset:offset+2], 'little'), 0)
            return {"success": True, "action": "type", "text": text, "hwnd": hwnd}
        except Exception as exc:
            return {"error": f"Failed to type to window: {exc}"}

    def key_down_to_window(key: str, hwnd: int) -> dict[str, Any]:
        try:
            _window_controller(hwnd).press(key_from_string(key))
            return {"success": True, "action": "key_down", "key": key, "hwnd": hwnd}
        except Exception as exc:
            return {"error": f"Failed to press key to window: {exc}"}

    def key_up_to_window(key: str, hwnd: int) -> dict[str, Any]:
        try:
            _window_controller(hwnd).release(key_from_string(key))
            return {"success": True, "action": "key_up", "key": key, "hwnd": hwnd}
        except Exception as exc:
            return {"error": f"Failed to release key to window: {exc}"}

    def key_press_to_window(key: str, hwnd: int) -> dict[str, Any]:
        result = key_down_to_window(key, hwnd)
        if "error" in result:
            return result
        result = key_up_to_window(key, hwnd)
        if "error" in result:
            return result
        return {"success": True, "action": "key_press", "key": key, "hwnd": hwnd}

elif IS_DARWIN:
    def type_text_to_window(text: str, window_id: int) -> dict[str, Any]:
        """Type text to a specific window on macOS."""
        try:
            import subprocess
            
            # Escape text for AppleScript
            escaped_text = text.replace('\\', '\\\\').replace('"', '\\"')
            
            script = f'''
            tell application "System Events"
                repeat with proc in application processes
                    try
                        set targetWindow to window id {window_id} of proc
                        set frontmost of proc to true
                        set frontmost of targetWindow to true
                        keystroke "{escaped_text}"
                        exit repeat
                    end try
                end repeat
            end tell
            '''
            
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=5,
                check=False
            )
            
            if result.returncode == 0:
                return {"success": True, "action": "type", "text": text, "window_id": window_id}
            else:
                return {"error": f"Failed to type to window: {result.stderr}"}
        except Exception as e:
            return {"error": f"Failed to type to window: {str(e)}"}
    
    def key_down_to_window(key: str, window_id: int) -> dict[str, Any]:
        """Press a key down to a specific window on macOS."""
        try:
            import subprocess
            
            # Map key names to AppleScript key codes
            key_map = {
                "enter": "return",
                "return": "return",
                "tab": "tab",
                "space": "space",
                "backspace": "delete",
                "delete": "delete",
                "esc": "escape",
                "escape": "escape",
                "up": "up arrow",
                "down": "down arrow",
                "left": "left arrow",
                "right": "right arrow",
            }
            
            key_name = key_map.get(key.lower(), key.lower())
            # Quote key name if it contains spaces (like "up arrow")
            if " " in key_name:
                key_name_script = f'"{key_name}"'
            else:
                key_name_script = key_name
            
            script = f'''
            tell application "System Events"
                repeat with proc in application processes
                    try
                        set targetWindow to window id {window_id} of proc
                        set frontmost of proc to true
                        set frontmost of targetWindow to true
                        key down {key_name_script}
                        exit repeat
                    end try
                end repeat
            end tell
            '''
            
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=2,
                check=False
            )
            
            if result.returncode == 0:
                return {"success": True, "action": "key_down", "key": key, "window_id": window_id}
            else:
                return {"error": f"Failed to press key to window: {result.stderr}"}
        except Exception as e:
            return {"error": f"Failed to press key to window: {str(e)}"}
    
    def key_up_to_window(key: str, window_id: int) -> dict[str, Any]:
        """Release a key to a specific window on macOS."""
        try:
            import subprocess
            
            # Map key names to AppleScript key codes
            key_map = {
                "enter": "return",
                "return": "return",
                "tab": "tab",
                "space": "space",
                "backspace": "delete",
                "delete": "delete",
                "esc": "escape",
                "escape": "escape",
                "up": "up arrow",
                "down": "down arrow",
                "left": "left arrow",
                "right": "right arrow",
            }
            
            key_name = key_map.get(key.lower(), key.lower())
            # Quote key name if it contains spaces (like "up arrow")
            if " " in key_name:
                key_name_script = f'"{key_name}"'
            else:
                key_name_script = key_name
            
            script = f'''
            tell application "System Events"
                repeat with proc in application processes
                    try
                        set targetWindow to window id {window_id} of proc
                        set frontmost of proc to true
                        set frontmost of targetWindow to true
                        key up {key_name_script}
                        exit repeat
                    end try
                end repeat
            end tell
            '''
            
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=2,
                check=False
            )
            
            if result.returncode == 0:
                return {"success": True, "action": "key_up", "key": key, "window_id": window_id}
            else:
                return {"error": f"Failed to release key to window: {result.stderr}"}
        except Exception as e:
            return {"error": f"Failed to release key to window: {str(e)}"}
    
    def key_press_to_window(key: str, window_id: int) -> dict[str, Any]:
        """Press and release a key to a specific window on macOS."""
        try:
            import subprocess
            
            # Map key names to AppleScript key codes
            key_map = {
                "enter": "return",
                "return": "return",
                "tab": "tab",
                "space": "space",
                "backspace": "delete",
                "delete": "delete",
                "esc": "escape",
                "escape": "escape",
                "up": "up arrow",
                "down": "down arrow",
                "left": "left arrow",
                "right": "right arrow",
            }
            
            key_name = key_map.get(key.lower(), key.lower())
            # Quote key name if it contains spaces (like "up arrow")
            if " " in key_name:
                key_name_script = f'"{key_name}"'
            else:
                key_name_script = key_name
            
            script = f'''
            tell application "System Events"
                repeat with proc in application processes
                    try
                        set targetWindow to window id {window_id} of proc
                        set frontmost of proc to true
                        set frontmost of targetWindow to true
                        keystroke {key_name_script}
                        exit repeat
                    end try
                end repeat
            end tell
            '''
            
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=2,
                check=False
            )
            
            if result.returncode == 0:
                return {"success": True, "action": "key_press", "key": key, "window_id": window_id}
            else:
                return {"error": f"Failed to press key to window: {result.stderr}"}
        except Exception as e:
            return {"error": f"Failed to press key to window: {str(e)}"}

elif IS_LINUX:
    def type_text_to_window(text: str, window_id: int) -> dict[str, Any]:
        """Type text to a specific window on Linux."""
        try:
            import subprocess
            
            # Activate window first
            subprocess.run(
                ["xdotool", "windowactivate", str(window_id)],
                capture_output=True,
                timeout=1,
                check=False
            )
            
            # Type text
            subprocess.run(
                ["xdotool", "type", "--window", str(window_id), text],
                capture_output=True,
                timeout=5,
                check=False
            )
            
            return {"success": True, "action": "type", "text": text, "window_id": window_id}
        except FileNotFoundError:
            return {"error": "xdotool not installed", "note": "Install xdotool: sudo apt install xdotool"}
        except Exception as e:
            return {"error": f"Failed to type to window: {str(e)}"}
    
    def key_down_to_window(key: str, window_id: int) -> dict[str, Any]:
        """Press a key down to a specific window on Linux."""
        try:
            import subprocess
            
            # Activate window first
            subprocess.run(
                ["xdotool", "windowactivate", str(window_id)],
                capture_output=True,
                timeout=1,
                check=False
            )
            
            # Key down
            subprocess.run(
                ["xdotool", "keydown", "--window", str(window_id), key],
                capture_output=True,
                timeout=1,
                check=False
            )
            
            return {"success": True, "action": "key_down", "key": key, "window_id": window_id}
        except FileNotFoundError:
            return {"error": "xdotool not installed", "note": "Install xdotool: sudo apt install xdotool"}
        except Exception as e:
            return {"error": f"Failed to press key to window: {str(e)}"}
    
    def key_up_to_window(key: str, window_id: int) -> dict[str, Any]:
        """Release a key to a specific window on Linux."""
        try:
            import subprocess
            
            # Activate window first
            subprocess.run(
                ["xdotool", "windowactivate", str(window_id)],
                capture_output=True,
                timeout=1,
                check=False
            )
            
            # Key up
            subprocess.run(
                ["xdotool", "keyup", "--window", str(window_id), key],
                capture_output=True,
                timeout=1,
                check=False
            )
            
            return {"success": True, "action": "key_up", "key": key, "window_id": window_id}
        except FileNotFoundError:
            return {"error": "xdotool not installed", "note": "Install xdotool: sudo apt install xdotool"}
        except Exception as e:
            return {"error": f"Failed to release key to window: {str(e)}"}
    
    def key_press_to_window(key: str, window_id: int) -> dict[str, Any]:
        """Press and release a key to a specific window on Linux."""
        try:
            import subprocess
            
            # Activate window first
            subprocess.run(
                ["xdotool", "windowactivate", str(window_id)],
                capture_output=True,
                timeout=1,
                check=False
            )
            
            # Key press
            subprocess.run(
                ["xdotool", "key", "--window", str(window_id), key],
                capture_output=True,
                timeout=1,
                check=False
            )
            
            return {"success": True, "action": "key_press", "key": key, "window_id": window_id}
        except FileNotFoundError:
            return {"error": "xdotool not installed", "note": "Install xdotool: sudo apt install xdotool"}
        except Exception as e:
            return {"error": f"Failed to press key to window: {str(e)}"}

else:
    # Unsupported platform
    def type_text_to_window(text: str, window_id: int) -> dict[str, Any]:
        import platform
        return {"error": f"Window keyboard targeting not supported on {platform.system()}"}
    
    def key_down_to_window(key: str, window_id: int) -> dict[str, Any]:
        import platform
        return {"error": f"Window keyboard targeting not supported on {platform.system()}"}
    
    def key_up_to_window(key: str, window_id: int) -> dict[str, Any]:
        import platform
        return {"error": f"Window keyboard targeting not supported on {platform.system()}"}
    
    def key_press_to_window(key: str, window_id: int) -> dict[str, Any]:
        import platform
        return {"error": f"Window keyboard targeting not supported on {platform.system()}"}

