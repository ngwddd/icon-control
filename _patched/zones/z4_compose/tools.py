"""zones/z4_compose/tools.py — 编排：脚本、宏、闭环、导航、验证（Z4）

自动生成（R3）：定义与实现在一起，schema 是唯一来源。
不要手改生成标记之间的内容之外的 schema 结构；改工具请改本文件后跑测试。
"""

from __future__ import annotations

from computer_mcp.tool_spec import ToolSpec

SPECS: list[ToolSpec] = [
    ToolSpec(
        name='act_until',
        effects=('compose',),
        zone='Z4',
        description='Repeat one action until a condition holds (walk until a prompt appears). Shorthand for one until-loop.',
        read_only=False,
        schema={'type': 'object', 'properties': {'action': {'type': 'object'}, 'cond': {'type': 'object'}, 'max_ms': {'type': 'integer'}}, 'additionalProperties': False},
    ),
    ToolSpec(
        name='batch',
        effects=('compose',),
        zone='Z4',
        description="Run a whole gesture sequence in ONE call. Each step: {action:'move'|'click'|'double_click'|'right_click'|'type'|'key'|'sleep'|'wait_change'|'screen_state'|'ui_click', ...}. Use this instead of many separate calls (each separate call costs a model round trip).",
        read_only=False,
        schema={'type': 'object', 'properties': {'steps': {'type': 'array', 'description': 'Ordered steps', 'items': {'type': 'object', 'additionalProperties': True}}, 'stop_on_error': {'type': 'boolean', 'default': True}, 'default_sleep_ms': {'type': 'integer', 'default': 120}}, 'required': ['steps']},
    ),
    ToolSpec(
        name='macro_run',
        effects=('compose','input',),
        zone='Z4',
        description="Replay a saved macro in ONE call. Coordinates are re-based onto the target window's current position. Use dry_run=true to see resolved absolute coordinates without clicking.",
        read_only=False,
        schema={'type': 'object', 'properties': {'name': {'type': 'string'}, 'params': {'type': 'object', 'description': 'Values for ${placeholders}'}, 'dry_run': {'type': 'boolean', 'default': False}, 'default_gap_ms': {'type': 'integer', 'default': 140}}, 'required': ['name']},
    ),
    ToolSpec(
        name='navigate',
        effects=('compose',),
        zone='Z4',
        description='M3: run a plan locally at 20+ Hz and come back only on success or stall. plan=[{kind:goto,cell:[c,r]}|{kind:search}|{kind:face,cell}|{kind:wait,ms}|{kind:key,key}]. Returns a short state page, so one call can cover a whole objective.',
        read_only=False,
        schema={'type': 'object', 'properties': {'plan': {'type': 'array', 'items': {'type': 'object'}}, 'map_region': {'type': 'array', 'items': {'type': 'integer'}}, 'prompt_box': {'type': 'array', 'items': {'type': 'integer'}}, 'max_seconds': {'type': 'number'}}, 'required': ['plan'], 'additionalProperties': False},
    ),
    ToolSpec(
        name='run_script',
        effects=('compose','input','screen_read',),
        zone='Z4',
        description='Execute a micro-script locally in ONE call (closed loop): ops = key/press/turn/move/click/scroll/sleep/loop/if/until/log. A 40-step navigation loop costs one round trip. Returns a trace.',
        read_only=False,
        schema={'type': 'object', 'properties': {'ops': {'type': 'array', 'items': {'type': 'object'}}, 'steps': {'type': 'array', 'items': {'type': 'object'}}, 'max_seconds': {'type': 'number'}}, 'additionalProperties': False},
    ),
    ToolSpec(
        name='servo',
        effects=('compose',),
        zone='Z4',
        description='M2: closed-loop servo toward a map cell. op=calibrate (estimate heading by stepping and watching the minimap displacement) | face | approach | forward | turn. Recomputes bearing every step instead of walking blind.',
        read_only=False,
        schema={'type': 'object', 'properties': {'op': {'type': 'string', 'enum': ['calibrate', 'face', 'approach', 'forward', 'turn']}, 'cell': {'type': 'array', 'items': {'type': 'integer'}, 'description': '[col, row] map cell'}, 'map_region': {'type': 'array', 'items': {'type': 'integer'}}, 'prompt_box': {'type': 'array', 'items': {'type': 'integer'}}, 'max_steps': {'type': 'integer'}, 'tol_cells': {'type': 'number'}, 'ms': {'type': 'number'}, 'px': {'type': 'integer'}, 'px_per_deg': {'type': 'number'}, 'tap_ms': {'type': 'number'}}, 'required': ['op'], 'additionalProperties': False},
    ),
    ToolSpec(
        name='trace',
        effects=('screen_read',),
        zone='Z4',
        description='Return the trace of the last run_script, or the run history.',
        read_only=True,
        schema={'type': 'object', 'properties': {'history': {'type': 'boolean'}}, 'additionalProperties': False},
    ),
    ToolSpec(
        name='verify_flow',
        effects=('screen_read', 'file_read', 'file_write'),
        zone='Z4',
        description='Run staged verification and return per-stage evidence. Each stage may wait, then run assertions: kind=text|template|baseline|stable|file. Stages stop at the first failure (stop_on_fail) and the report can be written to a JSON file. Verification only - it performs no input actions.',
        read_only=False,
        schema={'type': 'object', 'properties': {'stages': {'type': 'array', 'description': 'Ordered stages: {name, wait_ms?, assert:[{kind, ...}]}', 'items': {'type': 'object', 'additionalProperties': True}}, 'stop_on_fail': {'type': 'boolean', 'default': True}, 'report_path': {'type': 'string', 'description': 'Optional JSON report path'}}, 'required': ['stages']},
    ),
    ToolSpec(
        name='execute_verified',
        effects=('input', 'text_entry'),
        zone='Z4',
        description='一次调用完成：定位 → 执行 → 等到后置条件成立 → 报告是否真的生效',
        read_only=False,
        schema={'type': 'object', 'properties': {
            'query': {'type': 'string'},
            'ref': {'type': 'string'},
            'hwnd': {'type': 'integer'},
            'action': {'type': 'string',
                       'enum': ['click', 'invoke', 'set_value', 'toggle', 'select', 'type'],
                       'default': 'click'},
            'value': {'type': 'string'},
            'expect': {'type': 'object', 'description': '后置条件：{kind: value|contains|text|absent, text}',
                       'properties': {'kind': {'type': 'string',
                                               'enum': ['value', 'contains', 'text', 'absent']},
                                      'text': {'type': 'string'}}},
            'timeout_ms': {'type': 'integer', 'default': 3000},
            'settle_ms': {'type': 'integer', 'default': 120},
            'scan_max_nodes': {'type': 'integer', 'default': 400,
                               'description': '检查"不存在"时最多读多少个控件；被截断的扫描不能证明不存在'},
        }, 'required': ['action']},
    ),

]
