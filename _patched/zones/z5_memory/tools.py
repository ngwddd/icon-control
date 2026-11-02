"""zones/z5_memory/tools.py — 资产：宏、模板、基线、字形、应用知识（Z5）

自动生成（R3）：定义与实现在一起，schema 是唯一来源。
不要手改生成标记之间的内容之外的 schema 结构；改工具请改本文件后跑测试。
"""

from __future__ import annotations

from computer_mcp.tool_spec import ToolSpec

SPECS: list[ToolSpec] = [
    ToolSpec(
        name='anchor_mem',
        effects=('file_write',),
        read_actions=('list','stats'),
        action_default='list',
        zone='Z5',
        description='Learned anchor memory for UI elements: list / learn / verify / forget / stats. Stores normalised position + a 64-bit visual fingerprint + usage counters, so a click can be verified instead of guessed.',
        read_only=True,
        schema={'type': 'object', 'properties': {'action': {'type': 'string', 'enum': ['list', 'learn', 'verify', 'forget', 'stats']}, 'app': {'type': 'string'}, 'key': {'type': 'string'}, 'hwnd': {'type': 'integer'}, 'x': {'type': 'integer'}, 'y': {'type': 'integer'}, 'note': {'type': 'string'}}, 'required': ['action']},
    ),
    ToolSpec(
        name='capture_template',
        effects=('file_write',),
        zone='Z5',
        description="Save a screen region as a reusable template (grayscale PNG) under the tool's vision store. Use this for self-drawn UIs where UI Automation is blind: capture the button/icon once, then match_template finds it later. Give a tight region around the visual itself.",
        read_only=False,
        schema={'type': 'object', 'properties': {'name': {'type': 'string', 'description': 'Template name'}, 'x': {'type': 'integer'}, 'y': {'type': 'integer'}, 'w': {'type': 'integer'}, 'h': {'type': 'integer'}, 'hwnd': {'type': 'integer', 'description': 'Optional: grab the window bitmap (works when covered)'}, 'overwrite': {'type': 'boolean', 'default': True}}, 'required': ['name', 'x', 'y', 'w', 'h']},
    ),
    ToolSpec(
        name='glyph',
        effects=('file_write',),
        read_actions=('list','status'),
        action_default='list',
        zone='Z5',
        description='Manage learned digit glyphs for pixel fonts. action=list|learn|clear; learn needs label and box.',
        read_only=False,
        schema={'type': 'object', 'properties': {'action': {'type': 'string', 'enum': ['list', 'learn', 'clear']}, 'label': {'type': 'string'}, 'box': {'type': 'array', 'items': {'type': 'integer'}}, 'thr': {'type': 'integer'}}, 'required': ['action'], 'additionalProperties': False},
    ),
    ToolSpec(
        name='layout_mem',
        effects=('file_write',),
        read_actions=('list','resolve'),
        zone='Z5',
        description='Layout calibration memory (generic): save normalized regions once per app, then resolve to pixels at any window size. action=save needs hwnd+regions{name:[x,y,w,h] rel 0..1}; action=resolve returns pixel boxes; list/delete manage profiles.',
        read_only=True,
        schema={'type': 'object', 'properties': {'action': {'type': 'string', 'enum': ['save', 'list', 'resolve', 'delete']}, 'hwnd': {'type': 'integer'}, 'name': {'type': 'string'}, 'regions': {'type': 'object'}, 'meta': {'type': 'object'}}, 'required': ['action'], 'additionalProperties': False},
    ),
    ToolSpec(
        name='macro_list',
        effects=('observe',),
        zone='Z5',
        description='List saved macros (name, description, target window, step count).',
        read_only=True,
        schema={'type': 'object', 'properties': {}},
    ),
    ToolSpec(
        name='macro_save',
        effects=('file_write',),
        zone='Z5',
        description="Save a macro. Steps use window-relative 'rel':[dx,dy] coordinates and can carry 'expect':{'changed':true,'timeout_ms':1200} to verify the step actually did something.",
        read_only=False,
        schema={'type': 'object', 'properties': {'spec': {'type': 'object', 'description': '{name, description?, window:{title_contains|process}, steps:[...]}', 'additionalProperties': True}}, 'required': ['spec']},
    ),
    ToolSpec(
        name='set_baseline',
        effects=('file_write',),
        zone='Z5',
        description='Remember what a screen region normally looks like. diff_baseline later reports how far the current pixels deviate - precise and cheap, and scoped to just that region.',
        read_only=False,
        schema={'type': 'object', 'properties': {'name': {'type': 'string'}, 'x': {'type': 'integer'}, 'y': {'type': 'integer'}, 'w': {'type': 'integer'}, 'h': {'type': 'integer'}, 'hwnd': {'type': 'integer'}}, 'required': ['name', 'x', 'y', 'w', 'h']},
    ),
    ToolSpec(
        name='vision_list',
        effects=('observe',),
        zone='Z5',
        description='List stored templates and baselines (name, source region, size, creation time), plus live run statistics: calls, failures, retries, failure_rate. Use stats to spot a long automation that silently stopped working.',
        read_only=True,
        schema={'type': 'object', 'properties': {'reset_stats': {'type': 'boolean', 'default': False}, 'delete': {'type': 'string', 'description': 'Optional template name to delete'}}},
    ),
]
