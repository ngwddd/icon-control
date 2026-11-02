"""Only explicitly registered Icon Control processes belong to the watchdog."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import psutil
from computer_mcp import security

def identity(process):
    return dict(pid=process.pid, created=process.create_time(),
                exe=str(Path(process.exe()).resolve()),
                command_sha256=hashlib.sha256('\0'.join(process.cmdline()).encode()).hexdigest())

def register_current():
    record = identity(psutil.Process(os.getpid()))
    record['signature'] = security.signature(record, security.load_token())
    folder = security.data_home() / 'state' / 'processes'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (str(os.getpid())+'.json')
    path.write_text(json.dumps(record), encoding='utf-8')
    return path

def registered():
    folder = security.data_home() / 'state' / 'processes'
    for path in folder.glob('*.json'):
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
            if not security.authentic(record): continue
            process = psutil.Process(record['pid'])
            expected = {k:v for k,v in record.items() if k != 'signature'}
            if identity(process) == expected:
                yield process
        except (OSError, ValueError, KeyError, psutil.Error):
            continue
