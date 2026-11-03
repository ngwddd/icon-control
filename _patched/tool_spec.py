"""tool_spec.py — 工具定义的数据结构（R3 抽出，避免循环导入）。

只描述「是什么」，不含「怎么执行」。执行在 call_tool / zones/*/dispatch.py。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field


def micro_effects(ops, depth=0):
    """Mirror the micro runner grammar, including both conditional branches."""
    if depth > 8 or not isinstance(ops, list):
        raise ValueError("Invalid micro instruction list")
    effects = {"compose", "screen_read"}  # The runner obtains a frame on entry.
    for step in ops:
        if not isinstance(step, dict) or not isinstance(step.get("op"), str):
            raise ValueError("Invalid micro instruction")
        kind = step["op"].lower()
        if kind in {"key", "press", "walk_or_turn"}:
            effects.update(("input", "text_entry"))
        elif kind in {"move", "turn", "scroll", "click"}:
            effects.add("input")
        elif kind in {"if", "until"}:
            for field in (("then", "else") if kind == "if" else ("do",)):
                effects.update(micro_effects(step.get(field, []), depth + 1))
        elif kind not in {"sleep", "log"}:
            raise ValueError("Unknown micro instruction: " + kind)
    return tuple(sorted(effects))


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
    parameter_effects: tuple = ()

    def __post_init__(self):
        supported={'observe','input','compose','window','process','control','capture',
                   'clipboard_write','file_write','file_delete','config_write',
                   'screen_read','text_entry','window_close'}
        if not isinstance(self.effects,tuple) or not self.effects or not set(self.effects)<=supported:
            raise ValueError(f'{self.name}: explicit nonempty supported effects are required')
        for key,effects in self.parameter_effects:
            if not isinstance(key,str) or not effects or not set(effects)<=set(self.effects):
                raise ValueError(f'{self.name}: invalid parameter-dependent effect declaration')

    def effects_for(self, arguments=None):
        if arguments is None:
            return self.effects
        if not isinstance(arguments,dict):
            raise ValueError('Tool arguments must be an object')
        if self.name == 'run_script' and ('ops' in arguments or 'steps' in arguments):
            return micro_effects(arguments.get('ops') or arguments.get('steps') or [])
        if self.parameter_effects:
            chosen = tuple(dict.fromkeys(effect for key,effects in self.parameter_effects
                if arguments.get(key) for effect in effects))
            return chosen or ('observe',)
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
