"""Check authority immediately before every injected event; always allow cleanup."""
from __future__ import annotations
from contextlib import contextmanager
import threading
import weakref
import sys
from pynput.mouse import Controller as RawMouse, Button
from pynput.keyboard import Controller as RawKeyboard, Key, KeyCode
from computer_mcp.execution import check

_controllers = weakref.WeakSet()
_held_controllers = set()
_lock = threading.RLock()
_monitor_thread = None

class InjectedMouse(RawMouse):
    def _position_get(self):
        if sys.platform == 'win32':
            from computer_mcp.native_mouse import cursor_position
            return cursor_position()
        return super()._position_get()

    def _position_set(self, point):
        if sys.platform == 'win32':
            from computer_mcp.native_mouse import move_absolute
            move_absolute(*point)
        else:
            super()._position_set(point)

class UnicodeKey(KeyCode):
    """Marker separating literal text from physical shortcut keys."""


class InjectedKeyboard(RawKeyboard):
    def __init__(self):
        super().__init__()
        self._edit_keys = set()

    def _resolve(self, key):
        if isinstance(key, UnicodeKey):
            return key
        return super()._resolve(key)

    def _handle(self, key, is_press):
        from computer_mcp.native_keyboard import send_unicode, send_key, edit_shortcut, normalized_key_tokens
        if isinstance(key, UnicodeKey):
            send_unicode(key.char, is_press)
            return
        tokens = normalized_key_tokens(key)
        char = next((letter for letter in ('a', 'c', 'x', 'v') if letter in tokens), '')
        if is_press:
            from computer_mcp.native_keyboard import check_clipboard_chord
            modifiers = set()
            for name in ('ctrl', 'shift', 'alt'):
                if getattr(self, name + '_pressed', False):
                    modifiers.add(getattr(Key, name))
            check_clipboard_chord(key, modifiers)
        if not is_press and key in self._edit_keys:
            self._edit_keys.discard(key)
            return
        if is_press and self.ctrl_pressed and not self.shift_pressed and not self.alt_pressed:
            if edit_shortcut(char):
                self._edit_keys.add(key)
                return
        # Special keys and ordinary key actions retain virtual-key semantics.
        parameters = key._parameters(is_press)
        send_key(vk=parameters['wVk'], scan=parameters['wScan'], flags=parameters['dwFlags'])


def _watch_held():
    import time
    while True:
        time.sleep(.02)
        _check_held()

def _check_held():
    from computer_mcp import permission, control, panic
    with _lock:
        pending=list(_held_controllers)
    try:
        for controller in pending:
            with controller._mutex:
                if not controller.held:
                    with _lock:
                        _held_controllers.discard(controller)
                    continue
                state=permission.status(agent_session_id=controller.agent_session)
                revision=(state.get('session'),state.get('revision'),
                          state.get('revocation_generation'))
                generation=control.status()['generation']
                stopped=bool(panic._DEFAULT and panic._DEFAULT.triggered)
                invalid=not state.get('granted') or stopped or controller.authority!=(revision,generation)
            if invalid:
                # Losing a modifier must cancel the remaining input too; merely
                # releasing Ctrl would let the next letter become ordinary text.
                control.note_physical('Held-input authority lost; operation cancelled')
                return
    except Exception:
        control.note_physical('Held-input monitor failed; operation cancelled')

def _retain(controller, tool, *, point=None, hwnd=None):
    global _monitor_thread
    from computer_mcp import permission, capabilities, tool_registry, execution
    state=permission.status()
    stamp = execution.authority_stamp(state)
    why = capabilities.check_scope(state, tool_registry.get(tool), None)
    if not why:
        why = capabilities.check_target(state, point=point, hwnd=hwnd)
    if why:
        raise permission.PermissionDenied(why)
    from computer_mcp import agent_session
    controller.agent_session = agent_session.current()
    controller.authority=stamp
    with _lock:
        _held_controllers.add(controller)
        if _monitor_thread is None or not _monitor_thread.is_alive():
            _monitor_thread=threading.Thread(target=_watch_held,daemon=True,name='icon-held-input-monitor')
            _monitor_thread.start()

def release_all():
    with _lock:
        controllers = list(_controllers)
    for controller in controllers:
        controller.cleanup()

