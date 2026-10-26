# -*- coding: utf-8 -*-
"""v0.4 新架构的单测：采集守护 / 感知原语 / 数字识别 / 微脚本解释器。

一律用**合成图像**和**假的键鼠**，不碰真实屏幕、不点鼠标：
    · 原语：给定像素，答案必须确定
    · 数字：用内置 5×7 字体渲染 0-9，再读回来，必须逐字相等
    · 解释器：用假 daemon + 假键盘，验证 loop/until/if 的语义与预算保护
"""
from __future__ import annotations

import os
import sys
import time
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "venv", "Lib", "site-packages"))

try:
    from computer_mcp import perceive, digits, micro
    from computer_mcp.capture_daemon import CaptureDaemon, Frame
    from computer_mcp import live
    HAVE = True
except Exception:
    HAVE = False

NEED = unittest.skipUnless(HAVE, "导不进 computer_mcp（需要 venv）")


def blank(w=200, h=100, color=(0, 0, 0)) -> np.ndarray:
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :] = color
    return img


def draw_text(img, text, x, y, color=(235, 235, 235), scale=3):
    """用内置 5×7 字体在图上"画"字（测试用，不依赖字体文件）。"""
    font = digits.BUILTIN
    cx = x
    for ch in text:
        if ch == " ":
            cx += 4 * scale
            continue
        bmp = font.get(ch)
        if bmp is None:
            cx += 6 * scale
            continue
        for r in range(bmp.shape[0]):
            for c in range(bmp.shape[1]):
                if bmp[r, c]:
                    img[y + r * scale:y + (r + 1) * scale,
                        cx + c * scale:cx + (c + 1) * scale] = color
        cx += 6 * scale
    return cx


def draw_strokes(img, x, y, strokes=8, sw=4, sh=18, gap=6, color=(235, 235, 235)):
    """画一排竖条 —— 用来模拟"一行亮字"（内置字体只有数字，画不了字母）。"""
    cx = x
    for _ in range(strokes):
        img[y:y + sh, cx:cx + sw] = color
        cx += sw + gap
    return cx


class TestPrimitives(unittest.TestCase):
    @NEED
    def test_prompt_hit_and_miss(self) -> None:
        img = blank()
        draw_strokes(img, 20, 30)
        hit = perceive.probe_prompt(img, (0, 0, 200, 100))
        self.assertTrue(hit["hit"])
        self.assertGreater(hit["ratio"], 0.01)

        miss = perceive.probe_prompt(blank(), (0, 0, 200, 100))
        self.assertFalse(miss["hit"])
        self.assertEqual(miss["count"], 0)

    @NEED
    def test_bar_fill(self) -> None:
        img = blank(200, 40)
        img[10:30, 0:100] = (46, 160, 67)          # 左半满
        r = perceive.probe_bar(img, (0, 0, 200, 40), color="green", tol=40)
        self.assertAlmostEqual(r["fill"], 0.5, delta=0.06)

        empty = perceive.probe_bar(blank(200, 40), (0, 0, 200, 40), color="green")
        self.assertEqual(empty["fill"], 0.0)

    @NEED
    def test_openness(self) -> None:
        bright = blank(100, 100, (60, 60, 60))
        dark = blank(100, 100, (5, 5, 5))
        self.assertGreater(perceive.probe_openness(bright, (0, 0, 100, 100))["score"],
                           perceive.probe_openness(dark, (0, 0, 100, 100))["score"])

    @NEED
    def test_color_blob(self) -> None:
        img = blank(120, 120)
        img[40:60, 50:70] = (200, 60, 50)           # 红块
        r = perceive.probe_color_blob(img, (0, 0, 120, 120), color="red", tol=40)
        self.assertTrue(r["hit"])
        self.assertEqual(r["count"], 400)
        x, y, w, h = r["bbox"]
        self.assertEqual((x, y, w, h), (50, 40, 20, 20))

    @NEED
    def test_locate_rows_finds_two_lines(self) -> None:
        img = blank(300, 160)
        draw_text(img, "123", 10, 20, color=(80, 220, 220))
        draw_text(img, "456", 10, 80, color=(80, 220, 220))
        rows = perceive.locate_rows(img, (0, 0, 300, 160), color="cyan", tol=70, min_px=4)
        self.assertGreaterEqual(len(rows), 2, rows)
        self.assertLess(rows[0]["y0"], rows[-1]["y0"])

    @NEED
    def test_diff_region(self) -> None:
        a = blank(); b = a.copy()
        self.assertFalse(perceive.diff_region(a, b)["changed"])
        b[10:40, 10:40] = 255
        self.assertTrue(perceive.diff_region(a, b)["changed"])


