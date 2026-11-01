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

    def to_tool(self):
        """构造 MCP 的 Tool 对象（每次深拷贝，避免共享可变 dict）。"""
        from mcp.types import Tool

        return Tool(name=self.name, description=self.description,
                    inputSchema=copy.deepcopy(self.schema))
