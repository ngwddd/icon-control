"""Check authority immediately before every injected event; always allow cleanup."""
from __future__ import annotations
from contextlib import contextmanager
import threading
import weakref
from pynput.mouse import Controller as RawMouse, Button
from pynput.keyboard import Controller as RawKeyboard, Key, KeyCode
from computer_mcp.execution import check

_controllers = weakref.WeakSet()
_held_controllers = set()
_lock = threading.RLock()
_monitor_thread = None

def _watch_held():
    import time
    from computer_mcp import permission, control, panic
    while True:
        time.sleep(.02)
        with _lock:
            pending=list(_held_controllers)
        if not pending:
            continue
        try:
            state=permission.status()
            revision=(state.get('session'),state.get('revision'))
            generation=control.status()['generation']
            stopped=bool(panic._DEFAULT and panic._DEFAULT.triggered)
            for controller in pending:
                if not state.get('granted') or stopped or controller.authority!=(revision,generation):
                    controller.cleanup()
        except Exception:
            release_all()

def _retain(controller):
    global _monitor_thread
    from computer_mcp import permission, control
    state=permission.status()
    controller.authority=((state.get('session'),state.get('revision')),control.status()['generation'])
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
        # Releasing something this process pressed is emergency cleanup,
        # never a way to inject an otherwise unauthorised key-up event.
        with self._mutex:
            if value not in self.held:
                check(self.up_tool)
            self.raw.release(value)
            self.held.discard(value)
            if not self.held:
                with _lock:
                    _held_controllers.discard(self)

    def cleanup(self):
        with self._mutex:
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
        self._init(raw if raw is not None else RawMouse())

    @property
    def position(self):
        return self.raw.position

    @position.setter
    def position(self, point):
        check('mouse_move')
        self.raw.position = point

    def move(self, dx, dy):
        check('mouse_move')
        self.raw.move(dx, dy)

    def press(self, button):
        with self._mutex:
            check('button_down')
            self.held.add(button)
            _retain(self)
            self.raw.press(button)

    def click(self, button, count=1):
        for _ in range(count):
            check('click')
            self.press(button)
            self.release(button)

    def scroll(self, dx, dy):
        check('mouse_move')
        self.raw.scroll(dx, dy)

class KeyboardController(_Held):
    up_tool = 'key_up'
    def __init__(self, raw=None):
        self._init(raw if raw is not None else RawKeyboard())

    def press(self, key):
        with self._mutex:
            check('key_down')
            self.held.add(key)
            _retain(self)
            self.raw.press(key)

    def type(self, text):
        for character in text:
            check('type')
            self.press(character)
            self.release(character)

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
