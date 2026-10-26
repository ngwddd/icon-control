#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""track_oneshot.py — 列车的一次性自测（用户只需要跑这一条）

它做四件事，全自动，约 25 秒：
    ① 短跑抓帧 6 秒   → 报 fps / 环形占用 / 内存
    ② 记事本轨道 3 步 → 点击 → 粘贴 TRACK-xxxx → 文本断言 → 稳定
    ③ 异常延迟演练     → 故意给一个 200ms 预算让它超时，验证看门狗会报异常
    ④ 清理            → 关掉记事本，不留垃圾

用法：
    python track_oneshot.py

退出码：0 全部通过 / 1 有失败项
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
for cand in (os.path.join(HERE, "venv", "Lib", "site-packages"),
             os.path.join(os.path.dirname(HERE), "venv", "Lib", "site-packages")):
    if os.path.isdir(cand) and cand not in sys.path:
        sys.path.insert(0, cand)

import win32gui  # noqa: E402
import psutil  # noqa: E402

from computer_mcp import live  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"   {'✓' if ok else '✗'} {name:28} {detail}")


def kill_notepads() -> None:
    for p in psutil.process_iter(["name", "pid"]):
        if "notepad" in (p.info.get("name") or "").lower():
            try:
                psutil.Process(p.info["pid"]).kill()
            except Exception:
                pass


def step1_selfcheck() -> None:
    print("\n① 抓帧自检（6 秒）")
    res = live.tool_track({"action": "selfcheck", "seconds": 6.0})
    fps = float(res.get("fps_actual") or 0)
    ring_kb = float(res.get("ring_kb") or 0)
    check("fps ≥ 20", fps >= 20, f"{fps:.1f} fps")
    check("环形缓冲有上限", 0 < ring_kb < 20_000, f"{ring_kb:.0f} KB / {res.get('ring_frames')} 帧")
    check("抓帧线程无异常", not res.get("error"), str(res.get("error") or "")[:60])


def step2_track() -> None:
    print("\n② 记事本轨道（3 步）")
    kill_notepads()
    time.sleep(0.8)
    fn = f"oneshot_{int(time.time()) % 100000}.txt"
    path = os.path.join(os.environ.get("TEMP", "."), fn)
    open(path, "w", encoding="utf-8").write("")
    subprocess.Popen(["notepad.exe", path])
    time.sleep(2.2)

    hwnd = 0

    def cb(h, _):
        nonlocal hwnd
        if win32gui.IsWindowVisible(h) and fn[:10] in win32gui.GetWindowText(h):
            hwnd = h

    win32gui.EnumWindows(cb, None)
    if not hwnd:
        check("记事本窗口", False, "没找到")
        return

    mark = "TRACK" + str(int(time.time()) % 10000)
    track = {
        "name": "oneshot",
        "hwnd": hwnd,
        "steps": [
            {"name": "点编辑区", "action": {"kind": "click", "rel_frac": [0.5, 0.35]},
             "expect": {"kind": "stable", "ms": 200}, "budget_ms": 800, "timeout_ms": 4000},
            {"name": "粘贴标记", "action": {"kind": "paste", "text": mark},
             "expect": {"kind": "text", "query": mark}, "budget_ms": 2500, "timeout_ms": 9000},
            {"name": "画面稳定", "expect": {"kind": "stable", "ms": 300}, "timeout_ms": 4000},
        ],
    }
    res = live.tool_track({"action": "run", "track": track, "hwnd": hwnd, "max_total_s": 25})
    check("轨道跑完", res.get("status") == "done",
          f"status={res.get('status')} steps={res.get('steps_done')} {res.get('elapsed_s')}s")
    check("3 步全过", int(res.get("steps_done") or 0) >= 3, f"{res.get('steps_done')}/3")
    check("无异常延迟", int(res.get("anomalies") or 0) == 0, f"anomalies={res.get('anomalies')}")
    check("无对话框干扰", int(res.get("dialog_hits") or 0) == 0, f"dialogs={res.get('dialog_hits')}")
    mp = res.get("montage") or ""
    check("拼图已产出", bool(mp) and os.path.isfile(mp),
          f"{os.path.getsize(mp)//1024 if mp and os.path.isfile(mp) else 0} KB")

    try:
        win32gui.PostMessage(hwnd, 0x0010, 0, 0)
        time.sleep(0.6)
        from pynput.keyboard import Controller as KB
        kb = KB()
        kb.press("n")
        kb.release("n")
        time.sleep(0.4)
    except Exception:
        pass
    kill_notepads()


def step3_watchdog() -> None:
    print("\n③ 看门狗演练（故意超预算）")
    kill_notepads()
    time.sleep(0.6)
    fn = f"wd_{int(time.time()) % 100000}.txt"
    path = os.path.join(os.environ.get("TEMP", "."), fn)
    open(path, "w", encoding="utf-8").write("")
    subprocess.Popen(["notepad.exe", path])
    time.sleep(2.0)

    hwnd = 0

    def cb(h, _):
        nonlocal hwnd
        if win32gui.IsWindowVisible(h) and fn[:6] in win32gui.GetWindowText(h):
            hwnd = h

    win32gui.EnumWindows(cb, None)
    if not hwnd:
        check("看门狗", False, "没找到记事本")
        return

    # 预算 300ms，判据是"永远不可能出现的文字" → 必然超 3 倍 → 报异常 → 连续两次停车
    track = {"name": "watchdog-drill", "hwnd": hwnd, "steps": [
        {"name": "等一个不会出现的东西",
         "expect": {"kind": "text", "query": "ZZZ_NEVER_APPEARS_ZZZ"},
         "budget_ms": 300, "timeout_ms": 6000}]}
    t0 = time.time()
    res = live.tool_track({"action": "run", "track": track, "hwnd": hwnd, "max_total_s": 20})
    took = time.time() - t0
    check("看门狗触发", int(res.get("anomalies") or 0) >= 2, f"anomalies={res.get('anomalies')}")
    check("按异常停车", res.get("status") == "stall", f"status={res.get('status')}")
    check("及时停车（<10s）", took < 10, f"{took:.1f}s")
    kill_notepads()


def main() -> int:
    print("=" * 62)
    print("  列车（track）一次性自测")
    print("=" * 62)
    try:
        step1_selfcheck()
        step2_track()
        step3_watchdog()
    finally:
        kill_notepads()
        print("\n④ 清理完成（记事本已全部关闭）")

    ok = [r for r in RESULTS if r[1]]
    bad = [r for r in RESULTS if not r[1]]
    print("\n" + "=" * 62)
    print(f"  结果：{len(ok)} 通过 / {len(bad)} 失败")
    for name, _, detail in bad:
        print(f"     ✗ {name}  {detail}")
    print("=" * 62)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