class _Held:
    def _init(self, raw):
        self.raw = raw
        self.held = set()
        self._mutex = threading.RLock()
        with _lock:
            _controllers.add(self)

    def release(self, value):
        # Normal release is an input operation. Only cleanup() may bypass
        # authority, and then only for events recorded as held by this process.
        with self._mutex:
            check(self.up_tool)
            from computer_mcp.capabilities import require_target
            if self.up_tool == 'button_up':
                require_target(point=self.raw.position)
            else:
                require_target(hwnd=getattr(self.raw, 'hwnd', None))
            self.raw.release(value)
            self.held.discard(value)
            if not self.held:
                with _lock:
                    _held_controllers.discard(self)

    def cleanup(self):
        with self._mutex:
            # A destroyed/reused message target no longer owns our held keys.
            # Do not send cleanup events into the replacement process.
            target_exists = getattr(self.raw, 'target_exists', None)
            if target_exists is not None and not target_exists():
                self.held.clear()
            for value in tuple(self.held):
                try:
                    self.raw.release(value)
                    self.held.discard(value)
                except Exception:
                    pass
            if not self.held:
                with _lock:_held_controllers.discard(self)

class MouseController(_Held):
    up_tool = 'button_up'
    def __init__(self, raw=None):
        # Replace the exact legacy pynput implementation as well as the default
        # factory. Fake/custom test controllers remain isolated.
        self._init(InjectedMouse() if raw is None or type(raw) is RawMouse else raw)

    @property
    def position(self):
        return self.raw.position

    @position.setter
    def position(self, point):
        check('mouse_move')
        from computer_mcp.capabilities import require_target
        require_target(point=point)
        self.raw.position = point

    def move(self, dx, dy):
        check('mouse_move')
        from computer_mcp.capabilities import require_target
        x,y = self.raw.position
        require_target(point=(x+dx,y+dy))
        self.raw.move(dx, dy)

    def press(self, button, *, expected_target=None, expected_point=None, expected_hwnd=None):
        with self._mutex:
            check('button_down')
            from computer_mcp.capabilities import require_target
            require_target(point=self.raw.position)
            _retain(self, 'button_down', point=self.raw.position)
            if expected_target is not None:
                import win32gui, win32process
                from computer_mcp import capabilities, permission
                position = tuple(self.raw.position)
                hwnd = win32gui.WindowFromPoint(position)
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if position != expected_point or capabilities.process_record(pid) != expected_target:
                    raise permission.PermissionDenied('Point-click target changed before button-down')
                if expected_hwnd is not None and win32gui.GetAncestor(hwnd, 2) != expected_hwnd:
                    raise permission.PermissionDenied('Point-click top-level window changed before button-down')
                capabilities.require_target(point=position)
            self.held.add(button)
            self.raw.press(button)

    def click(self, button, count=1, *, expected_target=None, expected_point=None, expected_hwnd=None):
        for _ in range(count):
            check('click')
            self.press(button, expected_target=expected_target, expected_point=expected_point, expected_hwnd=expected_hwnd)
            self.release(button)

    def position_for_scroll(self, point):
        check('scroll')
        from computer_mcp.capabilities import require_target
        require_target(point=point)
        self.raw.position = point

    def scroll(self, dx, dy, *, expected_target=None, expected_point=None):
        check('scroll')
        from computer_mcp.capabilities import require_target
        require_target(point=self.raw.position)
        if expected_target is not None:
            import win32gui, win32process
            from computer_mcp import capabilities, permission
            point = tuple(self.raw.position)
            hwnd = win32gui.WindowFromPoint(point)
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if point != expected_point or capabilities.process_record(pid) != expected_target:
                raise permission.PermissionDenied('Scroll target changed before injection')
            require_target(point=point)
        self.raw.scroll(dx, dy)

class KeyboardController(_Held):
    up_tool = 'key_up'
    def __init__(self, raw=None):
        self._init(InjectedKeyboard() if sys.platform == "win32" and (raw is None or type(raw) is RawKeyboard) else (raw if raw is not None else RawKeyboard()))

    def press(self, key):
        with self._mutex:
            check('key_down')
            from computer_mcp.native_keyboard import check_clipboard_chord
            modifiers = set(self.held)
            for name in ('ctrl', 'shift', 'alt'):
                if getattr(self.raw, name + '_pressed', False):
                    modifiers.add(getattr(Key, name))
            check_clipboard_chord(key, modifiers)
            from computer_mcp.capabilities import require_target
            require_target(hwnd=getattr(self.raw,'hwnd',None))
            _retain(self, 'key_down', hwnd=getattr(self.raw,'hwnd',None))
            self.held.add(key)
            self.raw.press(key)

    def type(self, text):
        if not isinstance(text, str):
            raise TypeError('Text must be a string')
        # Validate the whole string before emitting a partial invalid surrogate.
        text.encode('utf-16-le')
        injected = 0
        for character in text:
            check('type')
            key = UnicodeKey.from_char(character) if isinstance(self.raw, InjectedKeyboard) else character
            try:
                self.press(key)
                self.release(key)
                injected += 1
            except BaseException:
                self.cleanup()
                raise
        return injected

    @contextmanager
    def pressed(self, *keys):
        try:
            for key in keys:
                self.press(key)
            yield
        finally:
            for key in reversed(keys):
                if key in self.held:
                    self.release(key)
