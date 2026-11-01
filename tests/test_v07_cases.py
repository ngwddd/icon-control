# -*- coding: utf-8 -*-
"""R7：把 dataset/cases/*.json 当成回归用例复跑。

默认跳过（需要真实桌面状态）；CI 里设 DSH_RUN_CASES=1 才跑。
断言：样本里记录的 args 再调一次，结果不应是 failed/error/denied。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401

RUN = os.environ.get("DSH_RUN_CASES") == "1"

try:
    from computer_mcp.dataset import promote
    from computer_mcp import mcp as M
    HAVE = True
except Exception:
    HAVE = False

NEED = unittest.skipUnless(HAVE and RUN, "需要 DSH_RUN_CASES=1 且能导入 computer_mcp")


def _text(resp) -> str:
    return "\n".join(getattr(c, "text", "") for c in resp if getattr(c, "text", None))


class TestPromotedCases(unittest.TestCase):
    @NEED
    def test_all_cases_still_behave(self) -> None:
        cases = promote.list_cases()
        self.assertGreater(len(cases), 0, "还没有任何 case")
        from computer_mcp.dataset import schema

        for name in cases:
            path = promote.CASES / name
            case = json.loads(path.read_text(encoding="utf-8"))
            resp = asyncio.run(M.call_tool(case["tool"], case.get("args") or {}))
            verdict = schema.ok_of(_text(resp))
            with self.subTest(case=case["case_id"]):
                self.assertNotEqual(verdict, False,
                                    f"{case['case_id']} 仍然失败")
