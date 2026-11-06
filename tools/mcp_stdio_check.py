"""End-to-end MCP stdio check against the installed launcher (JSON-RPC lines)."""
import json
import os
import subprocess
import sys
import threading
import time

HOME = os.environ.get('LOCALAPPDATA') + r'\IconControl'
PY = HOME + r'\current\Scripts\python.exe'
env = dict(os.environ, ICON_CONTROL_HOME=HOME, PYTHONIOENCODING='utf-8',
           ICON_CONTROL_POLICY='local')

proc = subprocess.Popen([PY, '-m', 'computer_mcp.launcher', 'stdio'],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL, env=env, text=True,
                        encoding='utf-8', bufsize=1)

responses = {}
lock = threading.Lock()


def reader():
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if 'id' in message:
            with lock:
                responses[message['id']] = message


threading.Thread(target=reader, daemon=True).start()


def send(payload):
    proc.stdin.write(json.dumps(payload) + '\n')
    proc.stdin.flush()


def wait(request_id, timeout=25):
    end = time.time() + timeout
    while time.time() < end:
        with lock:
            if request_id in responses:
                return responses[request_id]
        time.sleep(0.05)
    return None


def fail(reason):
    print(json.dumps(dict(ok=False, reason=reason), ensure_ascii=False))
    try:
        proc.kill()
    except Exception:
        pass
    raise SystemExit(1)


send(dict(jsonrpc='2.0', id=1, method='initialize',
          params=dict(protocolVersion='2024-11-05',
                      capabilities={},
                      clientInfo=dict(name='headless-check', version='1'))))
init = wait(1)
if not init:
    fail('no initialize response')

send(dict(jsonrpc='2.0', method='notifications/initialized', params={}))

send(dict(jsonrpc='2.0', id=2, method='tools/list', params={}))
tools = wait(2)
if not tools:
    fail('no tools/list response')
names = [tool['name'] for tool in tools['result']['tools']]

send(dict(jsonrpc='2.0', id=3, method='tools/call',
          params=dict(name='control_status', arguments={})))
call = wait(3)
if not call:
    fail('no tools/call response')

content = call['result'].get('content') or []
texts = [item.get('text', '') for item in content if item.get('type') == 'text']
text = texts[0] if texts else ''
types = [item.get('type') for item in content]
report = dict(ok=not call['result'].get('isError'),
              server=init['result'].get('serverInfo'),
              protocol=init['result'].get('protocolVersion'),
              tools=len(names),
              tool_sample=names[:5],
              call_is_error=call['result'].get('isError'),
              call_text=text[:400], content_types=types)
print(json.dumps(report, ensure_ascii=False, indent=2))
proc.kill()
