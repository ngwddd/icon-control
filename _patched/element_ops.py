"""Element state, available actions and pattern-based execution (v1.4.1).

A UIA control advertises what it can do through Control Patterns. Clicking a
coordinate works, but `invoke` / `set_value` / `toggle` / `select` do not depend on
the pixel the cursor happens to land on, and they work for a control that is
partially covered. Everything here degrades quietly: if a pattern is missing we
report `supported=False` rather than pretending.
"""
from __future__ import annotations

from typing import Any


def _obj(hwnd: int, path: str):
    from computer_mcp import ui_ext

    getter = getattr(ui_ext, '_control_obj_at_path', None)
    if getter is None:                                  # older build
        raise RuntimeError('UI Automation helpers are unavailable')
    obj = getter(hwnd, path)
    if obj is None:
        raise LookupError(f'no control at path {path!r}')
    return obj


def _safe(function, *args, **kwargs) -> Any:
    try:
        return function(*args, **kwargs)
    except Exception:                                   # noqa: BLE001
        return None


def _pattern(obj, name: str):
    getter = getattr(obj, f'Get{name}Pattern', None)
    if getter is None:
        return None
    pattern = _safe(getter)
    return pattern


def read_state(hwnd: int, path: str) -> dict:
    """What the control itself says about its state."""
    obj = _obj(hwnd, path)
    rect = _safe(lambda: obj.BoundingRectangle)
    state = dict(
        name=(_safe(lambda: obj.Name) or '').strip(),
        type=_safe(lambda: obj.ControlTypeName) or '',
        enabled=_safe(lambda: bool(obj.IsEnabled)),
        offscreen=_safe(lambda: bool(obj.IsOffscreen)),
        focusable=_safe(lambda: bool(obj.IsKeyboardFocusable)),
        focused=_safe(lambda: bool(obj.HasKeyboardFocus)),
        value=None, toggle=None, selected=None, expanded=None,
        supported={},
    )
    if rect is not None:
        state['bounds'] = dict(x=int(rect.left), y=int(rect.top),
                               w=int(rect.width()), h=int(rect.height()))

    value_pattern = _pattern(obj, 'Value')
    if value_pattern is not None:
        state['supported']['value'] = True
        state['value'] = _safe(lambda: value_pattern.Value)
        state['read_only'] = _safe(lambda: bool(value_pattern.IsReadOnly))

    toggle_pattern = _pattern(obj, 'Toggle')
    if toggle_pattern is not None:
        state['supported']['toggle'] = True
        raw = _safe(lambda: toggle_pattern.ToggleState)
        state['toggle'] = {0: 'off', 1: 'on', 2: 'indeterminate'}.get(raw, raw)

    selection = _pattern(obj, 'SelectionItem')
    if selection is not None:
        state['supported']['select'] = True
        state['selected'] = _safe(lambda: bool(selection.IsSelected))

    expand = _pattern(obj, 'ExpandCollapse')
    if expand is not None:
        state['supported']['expand'] = True
        state['expanded'] = _safe(lambda: expand.ExpandCollapseState)

    state['supported'].update(invoke=_pattern(obj, 'Invoke') is not None,
                              clickable=True,
                              scroll_item=_pattern(obj, 'ScrollItem') is not None)
    return state


def perform(hwnd: int, path: str, action: str, value: str | None = None,
            mouse=None) -> dict:
    """Run one action against the control, preferring its own patterns."""
    obj = _obj(hwnd, path)
    state = read_state(hwnd, path)
    chosen = action
    if action in ('auto', '', None):
        if state['supported'].get('invoke'):
            chosen = 'invoke'
        elif state['supported'].get('value') and not state.get('read_only'):
            chosen = 'set_value' if value is not None else 'focus'
        elif state['supported'].get('toggle'):
            chosen = 'toggle'
        elif state['supported'].get('select'):
            chosen = 'select'
        else:
            chosen = 'click'

    def failed(reason: str, detail: object = None) -> dict:
        out = dict(ok=False, action=chosen, error=reason)
        if detail is not None:
            out['detail'] = f'{type(detail).__name__}: {detail}'
        return out

    if chosen == 'invoke':
        pattern = _pattern(obj, 'Invoke')
        if pattern is None:
            return failed('control has no Invoke pattern')
        try:
            pattern.Invoke()
        except Exception as exc:                        # noqa: BLE001
            return failed('Invoke failed', exc)
        return dict(ok=True, action='invoke', method='uia')

    if chosen == 'set_value':
        pattern = _pattern(obj, 'Value')
        if pattern is None:
            return failed('control has no Value pattern')
        if value is None:
            return failed('set_value needs a value')
        if _safe(lambda: bool(pattern.IsReadOnly)):
            return failed('control is read-only')
        try:
            setter = getattr(pattern, 'SetValue', None)
            if callable(setter):
                setter(str(value))
            else:                       # older bindings expose only the property
                pattern.Value = str(value)
        except Exception as exc:                        # noqa: BLE001
            return failed('SetValue failed', exc)
        return dict(ok=True, action='set_value', method='uia', value=str(value))

    if chosen == 'toggle':
        pattern = _pattern(obj, 'Toggle')
        if pattern is None:
            return failed('control has no Toggle pattern')
        try:
            pattern.Toggle()
        except Exception as exc:                        # noqa: BLE001
            return failed('Toggle failed', exc)
        return dict(ok=True, action='toggle', method='uia')

    if chosen == 'select':
        pattern = _pattern(obj, 'SelectionItem')
        if pattern is None:
            return failed('control has no SelectionItem pattern')
        try:
            pattern.Select()
        except Exception as exc:                        # noqa: BLE001
            return failed('Select failed', exc)
        return dict(ok=True, action='select', method='uia')

    if chosen == 'focus':
        try:
            obj.SetFocus()
        except Exception as exc:                        # noqa: BLE001
            return failed('SetFocus failed', exc)
        return dict(ok=True, action='focus', method='uia')

    if chosen == 'scroll_into_view':
        pattern = _pattern(obj, 'ScrollItem')
        if pattern is None:
            return dict(ok=False, action=chosen,
                        error='control has no ScrollItem pattern')
        try:
            pattern.ScrollIntoView()
        except Exception as exc:                        # noqa: BLE001
            return dict(ok=False, action=chosen, error='ScrollIntoView failed',
                        detail=f'{type(exc).__name__}: {exc}')
        return dict(ok=True, action='scroll_into_view', method='uia')

    bounds = state.get('bounds') or {}
    if not bounds or mouse is None:
        return dict(ok=False, error='no clickable bounds', action=chosen)
    cx, cy = bounds['x'] + bounds['w'] // 2, bounds['y'] + bounds['h'] // 2
    mouse.position = (cx, cy)
    mouse.click(mouse_button_left())
    return dict(ok=True, action='click', method='mouse', x=cx, y=cy)


def mouse_button_left():
    from pynput.mouse import Button

    return Button.left