class TestDigits(unittest.TestCase):
    @NEED
    def test_read_rendered_digits(self) -> None:
        """渲染 "0123456789"，必须逐字读对（这是模板匹配的下限能力）。"""
        img = blank(700, 60)
        draw_text(img, "0123456789", 10, 10, scale=4)
        r = digits.read_digits(img, (0, 0, 700, 60), thr=140)
        self.assertEqual(r["text"], "0123456789", r)
        self.assertGreater(r["confidence"], 0.9)

    @NEED
    def test_read_two_digit_number(self) -> None:
        img = blank(200, 60)
        draw_text(img, "99", 10, 10, scale=4)
        r = digits.read_digits(img, (0, 0, 200, 60), thr=140)
        self.assertEqual(r["text"], "99", r)

    @NEED
    def test_learn_roundtrip(self) -> None:
        """教一个字形后，能匹配回来；教完清理，不污染真实模板库。"""
        img = blank(80, 60)
        draw_text(img, "7", 10, 10, scale=5)
        try:
            lr = digits.learn("7", img, (0, 0, 80, 60), thr=140)
            self.assertTrue(lr["ok"])
            self.assertGreaterEqual(lr["learned_total"], 1)
            r = digits.read_digits(img, (0, 0, 80, 60), thr=140)
            self.assertEqual(r["text"], "7")
        finally:
            digits.clear_learned()

    @NEED
    def test_empty_region(self) -> None:
        r = digits.read_digits(blank(), (0, 0, 50, 50))
        self.assertEqual(r["text"], "")
        self.assertEqual(r["confidence"], 0.0)


class FakeDaemon:
    """给解释器用的假采集器：帧内容由测试控制。"""

    def __init__(self, img):
        self.img = img
        self.scale = 1.0
        self.origin = (0, 0)
        self._f = Frame(idx=1, ts=time.time(), img=img)

    def latest(self):
        self._f = Frame(idx=self._f.idx + (0), ts=time.time(), img=self.img)
        return self._f

    def get(self, idx):
        return self._f

    def frames_between(self, idx):
        return []


class FakeKB:
    def __init__(self):
        self.pressed = []

    def press(self, k):
        self.pressed.append(("down", k))

    def release(self, k):
        self.pressed.append(("up", k))


class FakeMS:
    def __init__(self):
        self.moves = []
        self.position = (0, 0)

    def move(self, dx, dy):
        self.moves.append((dx, dy))

    def click(self, *a, **kw):
        self.moves.append("click")


