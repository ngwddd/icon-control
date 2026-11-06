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

What is deliberately kept
-------------------------
* ``security.stopped()``: a durable emergency stop still denies everything
  until an explicit resume (``policy.resume()``).
* ``control.blocking_reason()``: a physical user always wins for 10 seconds.
* ``capabilities.check_target``: the agent may never automate the approval UI
  itself, and a window must still be a real process.

What replaces the approval record
---------------------------------
``state/local-policy.json`` stores the mode and the moment authority was last
granted. The emergency stop compares against that timestamp, so a stop issued
after the policy was enabled keeps the agent frozen until a resume bumps it.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from computer_mcp import agent_session, security

MODE_ENV = 'ICON_CONTROL_POLICY'
LOCAL = 'local'
HUMAN = 'human'
DEFAULT_MODE = LOCAL
LEASE_SECONDS = 3600.0
WILDCARD = '*'


def mode() -> str:
    """``local`` (v1.4.0 default) or ``human`` (the pre-1.4 approval flow)."""
    value = (os.environ.get(MODE_ENV) or '').strip().lower()
    if value in (LOCAL, 'headless', 'on', '1', 'true'):
        return LOCAL
    if value in (HUMAN, 'approval', 'off', '0', 'false'):
        return HUMAN
    return DEFAULT_MODE


def is_local() -> bool:
    return mode() == LOCAL


def record_path() -> Path:
    return security.data_home() / 'state' / 'local-policy.json'


def _load() -> dict:
    try:
        data = json.loads(record_path().read_text(encoding='utf-8'))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def _save(payload: dict) -> dict:
    target = record_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    os.replace(temporary, target)
    return payload


def authorized_at() -> float:
    """When authority was last (re)granted. Defaults to the first sighting."""
    record = _load()
    try:
        value = float(record.get('authorized_at') or 0)
    except (TypeError, ValueError):
        value = 0.0
    if value > 0:
        return value
    now = time.time()
    try:
        _save(dict(record, mode=LOCAL, authorized_at=now, created_at=now))
    except OSError:
        pass
    return now


def resume() -> dict:
    """Explicit local resume after an emergency stop; the only way back."""
    now = time.time()
    record = _load()
    record.update(mode=LOCAL, authorized_at=now, resumed_at=now)
    record.setdefault('created_at', now)
    return _save(record)


def subject() -> str:
    """Stable per-installation identity, used for diagnostics only."""
    parts = [str(security.data_home().resolve()).lower(),
             os.environ.get('COMPUTERNAME', ''),
             os.environ.get('USERNAME', '')]
    return hashlib.sha256('|'.join(parts).encode('utf-8')).hexdigest()[:32]


def _stop_active(authorization_at: float) -> bool:
    payload = dict(session=agent_session.current(), revision=1,
                   authorized_at=authorization_at)
    try:
        return bool(security.stopped(payload))
    except Exception:
        return True          # fail closed: an unreadable latch is a stop


def authorization() -> dict:
    now = time.time()
    return dict(agent_session=agent_session.current(),
                agent_id=subject(),
                scopes=sorted(__import__('computer_mcp.capabilities',
                                         fromlist=['SCOPES']).SCOPES),
                applications=[WILDCARD],
                launches=[WILDCARD],
                read_files=[WILDCARD],
                lease_expires_at=now + LEASE_SECONDS,
                source=LOCAL)


def state() -> dict:
    """The payload ``permission.status()`` returns while the policy is local."""
    started = authorized_at()
    now = time.time()
    if _stop_active(started):
        return dict(granted=False, source='local', code='permission_revoked',
                    reason='Emergency stop active; resume with policy.resume()',
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
    """ready / user_takeover / stopped / error — what control_status reports."""
    if _stop_active(authorized_at()):
        return 'stopped'
    try:
        from computer_mcp import control
        if control.blocking_reason():
            return 'user_takeover'
    except Exception:
        return 'error'
    return 'ready'


def status() -> dict:
    """Diagnostics for doctor.py / control_status."""
    record = _load()
    return dict(mode=mode(), path=str(record_path()), record=record,
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
        print(json.dumps(_save(dict(_load(), mode=LOCAL, authorized_at=time.time())),
                         ensure_ascii=False))
        return 0
    if args.command == 'disable':
        print(json.dumps(_save(dict(_load(), mode=HUMAN)), ensure_ascii=False))
        return 0
    print(json.dumps(status(), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
