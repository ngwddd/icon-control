# -*- coding: utf-8 -*-
"""M1/M2/M3 的离线测试（不需要游戏、不动真实键鼠）。

验收的是这三件事能不能成立：
    M1  WorldState.minimap  合成一张地图 → 解出网格 / 玩家格 / 目标格
    M2  Servo.approach      在一个"会移动的假世界"里走到指定格
    M3  Supervisor.run      计划跑完；走不到时把控制权交回来（附一页状态）
"""
from __future__ import annotations

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "venv", "Lib", "site-packages"))

try:
    from computer_mcp import navigator as nav
    HAVE = True
except Exception:
    HAVE = False

NEED = unittest.skipUnless(HAVE, "导不进 computer_mcp（需要 venv）")

PITCH = 11
DARK = (12, 12, 12)
FLOOR = (110, 110, 110)
GREEN = (0, 255, 128)
GOLD = (232, 192, 64)


def render_map(rows: int, cols: int, player, markers=()) -> np.ndarray:
    """画一张小地图：深底 + 灰色地板格（1px 间隙），玩家绿、目标金。"""
    h, w = rows * PITCH, cols * PITCH
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :] = DARK
    for r in range(rows):
        for c in range(cols):
            y, x = r * PITCH + 1, c * PITCH + 1
            img[y:y + PITCH - 2, x:x + PITCH - 2] = FLOOR
    if player:
        c, r = player
        y, x = r * PITCH + 1, c * PITCH + 1
        img[y:y + PITCH - 2, x:x + PITCH - 2] = GREEN
    for (c, r) in markers:
        y, x = r * PITCH + 1, c * PITCH + 1
        img[y:y + PITCH - 2, x:x + PITCH - 2] = GOLD
    return img


class FakeWorld:
    """假世界：grab 按当前玩家位置渲染地图；forward 让玩家沿朝向走一格。"""

    def __init__(self, rows=9, cols=13, start=(1, 1), heading=0.0, blocked=()):
        self.rows, self.cols = rows, cols
        self.player = list(start)
        self.heading = heading          # 0 = 向右
        self.blocked = set(blocked)
        self.markers = [(cols - 2, rows - 2)]
        self.calls = 0

    # WorldState 需要
    def grab(self, region) -> np.ndarray:
        self.calls += 1
        return render_map(self.rows, self.cols, tuple(self.player), self.markers)

    def snapshot(self) -> nav.WorldSnapshot:
        return nav.WorldSnapshot(ts=0.0,
                                 grid=["." * self.cols] * self.rows,
                                 player=tuple(self.player), markers=[list(self.markers[0])],
                                 pitch=PITCH, origin=(0, 0))

    # Servo 需要
    def press(self, key, ms):
        if key != "w":
            return
        dc = int(round(np.cos(np.radians(self.heading))))
        dr = int(round(-np.sin(np.radians(self.heading))))
        nxt = (self.player[0] + dc, self.player[1] + dr)
        if nxt in self.blocked or not (0 <= nxt[0] < self.cols and 0 <= nxt[1] < self.rows):
            return
        self.player = list(nxt)


class FakeKB:
    def __init__(self, world): self.w = world
    def press(self, k): self.w.press(k, 0)
    def release(self, k): pass


class FakeMS:
    def __init__(self, world, px_per_deg=10.0):
        self.w = world
        self.ppd = px_per_deg
    def move(self, dx, dy):
        self.w.heading = (self.w.heading - dx / self.ppd) % 360


class WorldStateWithFake(nav.WorldState):
    """把 snapshot 换成假世界的（但 minimap 仍走真实解码逻辑）。"""

    def __init__(self, fake):
        super().__init__(fake.grab, map_cfg=nav.MapConfig(region=(0, 0, 10, 10)))
        self.fake = fake

    def snapshot(self):
        return self.fake.snapshot()


@NEED
class TestM1MapDecode(unittest.TestCase):
    def test_decode_player_and_marker(self) -> None:
        img = render_map(9, 13, (3, 2), [(11, 7)])
        ws = nav.WorldState(lambda r: img, map_cfg=nav.MapConfig(region=(0, 0, 1, 1)))
        grid, player, markers, pitch, origin = ws.minimap()
        self.assertGreaterEqual(pitch, 9.0)
        self.assertLessEqual(pitch, 13.0)
        self.assertIsNotNone(player, "没找到玩家格")
        self.assertEqual(len(markers), 1, f"目标标记数不对：{markers}")
        # 玩家应该在 (3,2) 附近（容许一格误差，因为原点对齐方式）
        self.assertLessEqual(abs(player[0] - 3), 1, f"玩家列={player}")
        self.assertLessEqual(abs(player[1] - 2), 1, f"玩家行={player}")
        self.assertTrue(grid and grid[0])

    def test_grid_is_rectangular(self) -> None:
        img = render_map(7, 10, (1, 1))
        ws = nav.WorldState(lambda r: img, map_cfg=nav.MapConfig(region=(0, 0, 1, 1)))
        grid, *_ = ws.minimap()
        self.assertGreater(len(grid), 3)
        self.assertEqual(len({len(r) for r in grid}), 1, "网格每行长度应该一致")

    def test_empty_region_is_safe(self) -> None:
        ws = nav.WorldState(lambda r: np.zeros((0, 0, 3), dtype=np.uint8),
                            map_cfg=nav.MapConfig(region=(0, 0, 1, 1)))
        grid, player, markers, pitch, _ = ws.minimap()
        self.assertEqual(grid, [])
        self.assertIsNone(player)


