"""zones/z0_governance/tools.py — 治理：授权、急停、保留、配置（Z0）

自动生成（R3）：定义与实现在一起，schema 是唯一来源。
不要手改生成标记之间的内容之外的 schema 结构；改工具请改本文件后跑测试。
"""

from __future__ import annotations

from computer_mcp.tool_spec import ToolSpec

SPECS: list[ToolSpec] = [
    ToolSpec(
        name='housekeeping',
        zone='Z0',
        description="Show disk usage of this tool's own folders (_draw / recordings / vision baselines) and optionally prune them. Assets (macros, recipes, templates, _patched) are never touched. action=status (default, read-only) or sweep (with dry_run).",
        read_only=True,
        schema={'type': 'object', 'properties': {'action': {'type': 'string', 'enum': ['status', 'sweep']}, 'dry_run': {'type': 'boolean'}}, 'additionalProperties': False},
    ),
    ToolSpec(
        name='set_config',
        zone='Z0',
        description='Configure observation options',
        read_only=False,
        schema={'type': 'object', 'properties': {'observe_screen': {'type': 'boolean', 'description': 'Include screenshots in responses (default: true)', 'default': True}, 'observe_mouse_position': {'type': 'boolean', 'description': 'Track and include mouse position', 'default': False}, 'observe_mouse_button_states': {'type': 'boolean', 'description': 'Track and include mouse button states', 'default': False}, 'observe_keyboard_key_states': {'type': 'boolean', 'description': 'Track and include keyboard key states', 'default': False}, 'observe_focused_app': {'type': 'boolean', 'description': 'Include focused application information', 'default': False}, 'observe_accessibility_tree': {'type': 'boolean', 'description': 'Include accessibility tree', 'default': False}, 'disallowed_hotkeys': {'type': 'array', 'items': {'type': 'string'}, 'description': "List of hotkey strings to disallow (e.g., ['ctrl+c', 'alt+f4'])", 'default': []}, 'constrain_mouse_to_window': {'oneOf': [{'type': 'null'}, {'type': 'integer'}, {'type': 'string'}], 'description': 'Constrain mouse movement and clicks to window bounds. Set to window handle (int), window title pattern (str), or null to disable.', 'default': None}, 'observe_system_metrics': {'type': 'boolean', 'description': 'Track and include system performance metrics (CPU, memory, disk I/O, network I/O)', 'default': False}}},
    ),

    ToolSpec(
        name='control_status',
        zone='Z0',
        description='读桌面控制权归属：ai / user / idle，以及用户接管后还有多久恢复',
        read_only=True,
        schema={'type': 'object', 'properties': {}},
    ),
    ToolSpec(
        name='control_claim',
        zone='Z0',
        description='申请或交还桌面控制权（action=claim|release）。用户物理动鼠标会自动夺回',
        read_only=False,
        schema={
            'type': 'object',
            'properties': {
                'action': {'type': 'string', 'enum': ['claim', 'release'], 'default': 'claim'},
                'reason': {'type': 'string'},
            },
        },
    ),
]
