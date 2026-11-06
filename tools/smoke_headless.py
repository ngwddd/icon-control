"""Live smoke: local policy grants without any bridge, and human mode still denies."""
import json
import os
import tempfile
from pathlib import Path

home = tempfile.mkdtemp(prefix='ic-headless-')
os.environ['ICON_CONTROL_HOME'] = home
os.environ['ICON_CONTROL_POLICY'] = 'local'
os.environ['PYTHONIOENCODING'] = 'utf-8'

from computer_mcp import agent_session, capabilities, permission, policy  # noqa: E402
from computer_mcp import tool_registry  # noqa: E402
from computer_mcp.zones.dispatch import dispatch  # noqa: E402

agent_session.register('headless smoke')

report = {}
report['mode'] = policy.mode()
state = permission.status()
report['granted'] = state.get('granted')
report['source'] = state.get('source')
report['scopes'] = len((state.get('authorization') or {}).get('scopes') or [])
report['apps'] = (state.get('authorization') or {}).get('applications')

# 1. the gate itself must let an input tool through
report['click_denial'] = permission.check_tool('click', {'x': 10, 'y': 10})

# 2. tools that used to be unreachable under a trust record
record = capabilities.launch_record(os.path.join(os.environ['WINDIR'], 'System32', 'notepad.exe'), '')
report['launch_record_ok'] = bool(record.get('sha256'))
try:
    capabilities.require_launch(os.path.join(os.environ['WINDIR'], 'System32', 'notepad.exe'), '')
    report['require_launch'] = 'allowed'
except Exception as exc:
    report['require_launch'] = f'{type(exc).__name__}: {exc}'

# 3. a real observation tool through the same dispatch the MCP server uses
from computer_mcp.zones.dispatch import ComputerState  # noqa: E402
from computer_mcp.input_guard import MouseController, KeyboardController  # noqa: E402

try:
    out = dispatch('control_status', {}, computer_state=ComputerState(),
                   mouse_controller=MouseController(), keyboard_controller=KeyboardController())
    result = out.get('result') or {}
    report['control_status_policy'] = result.get('policy')
    report['control_status_version'] = (result.get('runtime_contract') or {}).get('version')
except Exception as exc:
    report['control_status_policy'] = f'{type(exc).__name__}: {exc}'

# 4. human mode in the same home must still deny without a grant
os.environ['ICON_CONTROL_POLICY'] = 'human'
human_state = permission.status()
report['human_mode_granted'] = human_state.get('granted')
report['human_mode_reason'] = human_state.get('reason')

print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