@NEED
class TestM2Servo(unittest.TestCase):
    def _servo(self, heading=0.0):
        fake = FakeWorld(start=(1, 1), heading=heading)
        ws = WorldStateWithFake(fake)
        servo = nav.Servo(ws, FakeKB(fake), FakeMS(fake), px_per_deg=10.0, tap_ms=0)
        return fake, ws, servo

    def test_estimate_heading_from_displacement(self) -> None:
        """朝向靠"走一小步看地图位移"自校准：朝右走 → 0°，朝上走 → 90°。"""
        for heading, expect in ((0.0, 0.0), (90.0, 90.0), (180.0, 180.0), (270.0, -90.0)):
            fake, ws, servo = self._servo(heading=heading)
            got = servo.estimate_heading(ttl=0)
            self.assertIsNotNone(got, f"heading={heading} 没测出来")
            diff = min(abs(got - expect), 360 - abs(got - expect))
            self.assertLess(diff, 30, f"朝向误差太大：测出 {got}，期望 {expect}")

    def test_approach_reaches_target(self) -> None:
        fake, ws, servo = self._servo(heading=0.0)
        target = (8, 4)
        r = servo.approach(target, max_steps=40)
        self.assertTrue(r.get("ok"), f"没走到：{r}")
        self.assertLessEqual(abs(fake.player[0] - target[0]), 2)
        self.assertLessEqual(abs(fake.player[1] - target[1]), 2)

    def test_approach_reports_stuck(self) -> None:
        """四周全堵 → 必须报"卡住"，不能假装走到了。"""
        fake = FakeWorld(start=(1, 1), heading=0.0,
                         blocked=[(2, 1), (0, 1), (1, 2), (1, 0)])
        ws = WorldStateWithFake(fake)
        servo = nav.Servo(ws, FakeKB(fake), FakeMS(fake), px_per_deg=10.0, tap_ms=0)
        r = servo.approach((8, 4), max_steps=12)
        self.assertFalse(r.get("ok"), "四周全堵时不能报成功")
        self.assertTrue(
            ("无位移" in r.get("reason", "")) or ("最大步数" in r.get("reason", "")),
            f"失败原因要说清楚：{r.get('reason')}")


@NEED
class TestM3Supervisor(unittest.TestCase):
    def _sup(self, reachable=True):
        fake = FakeWorld(start=(1, 1), heading=0.0,
                         blocked=[] if reachable else [(2, 1), (0, 1), (1, 2), (1, 0)])
        ws = WorldStateWithFake(fake)
        servo = nav.Servo(ws, FakeKB(fake), FakeMS(fake), px_per_deg=10.0, tap_ms=0)
        return nav.Supervisor(ws, servo), fake

    def test_plan_completes(self) -> None:
        sup, fake = self._sup(reachable=True)
        r = sup.run([{"kind": "goto", "cell": [7, 3]},
                     {"kind": "wait", "ms": 1},
                     {"kind": "key", "key": "e", "hold_ms": 1}])
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(len(r.get("done", [])), 3)
        self.assertIn("text", r.get("state", {}))

    def test_returns_on_stall_with_state_page(self) -> None:
        sup, fake = self._sup(reachable=False)
        r = sup.run([{"kind": "goto", "cell": [9, 6]}])
        self.assertFalse(r.get("ok"))
        self.assertIn("走不到", r.get("reason", ""))
        page = r.get("state") or {}
        self.assertIn("text", page)
        self.assertIn("player", page.get("state", {}))

    def test_panic_aborts(self) -> None:
        sup, fake = self._sup(reachable=True)

        class P:
            triggered = True
        sup.panic = P()
        r = sup.run([{"kind": "goto", "cell": [7, 3]}])
        self.assertFalse(r.get("ok"))
        self.assertIn("急停", r.get("reason", ""))


if __name__ == "__main__":
    unittest.main()
