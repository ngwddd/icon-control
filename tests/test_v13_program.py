# -*- coding: utf-8 -*-
"""program.py：指令流的纯逻辑（facts 展开 / 读指令 / 翻译动作）。

守的两条：
    · 引用了不存在的名字必须**报错**，不能拿 None 去点鼠标（会点屏幕左上角）
    · 指令文件要能带注释、要能报出"第几行"，否则出错等于没线索
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "venv", "Lib", "site-packages"))

try:
    from computer_mcp import program as P
    HAVE = True
except Exception:
    HAVE = False

NEED = unittest.skipUnless(HAVE, "导不进 computer_mcp（需要 venv）")

FACTS = {"wx": {"rail": {"discover": [0.0351, 0.359]}, "input": [0.542, 0.9]},
         "stamp": "04:20:00"}


@NEED
class TestExpand(unittest.TestCase):
    def test_ref_value(self) -> None:
        self.assertEqual(P.expand("@wx.rail.discover", FACTS), [0.0351, 0.359])

    def test_nested_dict(self) -> None:
        got = P.expand({"a": "@wx.input", "b": [1, "@wx.input"]}, FACTS)
        self.assertEqual(got["a"], [0.542, 0.9])
        self.assertEqual(got["b"][1], [0.542, 0.9])

    def test_dollar_in_string(self) -> None:
        self.assertEqual(P.expand("验证 $stamp", FACTS), "验证 04:20:00")

    def test_plain_string_untouched(self) -> None:
        self.assertEqual(P.expand("普通文字", FACTS), "普通文字")
        self.assertEqual(P.expand("@不是引用 有空格", FACTS), "@不是引用 有空格")

    def test_missing_name_raises(self) -> None:
        with self.assertRaises(KeyError):
            P.expand("@wx.nope", FACTS)


@NEED
class TestLoadProgram(unittest.TestCase):
    def test_comments_and_blanks(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                         encoding="utf-8") as fh:
            fh.write("# 这是注释\n\n")
            fh.write(json.dumps({"op": "click", "at": "@wx.input"}) + "\n")
            fh.write(json.dumps({"op": "wait", "ms": 10}) + "\n")
            path = fh.name
        try:
            ins = P.load_program(path)
            self.assertEqual(len(ins), 2)
            self.assertEqual(ins[0]["op"], "click")
            self.assertEqual(ins[0]["_line"], 3)
        finally:
            os.unlink(path)

    def test_missing_op(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(json.dumps({"at": [0.1, 0.2]}) + "\n")
            path = fh.name
        try:
            with self.assertRaises(ValueError):
                P.load_program(path)
        finally:
            os.unlink(path)


@NEED
class TestAsAction(unittest.TestCase):
    def test_click_at_becomes_rel(self) -> None:
        self.assertEqual(P._as_action({"op": "click", "at": [0.1, 0.2]})["rel_frac"], [0.1, 0.2])

    def test_click_find_passthrough(self) -> None:
        a = P._as_action({"op": "click", "find": {"text": "发现"}})
        self.assertEqual(a["kind"], "click")
        self.assertEqual(a["find"], {"text": "发现"})

    def test_scroll_default_point(self) -> None:
        a = P._as_action({"op": "scroll", "dy": -300})
        self.assertEqual(a["kind"], "scroll")
        self.assertEqual(a["at_rel_frac"], [0.6, 0.5])

    def test_send_keeps_extra_fields(self) -> None:
        a = P._as_action({"op": "send", "text": "hi", "title_text": "文件传输助手"})
        self.assertEqual(a["kind"], "send")
        self.assertEqual(a["text"], "hi")
        self.assertEqual(a["title_text"], "文件传输助手")

    def test_unknown_op_empty(self) -> None:
        self.assertEqual(P._as_action({"op": "wat"}), {})


if __name__ == "__main__":
    unittest.main()
