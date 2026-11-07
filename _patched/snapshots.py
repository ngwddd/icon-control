"""Element references: re-resolve UIA nodes by structure, keep visual hits short-lived.

History: v1.3 bound a reference to a screenshot fingerprint with a 5 second TTL.
That made a reference useless the moment the window moved or a clock ticked, which
is why multi-step tasks kept re-observing. v1.4.1 splits the two cases:

* A **UIA reference** stores the child-index path inside its window. Resolving it
  walks the tree again and returns *current* bounds, so a moved or re-laid-out
  window is fine and costs nothing extra. If the control at that path is no longer
  the same name/type, the reference is stale.
* A **visual reference** (OCR or template hit) has nothing to re-resolve against, so
  it keeps the old contract: short TTL plus a window fingerprint.
"""
from __future__ import annotations

import copy
import hashlib
import os
import threading
import time
import uuid

_snapshots: dict = {}
_lock = threading.RLock()

REF_TTL_UIA = float(os.environ.get('ICON_CONTROL_REF_TTL', '120'))
REF_TTL_VISUAL = 5.0
MAX_SNAPSHOTS = 64


class StaleReference(ValueError):
    pass


def window_identity(hwnd):
    import ctypes
    from ctypes import wintypes

    import psutil
    import win32gui
    import win32process

    if not hwnd or not win32gui.IsWindow(hwnd):
        raise StaleReference('Window no longer exists')
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    function = ctypes.windll.user32.GetDpiForWindow
    function.argtypes = [wintypes.HWND]
    function.restype = wintypes.UINT
    return (int(hwnd), pid, psutil.Process(pid).create_time(), win32gui.GetWindowText(hwnd),
            tuple(win32gui.GetWindowRect(hwnd)), function(hwnd))


def screen_fingerprint(identity):
    from computer_mcp.core.screenshot import _grab

    left, top, right, bottom = identity[4]
    image, _, _ = _grab({'x': left, 'y': top, 'w': right - left, 'h': bottom - top})
    return hashlib.sha256(image.tobytes()).hexdigest()


def layout_digest(nodes) -> str:
    """Cheap stand-in for a screenshot: geometry plus names, no image capture."""
    payload = '|'.join(f"{n.get('type')}|{n.get('name')}|{n.get('x')},{n.get('y')},"
                       f"{n.get('w')},{n.get('h')}" for n in nodes)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]


def attach(hwnd, candidates):
    identity = window_identity(hwnd)
    nodes = copy.deepcopy(candidates[:1000])
    resolvable = bool(nodes) and all(node.get('path') for node in nodes)
    # Only ask for pixels when there is something to reference and it cannot be
    # re-resolved structurally. An empty tree (no UIA at all) needs no capture.
    digest = layout_digest(nodes)
    fingerprint = None
    if nodes and not resolvable:
        try:
            fingerprint = screen_fingerprint(identity)
        except Exception:
            fingerprint = ''
    ttl = REF_TTL_UIA if resolvable else REF_TTL_VISUAL
    now = time.monotonic()
    key = uuid.uuid4().hex
    for index, node in enumerate(nodes):
        node['ref'] = key + ':' + str(index)
    with _lock:
        for old in list(_snapshots):
            if now - _snapshots[old]['created'] > _snapshots[old]['ttl']:
                _snapshots.pop(old)
        while len(_snapshots) >= MAX_SNAPSHOTS:
            _snapshots.pop(next(iter(_snapshots)))
        _snapshots[key] = dict(created=now, ttl=ttl, identity=identity, digest=digest,
                               fingerprint=fingerprint, resolvable=resolvable,
                               nodes=copy.deepcopy(nodes))
    return dict(snapshot_id=key, expires_in_s=ttl, resolvable=resolvable,
                hwnd=int(hwnd), candidates=nodes)


def _check_identity(item, hwnd):
    expected = item['identity']
    if hwnd is not None and int(hwnd) != expected[0]:
        raise StaleReference('Reference belongs to another window')
    current = window_identity(expected[0])
    # pid / process creation time / dpi must match; the rectangle may move and the
    # title may change (editing a document adds a "*"), because a UIA reference
    # re-resolves by path to fresh coordinates.
    if current[:3] != expected[:3] or current[5] != expected[5]:
        raise StaleReference('Window, process or DPI changed; observe again')
    return expected, current


def _relocate(node, hwnd):
    from computer_mcp import ui_ext

    try:
        fresh = ui_ext.control_at_path(hwnd, node['path'])
    except StaleReference:
        raise
    except Exception as exc:                     # noqa: BLE001
        raise StaleReference(f'Cannot re-resolve the element path: {exc}') from None
    if not fresh:
        raise StaleReference('Element no longer exists at that path; observe again')
    if node.get('name') and fresh.get('name') != node['name']:
        raise StaleReference('Element at that path changed identity; observe again')
    if node.get('type') and fresh.get('type') != node['type']:
        raise StaleReference('Element at that path changed type; observe again')
    return fresh


def resolve(ref, hwnd=None):
    try:
        key, index = ref.split(':')
        index = int(index)
    except (AttributeError, ValueError):
        raise StaleReference('Invalid element reference') from None
    with _lock:
        item = copy.deepcopy(_snapshots.get(key))
    if not item or time.monotonic() - item['created'] > item['ttl']:
        raise StaleReference('Element reference expired; observe again')
    if index < 0 or index >= len(item['nodes']):
        raise StaleReference('Unknown element reference')
    expected, current = _check_identity(item, hwnd)
    node = item['nodes'][index]
    if item['resolvable']:
        fresh = _relocate(node, expected[0])
        target = dict(node)
        target.update(x=fresh['x'], y=fresh['y'], w=fresh['w'], h=fresh['h'])
        moved = (current[4] != expected[4])
        target['relocated'] = moved
    else:
        if current[4] != expected[4]:
            raise StaleReference('Window moved; visual reference is no longer reliable')
        if item['fingerprint']:
            try:
                if screen_fingerprint(current) != item['fingerprint']:
                    raise StaleReference('Window content changed; observe again')
            except StaleReference:
                raise
            except Exception as exc:             # noqa: BLE001
                raise StaleReference(f'Cannot verify the window: {exc}') from None
        target = dict(node)
    target['hwnd'] = expected[0]
    target.setdefault('cx', target['x'] + target['w'] // 2)
    target.setdefault('cy', target['y'] + target['h'] // 2)
    left, top, right, bottom = current[4]
    if not left <= target['cx'] < right or not top <= target['cy'] < bottom:
        raise StaleReference('Target outside window')
    return target
