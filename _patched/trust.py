"""Signed 30-day trust record for the installed agent (v1.3.9-beta).

Why: session-bound approvals die on every restart, so the user re-approves
constantly. A trust record says "this installation, in this workspace, with this
tool fingerprint, may act without asking again for N days".

What it is not: it is not a grant. ``permission.status()`` still runs on every
call, the record is HMAC-signed with the installer token, revocation and the
emergency stop beat it, and changing the tool fingerprint (an upgrade) or the
workspace invalidates it.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

from computer_mcp import security

DEFAULT_DAYS = 30
LEASE_SECONDS = 900
WILDCARD = '*'


def path() -> Path:
    return security.data_home() / 'state' / 'desktop-trust.json'


def _stop_path() -> Path:
    return security.data_home() / 'state' / 'emergency-stop.json'


_TOOLS_CACHE = {"value": None}


def tools_fingerprint() -> str:
    """Cached: runtime_contract hashes every tool schema, far too slow per call."""
    if _TOOLS_CACHE["value"] is None:
        from computer_mcp import runtime_contract
        try:
            _TOOLS_CACHE["value"] = str(
                runtime_contract.describe(include_schema=False).get('tools_sha256') or '')
        except Exception:
            _TOOLS_CACHE["value"] = ''
    return _TOOLS_CACHE["value"]


def workspace() -> str:
    from computer_mcp import agent_session
    try:
        return agent_session.workspace_identity()
    except Exception:
        return ''


def subject_id() -> str:
    """Stable for an installation+workspace+tool set; changes on any of them."""
    parts = [workspace(), tools_fingerprint(), os.environ.get('COMPUTERNAME', '')]
    return hashlib.sha256('|'.join(parts).encode('utf-8')).hexdigest()[:32]


def _write(payload: dict) -> dict:
    token = security.load_token()
    if not token:
        raise RuntimeError('Installer token missing; trust cannot be signed')
    payload = dict(payload)
    payload.pop('signature', None)
    payload['signature'] = security.signature(payload, token)
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                     prefix='trust-', suffix='.tmp', delete=False) as stream:
        json.dump(payload, stream, ensure_ascii=False)
        temporary = Path(stream.name)
    os.replace(temporary, target)
    return payload


def load() -> dict | None:
    try:
        data = json.loads(path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not security.authentic(data):
        return None
    return data


def grant(days: int = DEFAULT_DAYS, confirm=None) -> dict:
    """Create the trust record. ``confirm`` must be the user's gesture.

    There is deliberately no default: an agent that reaches this function must
    still obtain a human confirmation, so a missing ``confirm`` fails closed.
    """
    if not callable(confirm) or not confirm():
        raise PermissionError('Trust requires an explicit user confirmation')
    now = time.time()
    payload = dict(schema=1, subject=subject_id(), workspace=workspace(),
                   tools_sha256=tools_fingerprint(),
                   granted_at=now, expires_at=now + max(1, int(days)) * 86400,
                   days=int(days), revoked_at=None, revocation_generation=0)
    return _write(payload)


def revoke() -> dict:
    record = load() or dict(subject=subject_id(), workspace=workspace(),
                            tools_sha256=tools_fingerprint(), granted_at=0,
                            expires_at=0, days=0, revoked_at=None,
                            revocation_generation=0)
    record = dict(record)
    record['revoked_at'] = time.time()
    record['revocation_generation'] = int(record.get('revocation_generation') or 0) + 1
    return _write(record)


def _stopped_after(record: dict) -> bool:
    try:
        stop = json.loads(_stop_path().read_text(encoding='utf-8'))
        when = float(stop.get('stopped_at') or 0)
    except (OSError, ValueError, TypeError):
        return False
    return when >= float(record.get('granted_at') or 0)


def validate(now: float | None = None) -> dict:
    now = time.time() if now is None else now
    record = load()
    if not record:
        return dict(ok=False, reason='no trust record', subject=None)
    subject = subject_id()
    if record.get('revoked_at'):
        return dict(ok=False, reason='revoked', subject=record.get('subject'))
    if record.get('subject') != subject:
        return dict(ok=False, reason='subject changed (workspace, tool fingerprint or host)', subject=record.get('subject'))
    expires = float(record.get('expires_at') or 0)
    if expires <= now:
        return dict(ok=False, reason='trust expired', subject=record.get('subject'))
    if _stopped_after(record):
        return dict(ok=False, reason='emergency stop after trust was granted', subject=record.get('subject'))
    return dict(ok=True, reason='trusted', subject=record.get('subject'),
                expires_at=expires, days_left=round((expires - now) / 86400, 1),
                generation=int(record.get('revocation_generation') or 0))


def authorization(now: float | None = None) -> dict | None:
    """Live authority for a trusted subject; short lease, re-checked every call."""
    from computer_mcp import agent_session, capabilities
    state = validate(now)
    if not state.get('ok'):
        return None
    now = time.time() if now is None else now
    return dict(agent_session=agent_session.current(), agent_id=state['subject'],
                scopes=sorted(capabilities.SCOPES), applications=[WILDCARD],
                lease_expires_at=now + LEASE_SECONDS, source='trust',
                trust_expires_at=state.get('expires_at'))


def main(argv=None) -> int:
    """Human entry point: ``python -m computer_mcp.trust [grant|revoke|status]``.

    ``grant`` only succeeds after the native one-click prompt returns True, so a
    tool call cannot mint trust by itself.
    """
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(prog='computer_mcp.trust')
    sub = parser.add_subparsers(dest='command', required=True)
    grant_parser = sub.add_parser('grant', help='ask the user once, then trust this install')
    grant_parser.add_argument('--days', type=int, default=DEFAULT_DAYS)
    sub.add_parser('revoke', help='revoke trust immediately')
    sub.add_parser('status', help='print the current trust state')
    args = parser.parse_args(argv)

    if args.command == 'status':
        print(json.dumps(validate(), ensure_ascii=False, indent=2))
        return 0 if validate().get('ok') else 3

    if args.command == 'revoke':
        record = revoke()
        print(json.dumps(dict(revoked=True, revocation_generation=record['revocation_generation']),
                         ensure_ascii=False))
        return 0

    from computer_mcp import native_dialog
    if args.days < 1 or args.days > 365:
        print(json.dumps(dict(granted=False, reason='days out of range'), ensure_ascii=False))
        return 2
    if not native_dialog.ask_trust(args.days, subject_id()):
        print(json.dumps(dict(granted=False, reason='user declined or UI unavailable'),
                         ensure_ascii=False))
        return 1
    record = grant(days=args.days, confirm=lambda: True)
    print(json.dumps(dict(granted=True, subject=record['subject'], days=record['days'],
                          expires_at=record['expires_at']), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
