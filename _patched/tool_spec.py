"""tool_spec.py — 工具定义的数据结构（R3 抽出，避免循环导入）。

只描述「是什么」，不含「怎么执行」。执行在 call_tool / zones/*/dispatch.py。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolSpec:
    name: str
    zone: str
    description: str
    schema: dict
    read_only: bool = False
    aliases: tuple = field(default=())
    effects: tuple | None = None

    def __post_init__(self):
        if self.effects is None:
            effect = ('input',) if self.zone == 'Z3' else (('compose',) if self.zone == 'Z4' and not self.read_only else
                     (('file_write',) if not self.read_only else ('observe',)))
            overrides = {
                'housekeeping': ('file_delete',), 'set_config': ('config_write',),
                'capture_config': ('config_write',), 'anchor_mem': ('file_write',),
                'layout_mem': ('file_write',), 'snapshot': ('file_write',),
                'frame_mark': ('file_write',), 'probe': ('file_write',),
                'control_claim': ('control',), 'verify_flow': ('file_write',),
            }
            if self.zone == 'Z3' and ('window' in self.name or 'desktop' in self.name):
                effect = ('window',)
            object.__setattr__(self, 'effects', overrides.get(self.name, effect))

    @property
    def requires_authority(self):
        return any(effect != 'observe' for effect in self.effects)

    def to_tool(self):
        """构造 MCP 的 Tool 对象（每次深拷贝，避免共享可变 dict）。"""
        from mcp.types import Tool

        return Tool(name=self.name, description=self.description,
                    inputSchema=copy.deepcopy(self.schema))