class TestMicroInterpreter(unittest.TestCase):
    @NEED
    def test_key_actions_recorded(self) -> None:
        d = FakeDaemon(blank())
        kb, ms = FakeKB(), FakeMS()
        r = micro.Runner(d, kb, ms, 1.0, (0, 0), 5)
        r.run([{"op": "key", "key": "w", "hold_ms": 20},
               {"op": "turn", "px": 30}])
        self.assertEqual(kb.pressed, [("down", "w"), ("up", "w")])
        self.assertEqual(ms.moves, [(30, 0)])
        self.assertEqual(r.result()["steps"], 2)

    @NEED
    def test_loop_times(self) -> None:
        d = FakeDaemon(blank())
        r = micro.Runner(d, FakeKB(), FakeMS(), 1.0, (0, 0), 5)
        r.run([{"op": "loop", "times": 3, "do": [{"op": "key", "key": "a", "hold_ms": 1}]}])
        self.assertEqual(r.result()["steps"], 4)     # 1 loop + 3 body

    @NEED
    def test_if_branches_on_condition(self) -> None:
        img = blank()
        draw_strokes(img, 10, 20)
        d = FakeDaemon(img)
        r = micro.Runner(d, FakeKB(), FakeMS(), 1.0, (0, 0), 5)
        r.run([{"op": "if",
                "cond": {"kind": "prompt", "box": [0, 0, 200, 100]},
                "then": [{"op": "log", "text": "有提示"}],
                "else": [{"op": "log", "text": "没提示"}]}])
        texts = [t.get("text") for t in r.result()["trace"] if t.get("op") == "log"]
        self.assertIn("有提示", texts)

    @NEED
    def test_until_stops_when_condition_true(self) -> None:
        img = blank()
        draw_strokes(img, 10, 20)
        d = FakeDaemon(img)
        r = micro.Runner(d, FakeKB(), FakeMS(), 1.0, (0, 0), 5)
        r.run([{"op": "until",
                "cond": {"kind": "prompt", "box": [0, 0, 200, 100]},
                "timeout_ms": 500,
                "do": [{"op": "sleep", "ms": 10}]}])
        logs = [t.get("text", "") for t in r.result()["trace"]]
        self.assertTrue(any("until 命中" in x for x in logs), logs)

    @NEED
    def test_budget_guard(self) -> None:
        d = FakeDaemon(blank())
        r = micro.Runner(d, FakeKB(), FakeMS(), 1.0, (0, 0), 0.15)
        r.run([{"op": "loop", "times": 100, "do": [{"op": "sleep", "ms": 5}]}])
        res = r.result()
        self.assertTrue(res["stopped"])
        self.assertIn("最大", res["stop_reason"])

    @NEED
    def test_to_frame_box_scaling(self) -> None:
        box = micro.to_frame_box([100, 200, 40, 20], 0.5, (0, 0))
        self.assertEqual(box, (50, 100, 20, 10))
        box2 = micro.to_frame_box([100, 200, 40, 20], 0.5, (100, 200))
        self.assertEqual(box2, (0, 0, 20, 10))


class TestDaemonBasics(unittest.TestCase):
    @NEED
    def test_start_status_stop(self) -> None:
        d = CaptureDaemon(scale=0.25, active_fps=8, idle_fps=2, max_frames=20)
        st = d.start()
        self.assertTrue(st["ok"])
        time.sleep(0.6)
        s = d.status()
        self.assertTrue(s["running"])
        self.assertGreater(s["frames"], 0)
        self.assertIsNotNone(d.latest())
        d.stop()
        self.assertFalse(d.status()["running"])

    @NEED
    def test_frame_summary_shape(self) -> None:
        d = CaptureDaemon(scale=0.25, active_fps=8, idle_fps=2, max_frames=10)
        try:
            d.start()
            time.sleep(0.5)
            f = d.latest()
            if f is None:
                self.skipTest("本机抓不到屏幕")
            summ = f.summary()
            for k in ("idx", "ts", "diff", "bbox", "active_window"):
                self.assertIn(k, summ)
        finally:
            d.stop()

    @NEED
    def test_wait_times_out(self) -> None:
        d = CaptureDaemon(scale=0.25, active_fps=8, idle_fps=2, max_frames=10)
        try:
            d.start()
            hit, fr = d.wait(lambda f: False, timeout_ms=200)
            self.assertFalse(hit)
        finally:
            d.stop()


class TestLiveSurface(unittest.TestCase):
    @NEED
    def test_capture_tool_contract(self) -> None:
        r = live.tool_capture({"action": "status"})
        self.assertTrue(r["success"])
        self.assertIn("running", r)
        r2 = live.tool_capture({"action": "start", "scale": 0.25, "active_fps": 8, "idle_fps": 2})
        self.assertTrue(r2["success"])
        self.assertIn("frames", r2)

    @NEED
    def test_run_script_rejects_empty(self) -> None:
        r = live.tool_run_script({"ops": []})
        self.assertFalse(r["success"])

    @NEED
    def test_snapshot_writes_file(self) -> None:
        r = live.tool_snapshot({"region": [0, 0, 120, 80], "scale": 1.0})
        if not r.get("success"):
            self.skipTest("本机抓不到屏幕")
        self.assertTrue(os.path.isfile(r["path"]))
        self.assertEqual(r["size"], [120, 80])
        os.remove(r["path"])


if __name__ == "__main__":
    unittest.main()
