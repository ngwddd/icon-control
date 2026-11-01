"""zones/z6_learning/tools.py — 训练数据分区（Z6）

四个工具：status / query / promote / export。
刻意**不提供**「删除全部」——清理由保留策略负责，避免模型误删训练资产。
"""

from __future__ import annotations

from computer_mcp.tool_spec import ToolSpec

SPECS: list[ToolSpec] = [
    ToolSpec(
        name='dataset_status',
        zone='Z6',
        description='训练数据分区状态：是否开启、今日/累计样本数、占用体积、最近一条样本',
        read_only=True,
        schema={'type': 'object', 'properties': {}},
    ),
    ToolSpec(
        name='dataset_query',
        zone='Z6',
        description='按工具/分区/结果/天数筛训练样本（只读，默认返回最新 20 条）',
        read_only=True,
        schema={
            'type': 'object',
            'properties': {
                'tool': {'type': 'string', 'description': '工具名，如 click'},
                'zone': {'type': 'string', 'enum': ['Z0', 'Z1', 'Z2', 'Z3', 'Z4', 'Z5', 'Z6']},
                'verdict': {'type': 'string', 'enum': ['success', 'failed', 'denied', 'error', 'unknown']},
                'days': {'type': 'integer', 'description': '只查最近 N 天'},
                'limit': {'type': 'integer', 'default': 20},
                'group_by': {'type': 'string', 'enum': ['tool', 'zone', 'verdict']},
            },
        },
    ),
    ToolSpec(
        name='dataset_promote',
        zone='Z6',
        description='把某条样本提升为回归用例（写 dataset/cases/，供反复验证）',
        read_only=False,
        schema={
            'type': 'object',
            'properties': {
                'episode_id': {'type': 'string', 'description': '样本 id（dataset_query 里能看到）'},
                'note': {'type': 'string', 'description': '备注：为什么这条值得回归'},
            },
            'required': ['episode_id'],
        },
    ),
    ToolSpec(
        name='dataset_export',
        zone='Z6',
        description='把最近 N 天的样本打包成 zip（离线回流/微调用），默认 7 天',
        read_only=False,
        schema={
            'type': 'object',
            'properties': {
                'days': {'type': 'integer', 'default': 7},
                'tag': {'type': 'string', 'description': '子目录名，默认 YYYY-W周'},
            },
        },
    ),

    ToolSpec(
        name='dataset_triage',
        zone='Z6',
        description='分拣失败样本：同类失败达到阈值就自动生成回归用例（默认 1 天 / 3 次）',
        read_only=False,
        schema={
            'type': 'object',
            'properties': {
                'days': {'type': 'integer', 'default': 1},
                'min_count': {'type': 'integer', 'default': 3},
                'dry_run': {'type': 'boolean', 'default': False},
            },
        },
    ),

    ToolSpec(
        name='dataset_explore',
        zone='Z6',
        description='随机游走采集弱语义轨迹（只调用只读工具，不点击不输入），样本打 explore 标签',
        read_only=False,
        schema={
            'type': 'object',
            'properties': {
                'steps': {'type': 'integer', 'default': 12},
                'interval_ms': {'type': 'integer', 'default': 400},
                'seed': {'type': 'integer'},
            },
        },
    ),
]
