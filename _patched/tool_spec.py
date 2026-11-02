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
    effects: tuple
    read_only: bool = False
    aliases: tuple = field(default=())
    read_actions: tuple = ()
    action_default: str | None = None
    read_when_absent: tuple = ()

    def __post_init__(self):
        supported={'observe','input','compose','window','process','control','capture',
                   'clipboard_write','file_write','file_delete','config_write'}
        if not isinstance(self.effects,tuple) or not self.effects or not set(self.effects)<=supported:
            raise ValueError(f'{self.name}: explicit nonempty supported effects are required')

    def effects_for(self, arguments=None):
        if arguments is None:
            return self.effects
        if not isinstance(arguments,dict):
            raise ValueError('Tool arguments must be an object')
        if self.read_when_absent and not any(k in arguments for k in self.read_when_absent):
            return ('observe',)
        if arguments.get('action',self.action_default) in self.read_actions:
            return ('observe',)
        return self.effects

    def needs_authority(self, arguments=None):
        return any(effect != 'observe' for effect in self.effects_for(arguments))

    @property
    def requires_authority(self):
        return self.needs_authority()

    def to_tool(self):
        """构造 MCP 的 Tool 对象（每次深拷贝，避免共享可变 dict）。"""
        from mcp.types import Tool

        return Tool(name=self.name, description=self.description,
                    inputSchema=copy.deepcopy(self.schema))
