"""zones/z1_capture/tools.py — 采集：截图、录屏、守护进程、模板抓取（Z1）

自动生成（R3）：定义与实现在一起，schema 是唯一来源。
不要手改生成标记之间的内容之外的 schema 结构；改工具请改本文件后跑测试。
"""

from __future__ import annotations

from computer_mcp.tool_spec import ToolSpec

SPECS: list[ToolSpec] = [
    ToolSpec(
        name='capture_config',
        effects=('config_write',),
        read_when_absent=('scale','quality','format','diff_threshold','mask_bottom'),
        zone='Z1',
        description='Get or set capture settings: scale (default 0.5 -> 1280x720), quality (75), format (jpeg|png), diff_threshold (0.8 %), mask_bottom (60 px of taskbar ignored by change detection). Call with no args to just read them.',
        read_only=True,
        schema={'type': 'object', 'properties': {'scale': {'type': 'number', 'description': 'Downscale factor, 1.0 = full resolution'}, 'quality': {'type': 'integer', 'description': 'JPEG quality 1-95'}, 'format': {'type': 'string', 'enum': ['jpeg', 'png']}, 'diff_threshold': {'type': 'number', 'description': 'Mean abs diff % that counts as changed'}, 'mask_bottom': {'type': 'integer', 'description': 'Bottom pixel rows ignored by change detection'}}},
    ),
    ToolSpec(
        name='capture_daemon',
        effects=('file_write',),
        read_actions=('status',),
        action_default='status',
        zone='Z1',
        description='Start/stop/status of the persistent screen-capture daemon (ring buffer, default scale 0.25, 12 fps active / 3 fps idle). After start, sense/watch/probe read memory instead of grabbing the screen.',
        read_only=False,
        schema={'type': 'object', 'properties': {'action': {'type': 'string', 'enum': ['start', 'status', 'stop']}, 'scale': {'type': 'number'}, 'active_fps': {'type': 'number'}, 'idle_fps': {'type': 'number'}, 'monitor': {'type': 'integer'}}, 'additionalProperties': False},
    ),
    ToolSpec(
        name='record',
        effects=('file_write',),
        zone='Z1',
        description='Dump the daemon ring buffer (frames + manifest + last trace) to disk for evidence or replay.',
        read_only=False,
        schema={'type': 'object', 'properties': {'action': {'type': 'string', 'enum': ['start', 'stop']}}, 'required': ['action'], 'additionalProperties': False},
    ),
    ToolSpec(
        name='screenshot',
        effects=('observe',),
        zone='Z1',
        description='Capture a screenshot of the display and return it as base64-encoded PNG',
        read_only=True,
        schema={'type': 'object', 'properties': {}},
    ),
    ToolSpec(
        name='screenshot_window',
        effects=('observe',),
        zone='Z1',
        description='Capture screenshot of a specific window',
        read_only=True,
        schema={'type': 'object', 'properties': {'hwnd': {'type': 'integer', 'description': 'Window handle'}}, 'required': ['hwnd']},
    ),
    ToolSpec(
        name='snapshot',
        effects=('file_write','file_delete',),
        zone='Z1',
        description='Grab one image on demand and return its file path (no base64). Use only when pixels must be inspected.',
        read_only=True,
        schema={'type': 'object', 'properties': {'region': {'type': 'array', 'items': {'type': 'integer'}}, 'scale': {'type': 'number'}}, 'additionalProperties': False},
    ),
    ToolSpec(
        name='track',
        effects=('compose','input','clipboard_write','window','file_write',),
        zone='Z1',
        description="列车：三轮回转（入帧 30fps / 处理差分状态机 / 输出摘要+拼图）+ 看门狗。action=start 后列车常驻后台跑，随时用 status 取新鲜摘要（含一张拼图路径）；action=run 阻塞跑到结束；stop 停车；selfcheck 短跑报 fps/内存。track={'name':..,'window':{'process':..},'steps':[{name,expect,action,budget_ms}]}",
        read_only=False,
        schema={'type': 'object', 'properties': {'action': {'type': 'string', 'enum': ['run', 'start', 'status', 'stop', 'selfcheck']}, 'id': {'type': 'integer'}, 'track': {'type': 'object'}, 'recipe': {'type': 'string'}, 'hwnd': {'type': 'integer'}, 'max_total_s': {'type': 'number'}, 'wait_s': {'type': 'number'}, 'seconds': {'type': 'number'}}, 'required': ['action'], 'additionalProperties': False},
    ),
]
