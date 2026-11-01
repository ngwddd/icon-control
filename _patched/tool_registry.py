"""tool_registry.py — 工具清单聚合层（R3）

定义在 `zones/*/tools.py`，这里只做聚合与查询。
`TOOLS` 是唯一索引；`all_tools()` 按名字排序，保证输出稳定。
"""

from __future__ import annotations

import os

from typing import Iterator

from computer_mcp.tool_spec import ToolSpec
from computer_mcp.zones.aliases import ALIASES

ZONES = ("Z0", "Z1", "Z2", "Z3", "Z4", "Z5", "Z6")

ZONE_NAMES = {
    "Z0": "治理",
    "Z1": "采集",
    "Z2": "判据",
    "Z3": "动作",
    "Z4": "编排",
    "Z5": "资产",
    "Z6": "训练数据",
}

from computer_mcp.zones.z0_governance.tools import SPECS as Z0_SPECS
from computer_mcp.zones.z1_capture.tools import SPECS as Z1_SPECS
from computer_mcp.zones.z2_sense.tools import SPECS as Z2_SPECS
from computer_mcp.zones.z3_act.tools import SPECS as Z3_SPECS
from computer_mcp.zones.z4_compose.tools import SPECS as Z4_SPECS
from computer_mcp.zones.z5_memory.tools import SPECS as Z5_SPECS
from computer_mcp.zones.z6_learning.tools import SPECS as Z6_SPECS

_ALL_SPECS: list[ToolSpec] = []
_ALL_SPECS.extend(Z0_SPECS)
_ALL_SPECS.extend(Z1_SPECS)
_ALL_SPECS.extend(Z2_SPECS)
_ALL_SPECS.extend(Z3_SPECS)
_ALL_SPECS.extend(Z4_SPECS)
_ALL_SPECS.extend(Z5_SPECS)
_ALL_SPECS.extend(Z6_SPECS)

TOOLS: dict[str, ToolSpec] = {s.name: s for s in _ALL_SPECS}


def get(name: str):
    return TOOLS.get(name)


def _csv(env: str) -> set:
    raw = os.environ.get(env, "") or ""
    return {x.strip() for x in raw.split(",") if x.strip()}


def _allowed(name: str) -> bool:
    """DSH_TOOLS_ALLOW / DSH_TOOLS_DENY 过滤（P0-4）。

    只影响**模型能看到什么**，不影响内部调用（宏、测试、脚本仍可直接用名字）。
    """
    allow, deny = _csv("DSH_TOOLS_ALLOW"), _csv("DSH_TOOLS_DENY")
    if allow and name not in allow:
        return False
    if name in deny:
        return False
    return True


def all_tools() -> list:
    """按名字排序返回已启用的 Tool（稳定顺序）。"""
    return [TOOLS[n].to_tool() for n in sorted(TOOLS) if _allowed(n)]


def disabled() -> list:
    """被白黑名单挡掉的工具名（给 dataset_status / 诊断用）。"""
    return [n for n in sorted(TOOLS) if not _allowed(n)]


def by_zone(zone: str) -> list:
    return [s for s in TOOLS.values() if s.zone == zone]


def resolve(name: str):
    """名字或别名 → 规范名。"""
    if name in TOOLS:
        return name
    for spec in TOOLS.values():
        if name in spec.aliases:
            return spec.name
    return None


def iter_specs() -> Iterator[ToolSpec]:
    for n in sorted(TOOLS):
        yield TOOLS[n]


def summary() -> dict:
    counts = {z: 0 for z in ZONES}
    for s in TOOLS.values():
        counts[s.zone] = counts.get(s.zone, 0) + 1
    return {
        "total": len(TOOLS),
        "by_zone": counts,
        "zone_names": ZONE_NAMES,
        "read_only": sum(1 for s in TOOLS.values() if s.read_only),
        "aliased": sum(1 for s in TOOLS.values() if s.aliases),
    }

# 别名索引：旧名 → 规范名（不额外注册工具，只做解析）
def alias_of(name: str):
    return ALIASES.get(name)


def zone_of(name: str) -> str:
    """任意名字（含别名）→ 分区。查不到返回 "?"。"""
    spec = TOOLS.get(name)
    if spec is None:
        back = {v: k for k, v in ALIASES.items()}      # 新名 → 旧名
        spec = TOOLS.get(back.get(name, ''))
    return spec.zone if spec else '?'
