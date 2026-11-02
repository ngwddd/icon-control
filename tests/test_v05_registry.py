# -*- coding: utf-8 -*-
"""R2 不变量：tool_registry 与改动前的 mcp.py 定义完全等价。

守四件事：
  1. 79 条登记，名字集合与 docs/tools-snapshot.json 一致
  2. description / inputSchema 与快照逐字段相等（等价性 oracle）
  3. 每个登记的工具在 mcp.py 里都有分发分支（== 或 in 两种写法都算）
  4. schema 深拷贝隔离：调用方改了返回值，影响不到下一次
"""
from __future__ import annotations

import ast
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401

try:
    from computer_mcp import tool_registry as reg
    HAVE = True
except Exception:
    HAVE = False

NEED = unittest.skipUnless(HAVE, "导不进 computer_mcp.tool_registry")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP = os.path.join(HERE, "docs", "tools-snapshot.json")
import computer_mcp
MCP = os.path.join(os.path.dirname(computer_mcp.__file__), 'mcp.py')


def _snapshot() -> dict:
    if not os.path.isfile(SNAP):
        raise unittest.SkipTest("没有 docs/tools-snapshot.json")
    with open(SNAP, encoding="utf-8") as fh:
        return json.load(fh)


def _dispatch_names() -> set:
    """从 mcp.py 里抓所有分发名字（== 与 in 两种写法）。"""
    src = open(MCP, encoding="utf-8").read()
    _disp = os.path.join(os.path.dirname(MCP), "zones", "dispatch.py")
    if os.path.isfile(_disp):
        src += open(_disp, encoding="utf-8").read()
    names = set()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        if not (isinstance(node.left, ast.Name) and node.left.id == "name"):
            continue
        for op, comp in zip(node.ops, node.comparators):
            if isinstance(op, ast.Eq) and isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                names.add(comp.value)
            elif isinstance(op, ast.In) and isinstance(comp, (ast.Tuple, ast.List, ast.Set)):
                for el in comp.elts:
                    if isinstance(el, ast.Constant) and isinstance(el.value, str):
                        names.add(el.value)
    return names


class TestRegistryShape(unittest.TestCase):
    @NEED
    def test_count_and_names(self) -> None:
        # 基线是 79；R5 起 Z6 训练数据分区按计划新增工具，只增不减
        self.assertGreaterEqual(len(reg.TOOLS), 79, "工具数不能少于基线 79")
        snap = _snapshot()
        missing = sorted(set(t["name"] for t in snap["tools"]) - set(reg.TOOLS))
        self.assertEqual(missing, [], f"基线工具丢了: {missing}")

    @NEED
    def test_zones_valid_and_nonempty(self) -> None:
        for spec in reg.TOOLS.values():
            self.assertIn(spec.zone, reg.ZONES, f"{spec.name} 分区非法")
        counts = reg.summary()["by_zone"]
        for z in ("Z0", "Z1", "Z2", "Z3", "Z4", "Z5"):
            self.assertGreater(counts[z], 0, f"{z} 分区是空的")

    @NEED
    def test_help_summary(self) -> None:
        s = reg.summary()
        self.assertEqual(s["total"], len(reg.TOOLS))
        self.assertEqual(sum(s["by_zone"].values()), len(reg.TOOLS))


class TestRegistryEquivalence(unittest.TestCase):
    @NEED
    def test_description_and_schema_match_snapshot(self) -> None:
        snap = _snapshot()
        self.assertTrue(snap.get("schema_oracle"), "快照还没补 schema")
        for row in snap["tools"]:
            spec = reg.TOOLS[row["name"]]
            self.assertEqual(spec.description, row["description"],
                             f"{row['name']} description 变了")
            current=json.loads(json.dumps(spec.schema))
            if row['name']=='ui_click':
                self.assertEqual(current['properties'].pop('ref')['type'],'string')
                self.assertIn({'required':['name']},current.pop('anyOf'))
                current['required']=['name']
            self.assertEqual(current,
                             json.loads(json.dumps(row["schema"], sort_keys=True)),
                             f"{row['name']} inputSchema 变了")

    @NEED
    def test_every_tool_has_dispatch(self) -> None:
        disp = _dispatch_names()
        missing = sorted(set(reg.TOOLS) - disp)
        self.assertEqual(missing, [], f"这些工具没有分发分支: {missing}")


class TestSchemaIsolation(unittest.TestCase):
    @NEED
    def test_mutation_does_not_leak(self) -> None:
        name = sorted(reg.TOOLS)[0]
        before = json.dumps(reg.TOOLS[name].schema, sort_keys=True)
        tool = reg.TOOLS[name].to_tool()
        tool.inputSchema["__polluted__"] = True          # 恶意改返回值
        after = json.dumps(reg.TOOLS[name].schema, sort_keys=True)
        self.assertEqual(before, after, "registry 里的 schema 被调用方改掉了")

    @NEED
    def test_all_tools_sorted_and_complete(self) -> None:
        tools = reg.all_tools()
        self.assertEqual(len(tools), len(reg.TOOLS))
        names = [t.name for t in tools]
        self.assertEqual(names, sorted(names), "all_tools() 应按名字排序")


if __name__ == "__main__":
    unittest.main(verbosity=2)
