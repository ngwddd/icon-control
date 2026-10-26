# -*- coding: utf-8 -*-
"""train.py 的单测：三个轮子的纯逻辑 + 看门狗 + 轨道解析。

守的是这段时间踩过的坑：
    · 块平均降采样（PIL.resize 太慢）
    · 变化块判定（没变就是 0，别误报）
    · 状态机 STABLE/TRANSITION 不能抖动
    · 环形缓冲/事件队列**必须有上限**（用户要求"不占我内存"）
    · 看门狗：超 3 倍预算才算异常，连续 2 次才停车（不然会误停）
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
    from computer_mcp import train as train_mod
    from computer_mcp import train as T
    HAVE = True
except Exception:
    HAVE = False

NEED = unittest.skipUnless(HAVE, "导不进 computer_mcp（需要 venv）")


@NEED
class TestBlockReduce(unittest.TestCase):
    def test_shape_and_mean(self) -> None:
        g = np.arange(64, dtype=np.float32).reshape(8, 8)
        out = T.block_reduce(g, 4)
        self.assertEqual(out.shape, (2, 2))
        self.assertAlmostEqual(float(out[0, 0]), float(g[:4, :4].mean()), places=4)

    def test_flat_image_unchanged(self) -> None:
        g = np.full((40, 40), 120.0, dtype=np.float32)
        out = T.block_reduce(g, 4)
        self.assertTrue(np.allclose(out, 120.0))

    def test_too_small_returns_gray(self) -> None:
        g = np.full((3, 3), 7.0, dtype=np.float32)
        out = T.block_reduce(g, 4)
        self.assertEqual(out.shape, (3, 3))

    def test_rejects_color(self) -> None:
        with self.assertRaises(ValueError):
            T.block_reduce(np.zeros((4, 4, 3), dtype=np.float32))


@NEED
class TestChangeBlocks(unittest.TestCase):
    def test_no_change(self) -> None:
        a = np.full((10, 10), 50.0, dtype=np.float32)
        n, frac, mask = T.change_blocks(a, a.copy())
        self.assertEqual(n, 0)
        self.assertEqual(frac, 0.0)
        self.assertFalse(mask.any())

    def test_single_block_change(self) -> None:
        a = np.full((10, 10), 50.0, dtype=np.float32)
        b = a.copy()
        b[2, 3] = 200.0
        n, frac, mask = T.change_blocks(a, b)
        self.assertEqual(n, 1)
        self.assertAlmostEqual(frac, 0.01, places=4)
        self.assertTrue(mask[2, 3])

    def test_prev_none_is_all_changed(self) -> None:
        b = np.zeros((8, 8), dtype=np.float32)
        n, frac, _ = T.change_blocks(None, b)
        self.assertEqual(n, 64)
        self.assertEqual(frac, 1.0)

    def test_shape_mismatch_is_all_changed(self) -> None:
        n, frac, _ = T.change_blocks(np.zeros((4, 4), np.float32), np.zeros((8, 8), np.float32))
        self.assertEqual(frac, 1.0)


@NEED
class TestThumbRing(unittest.TestCase):
    def test_frame_cap(self) -> None:
        ring = T.ThumbRing(frames=5)
        for i in range(20):
            ring.push(float(i), b"x" * 100, np.zeros((2, 2), np.float32))
        self.assertEqual(len(ring), 5)
        self.assertEqual(ring.bytes, 500)

    def test_byte_cap(self) -> None:
        ring = T.ThumbRing(frames=100, max_bytes=1000)
        for i in range(50):
            ring.push(float(i), b"y" * 100, np.zeros((2, 2), np.float32))
        self.assertLessEqual(ring.bytes, 1000)
        self.assertGreaterEqual(len(ring), 1)

    def test_span(self) -> None:
        ring = T.ThumbRing(frames=10)
        ring.push(100.0, b"a", np.zeros((1, 1), np.float32))
        ring.push(101.5, b"b", np.zeros((1, 1), np.float32))
        self.assertAlmostEqual(ring.span_s(), 1.5, places=3)


@NEED
class TestEventLog(unittest.TestCase):
    def test_cap(self) -> None:
        log = T.EventLog(cap=10)
        for i in range(50):
            log.add("STEP", f"e{i}")
        self.assertEqual(len(log), 10)
        tail = log.tail(3)
        self.assertEqual([e["detail"] for e in tail], ["e47", "e48", "e49"])

    def test_unknown_kind_falls_back(self) -> None:
        log = T.EventLog()
        ev = log.add("WHATEVER", "x")
        self.assertEqual(ev.kind, "STEP")


@NEED
class TestWatchdog(unittest.TestCase):
    def test_no_anomaly_within_budget(self) -> None:
        w = T.Watchdog()
        w.begin("click", 600)
        self.assertFalse(w.check()[0])

    def test_anomaly_after_3x(self) -> None:
        w = T.Watchdog()
        w.begin("launch", 100)
        w.step_start = time.time() - 0.5          # 已过 500ms = 5× 预算
        bad, msg = w.check()
        self.assertTrue(bad)
        self.assertIn("异常延迟", msg)

    def test_anomaly_reported_once_per_second(self) -> None:
        w = T.Watchdog()
        w.begin("launch", 100)
        w.step_start = time.time() - 0.5
        self.assertTrue(w.check()[0])
        self.assertFalse(w.check()[0], "1 秒内不该重复报")

    def test_stop_after_two_anomalies(self) -> None:
        w = T.Watchdog()
        w.begin("launch", 100)
        w.step_start = time.time() - 0.5
        w.check()
        w.last_anomaly_at = 0.0                   # 模拟过了 1 秒
        w.step_start = time.time() - 0.5
        w.check()
        self.assertTrue(w.should_stop())

    def test_zero_budget_never_alarms(self) -> None:
        w = T.Watchdog()
        w.begin("x", 0)
        w.step_start = time.time() - 100
        self.assertFalse(w.check()[0])


@NEED
class TestTrackParse(unittest.TestCase):
    def test_from_dict_defaults(self) -> None:
        t = T.Track.from_dict({"name": "demo", "steps": [
            {"name": "a", "action": {"kind": "click"}},
            {"name": "b"},
        ]})
        self.assertEqual(t.name, "demo")
        self.assertEqual(len(t.steps), 2)
        self.assertEqual(t.steps[0].budget(), T.DEFAULT_BUDGET_MS["click"])
        self.assertEqual(t.steps[1].name, "b")
        self.assertEqual(t.capture["fps"], 30)

    def test_capture_override(self) -> None:
        t = T.Track.from_dict({"name": "x", "capture": {"fps": 15, "down": 8},
                               "steps": []})
        self.assertEqual(t.capture["fps"], 15)
        self.assertEqual(t.capture["down"], 8)

    def test_expect_kinds_present(self) -> None:
        t = T.Track.from_dict({"steps": [
            {"name": "s", "expect": {"kind": "stable", "ms": 300}}]})
        self.assertEqual(t.steps[0].expect["kind"], "stable")


@NEED
class TestMontage(unittest.TestCase):
    def test_empty_returns_canvas(self) -> None:
        img = T.montage([])
        self.assertEqual(img.shape, (360, 640))
        self.assertTrue((img == 24).all())

    def test_tiles_placed(self) -> None:
        tile = np.full((40, 60), 250, dtype=np.uint8)
        img = T.montage([tile, tile])
        self.assertEqual(img.shape, (360, 640))
        self.assertTrue((img[4:44, 4:64] == 250).all(), "第一块应贴在左上")
        self.assertGreater(int(img.sum()), 24 * 360 * 640)

    def test_oversize_tile_scaled(self) -> None:
        tile = np.full((2000, 2000), 200, dtype=np.uint8)
        img = T.montage([tile])
        self.assertEqual(img.shape, (360, 640))
        self.assertTrue((img > 150).any())


@NEED
class TestExpectPure(unittest.TestCase):
    def test_stable_predicate(self) -> None:
        class FakeWheel:
            state = T.STATE_STABLE
            last_change_at = time.time() - 1.0
            last_frac = 0.0

        self.assertTrue(T.check_expect({"kind": "stable", "ms": 300}, FakeWheel(), (0, 0, 10, 10)))

    def test_changed_predicate(self) -> None:
        class FakeWheel:
            state = T.STATE_TRANSITION
            last_change_at = time.time()
            last_frac = 0.05

        self.assertTrue(T.check_expect({"kind": "changed", "min_frac": 0.01}, FakeWheel(), (0, 0, 10, 10)))
        self.assertFalse(T.check_expect({"kind": "changed", "min_frac": 0.5}, FakeWheel(), (0, 0, 10, 10)))

    def test_no_expect_means_no_opinion(self) -> None:
        """没有判据 ≠ 已达成。

        实测教训：以前 check_expect(None) 返回 True，导致 Runner 把"只带动作、
        不带 expect 的步骤"当成已满足 → **动作根本不执行**，轨道 0 秒报 done。
        现在返回 None（判不了），动作才会真的跑。
        """
        self.assertIsNone(train_mod.check_expect(None, None, (0, 0, 100, 100), 0))
        self.assertIsNone(train_mod.check_expect({}, None, (0, 0, 100, 100), 0))

    def test_unknown_kind_is_uncertain(self) -> None:
        self.assertIsNone(T.check_expect({"kind": "???"}, None, (0, 0, 1, 1)))


@NEED
class TestResolvePoint(unittest.TestCase):
    def test_center(self) -> None:
        self.assertEqual(T._resolve_point((100, 200, 400, 300), [0.5, 0.5]), (300, 350))

    def test_corner(self) -> None:
        self.assertEqual(T._resolve_point((0, 0, 100, 100), [1.0, 1.0]), (100, 100))


@NEED
class TestTextMatch(unittest.TestCase):
    """OCR 文本比对：必须容忍连字符/空格/大小写（实测 TRACK-OK 被读散过一次）。"""

    def test_norm_strips_and_lowers(self) -> None:
        self.assertEqual(T.norm_text("TRACK-OK-2152"), "trackok2152")
        self.assertEqual(T.norm_text(" track ok 2152 "), "trackok2152")
        self.assertEqual(T.norm_text("文件传输助手"), "文件传输助手")

    def test_norm_empty(self) -> None:
        self.assertEqual(T.norm_text(""), "")
        self.assertEqual(T.norm_text(None), "")

    def test_lcs_exact(self) -> None:
        self.assertEqual(T.lcs_share("trackok", "trackok"), 1.0)

    def test_lcs_contains(self) -> None:
        self.assertEqual(T.lcs_share("abc", "xxabcxx"), 1.0)

    def test_lcs_partial(self) -> None:
        share = T.lcs_share("trackok2152", "trackok2153")
        self.assertGreater(share, 0.8)
        self.assertLess(share, 1.0)

    def test_lcs_disjoint(self) -> None:
        self.assertEqual(T.lcs_share("abc", "xyz"), 0.0)

    def test_lcs_empty(self) -> None:
        self.assertEqual(T.lcs_share("", "abc"), 0.0)


if __name__ == "__main__":
    unittest.main()