"""Shared local authority format. Possession of a token never bypasses policy."""
from __future__ import annotations
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import time
import tempfile

def data_home() -> Path:
    return Path(os.environ.get('ICON_CONTROL_HOME') or
                (Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'IconControl'))

def token_path() -> Path:
    return data_home() / 'state' / 'bridge-token.txt'

def load_token() -> str:
    try:
        token = token_path().read_text(encoding='utf-8').strip()
        return token if len(token) >= 32 and token != '__BRIDGE_TOKEN__' else ''
    except OSError:
        return ''

def provision_token() -> str:
    """Installer-only provisioning. Do not expose this as an agent tool."""
    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(secrets.token_urlsafe(32))
    token = load_token()
    if not token:
        raise RuntimeError('Invalid authority token; reprovision through installer')
    return token

def signature(payload: dict, token: str) -> str:
    body = {k: v for k, v in payload.items() if k != 'signature'}
    return hmac.new(token.encode(), json.dumps(body, sort_keys=True,
                    separators=(',', ':'), ensure_ascii=False).encode(), hashlib.sha256).hexdigest()

def authentic(payload: dict) -> bool:
    token = load_token()
    return bool(token and isinstance(payload.get('signature'), str) and
                hmac.compare_digest(signature(payload, token), payload['signature']))

def latch_stop():
    """Persist a physical emergency stop across worker process restarts."""
    path=data_home()/'state'/'emergency-stop.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    payload={'stopped_at':time.time()}
    token=load_token()
    if token:payload['signature']=signature(payload,token)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,
                                     prefix='stop-',suffix='.tmp',delete=False) as stream:
        temp=Path(stream.name)
        json.dump(payload,stream)
    try:
        os.replace(temp,path)
    finally:
        temp.unlink(missing_ok=True)
    return payload['stopped_at']

def stopped(payload):
    path=data_home()/'state'/'emergency-stop.json'
    if not path.exists():return False
    try:
        stop=json.loads(path.read_text(encoding='utf-8'))
        return not authentic(stop) or float(payload.get('authorized_at',0)) <= float(stop['stopped_at'])
    except (OSError,ValueError,TypeError,KeyError):return True
