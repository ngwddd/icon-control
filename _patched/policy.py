"""Local execution policy (v1.4.0): the MCP connection is the only authority.

Why this module exists
----------------------
Up to v1.3.9 every input tool had to prove that a human had just approved it:
a signed bridge state (or a 30-day trust record) had to be fresh, bound to the
caller's session, and inside a scope/app allow-list. That made "call a tool"
depend on a second process (``permission_bridge``), a tray UI, a hotkey, and
periodic re-approval after every upgrade.

v1.4.0 removes the human-approval requirement and keeps the *execution* guards:
the takeover check, the emergency stop, target-window identity, and the
per-tool argument validation. Authority now comes from the fact that the caller
already owns this user's session and can reach this MCP transport.

Stop semantics (matters)
------------------------
``security.stopped()`` compares the moment authority was granted with the
moment the emergency stop fired. The policy record therefore must never invent
a fresh grant time while a stop latch exists: doing so would silently undo the
stop. Missing or unreadable records are treated as "no authority yet" whenever
a latch is present, and the only way back is an explicit ``resume()``.

What is deliberately kept
-------------------------
* ``security.stopped()``: a durable emergency stop still denies everything
  until an explicit resume (``policy.resume()``).
* ``control.blocking_reason()``: a physical user always wins for 10 seconds.
* ``capabilities.check_target``: a target must still be a real process, and the
  approval UI itself may never be automated.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path

from computer_mcp import agent_session, security

MODE_ENV = 'ICON_CONTROL_POLICY'
LOCAL = 'local'
HUMAN = 'human'
DEFAULT_MODE = LOCAL
LEASE_SECONDS = 3600.0
WILDCARD = '*'

# Only the facts that come from the two files are cached. The authorisation
# payload is rebuilt per call because it embeds the caller's session, and one
# process can serve several HTTP clients with different session identities.
_FACTS = {'signature': None, 'value': None}
_SCOPES = {'value': None}
_WRITE_LOCK = threading.RLock()


def _record_path() -> Path:
    return security.data_home() / 'state' / 'local-policy.json'


record_path = _record_path


def _stop_path() -> Path:
    return security.data_home() / 'state' / 'emergency-stop.json'


def _load() -> dict:
    try:
        data = json.loads(_record_path().read_text(encoding='utf-8'))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def _save(payload: dict) -> dict:
    """Write the record atomically; raise rather than pretend success."""
    with _WRITE_LOCK:
        return _save_locked(payload)


def _save_locked(payload: dict) -> dict:
    target = _record_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    last: Exception | None = None
    for attempt in range(12):
        handle, name = tempfile.mkstemp(dir=str(target.parent), prefix='policy-', suffix='.tmp')
        try:
            with os.fdopen(handle, 'w', encoding='utf-8') as stream:
                json.dump(payload, stream, ensure_ascii=False)
            os.replace(name, target)
            # A concurrent writer may have won the race with a newer record;
            # any parseable record means the path is intact.
            if not _load():
                raise OSError('policy record did not persist')
            return payload
        except PermissionError as exc:      # Windows sharing violation: retry
            last = exc
            time.sleep(0.02 * (attempt + 1))
        finally:
            try:
                os.unlink(name)
            except OSError:
                pass
    raise OSError(f'cannot persist the local policy record: {last}')


def mode() -> str:
    """``local`` (default) or ``human``; env wins, then the record, then default."""
    value = (os.environ.get(MODE_ENV) or '').strip().lower()
    if value in (LOCAL, 'headless', 'on', '1', 'true'):
        return LOCAL
    if value in (HUMAN, 'approval', 'off', '0', 'false'):
        return HUMAN
    stored = str(_load().get('mode') or '').strip().lower()
    if stored in (LOCAL, HUMAN):
        return stored
    return DEFAULT_MODE


def is_local() -> bool:
    return mode() == LOCAL


def _file_signature(path: Path):
    try:
        stat = path.stat()
        return (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return None


def _signature():
    return (_file_signature(_record_path()), _file_signature(_stop_path()))


def _parse_time(record: dict) -> float:
    try:
        return float(record.get('authorized_at') or 0)
    except (TypeError, ValueError):
        return 0.0


def _facts() -> dict:
    """(authorised_at, stop_latch_present) — cached until either file changes."""
    signature = _signature()
    if _FACTS['value'] is not None and _FACTS['signature'] == signature:
        return _FACTS['value']
    record = _load()
    value = dict(authorized_at=_parse_time(record),
                 has_record=bool(record),
                 stop_present=_stop_path().exists())
    _FACTS.update(signature=signature, value=value)
    return value


def authorized_at() -> float:
    """When authority was granted; 0.0 means "not authorised, do not invent it".

    A missing record on a healthy install is created once (first run). A stop
    latch in place suppresses that creation: otherwise deleting the record
    would be an easy way to cancel an emergency stop.
    """
    facts = _facts()
    if facts['authorized_at'] > 0:
        return facts['authorized_at']
    if facts['stop_present']:
        return 0.0
    now = time.time()
    record = _load()
    record.update(mode=record.get('mode') or LOCAL, authorized_at=now,
                  created_at=record.get('created_at') or now)
    _save(record)
    _FACTS.update(signature=None, value=None)
    return now


def resume() -> dict:
    """Explicit local resume after an emergency stop; the only way back.

    The latch is removed on purpose: a resume is a human decision, and relying
    on "my timestamp is newer than the stop" breaks when both land in the same
    clock tick.
    """
    now = time.time()
    record = _load()
    record.update(mode=record.get('mode') or LOCAL, authorized_at=now, resumed_at=now)
    record.setdefault('created_at', now)
    saved = _save(record)
    try:
        _stop_path().unlink()
    except OSError:
        pass
    _FACTS.update(signature=None, value=None)
    return saved


def ensure_initialised() -> dict | None:
    """Prepare a fresh install without ever undoing a stop or a resume.

    Called by the installer: it may create the record when none exists and no
    stop is latched, and otherwise leaves the current state untouched.
    """
    facts = _facts()
    if facts['has_record'] or facts['stop_present']:
        return None
    return dict(authorized_at=authorized_at())


def subject() -> str:
    parts = [str(security.data_home().resolve()).lower(),
             os.environ.get('COMPUTERNAME', ''),
             os.environ.get('USERNAME', '')]
    return hashlib.sha256('|'.join(parts).encode('utf-8')).hexdigest()[:32]


def _all_scopes() -> list:
    if _SCOPES['value'] is None:
        from computer_mcp import capabilities
        _SCOPES['value'] = tuple(sorted(capabilities.SCOPES))
    return list(_SCOPES['value'])


def authorization() -> dict:
    now = time.time()
    return dict(agent_session=agent_session.current(),
                agent_id=subject(),
                scopes=_all_scopes(),
                applications=[WILDCARD],
                launches=[WILDCARD],
                read_files=[WILDCARD],
                lease_expires_at=now + LEASE_SECONDS,
                source=LOCAL)


def _stopped(started: float) -> bool:
    try:
        return bool(security.stopped(dict(session=agent_session.current(), revision=1,
                                          authorized_at=started)))
    except Exception:
        return True          # fail closed: an unreadable latch is a stop


def state() -> dict:
    """The payload ``permission.status()`` returns while the policy is local."""
    now = time.time()
    started = authorized_at()
    if started <= 0 or _stopped(started):
        return dict(granted=False, source='local', code='permission_revoked',
                    reason='Emergency stop active; resume with python -m computer_mcp.policy resume',
                    checked_at=time.strftime('%Y-%m-%d %H:%M:%S'),
                    checked_at_ts=now, expires_at=now + LEASE_SECONDS,
                    authorized_at=started, session=agent_session.current(),
                    revision=1, authorization={})
    return dict(granted=True, source='local', age_s=0.0, screen_text='',
                checked_at=time.strftime('%Y-%m-%d %H:%M:%S'),
                checked_at_ts=now, expires_at=now + LEASE_SECONDS,
                authorized_at=started, session=agent_session.current(),
                revision=1, authorization=authorization())


def runtime_state() -> str:
    """ready / user_takeover / stopped / error — what control_status reports.

    Deliberately uses ``control.status()`` rather than
    ``control.blocking_reason()``: the latter installs the low-level input
    hooks, and a read-only status query must not start monitoring.
    """
    started = authorized_at()
    if started <= 0 or _stopped(started):
        return 'stopped'
    try:
        from computer_mcp import control
        state = control.status()
    except Exception:
        return 'error'
    if not state.get('enabled', True):
        return 'error'
    if state.get('owner') == 'user':
        return 'user_takeover'
    return 'ready'


def status() -> dict:
    """Diagnostics for doctor.py / control_status."""
    facts = _facts()
    return dict(mode=mode(), path=str(_record_path()),
                record=_load(), facts=facts,
                runtime=runtime_state(), subject=subject())


def main(argv=None) -> int:
    import argparse
    import sys
    parser = argparse.ArgumentParser(prog='computer_mcp.policy')
    parser.add_argument('command', nargs='?', default='status',
                        choices=['status', 'resume', 'enable', 'disable'])
    args = parser.parse_args(argv)
    if args.command == 'resume':
        print(json.dumps(resume(), ensure_ascii=False))
        return 0
    if args.command == 'enable':
        record = _load()
        record.update(mode=LOCAL, authorized_at=time.time())
        print(json.dumps(_save(record), ensure_ascii=False))
        _FACTS.update(signature=None, value=None)
        return 0
    if args.command == 'disable':
        record = _load()
        record.update(mode=HUMAN)
        record.setdefault('created_at', time.time())
        print(json.dumps(_save(record), ensure_ascii=False))
        _FACTS.update(signature=None, value=None)
        return 0
    print(json.dumps(status(), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
