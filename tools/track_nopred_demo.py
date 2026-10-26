#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""track_nopred_demo.py — 回归测试：无 expect 的步骤必须真的执行

守的 bug（2026-10-27，让我三次误报"完成"）：
    `check_expect(None)` 返回 True → Runner 先判 pred，True 就"达成"并**跳过动作**
    → 只带 action、不带 expect 的步骤（scroll / paste / send / key）一次都不执行，
      而轨道照样 status=done。

这个脚本就用最笨的办法验证它：
    开一个 Tk 窗口，里面一个按钮，按钮被点一次就 +1 记到文件里。
    然后用 track 跑一个**只有 action、没有 expect** 的步骤去点它。
        修好之前：clicks == 0，轨道却在 0.2 秒内报 done
        修好之后：clicks == 1，轨道报了 done 而且真的点了

用法：  python tools/track_nopred_demo.py
退出码：0 = 通过（确实点了），1 = 复现了 bug（没点）
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
for cand in (os.path.join(BASE, "venv", "Lib", "site-packages"),
             os.path.join(HERE, "venv", "Lib", "site-packages")):
    if os.path.isdir(cand) and cand not in sys.path:
        sys.path.insert(0, cand)

TMP = os.environ.get("TEMP", ".")
RUN = os.environ.get("NOPRED_RUN") or str(os.getpid())
STATE = os.path.join(TMP, f"nopred_{RUN}_state.json")
CLICKS = os.path.join(TMP, f"nopred_{RUN}_clicks.log")

W, H, X, Y = 520, 360, 160, 160


# ─────────────────────── 子进程：被点的窗口 ───────────────────────

def run_app() -> int:
    import tkinter as tk

    import win32gui

    for p in (STATE, CLICKS):
        try:
            os.remove(p)
        except OSError:
            pass

    root = tk.Tk()
    root.title("nopred-demo")
    root.geometry(f"{W}x{H}+{X}+{Y}")
    root.configure(bg="#20232a")
    root.attributes("-topmost", True)

    count = tk.Label(root, text="clicks=0", bg="#20232a", fg="#9aa0a6",
                     font=("Consolas", 12))
    count.place(relx=0.04, rely=0.05)

    btn = tk.Label(root, text="点我", bg="#2f6f3f", fg="#ffffff",
                   font=("Microsoft YaHei", 18), width=8, height=3)
    btn.place(relx=0.5, rely=0.55, anchor="center")

    n = {"c": 0}

    def on_click(_e) -> None:
        n["c"] += 1
        count.configure(text=f"clicks={n['c']}")
        with open(CLICKS, "a", encoding="utf-8") as fh:
            fh.write(f"click {n['c']}\n")

    btn.bind("<Button-1>", on_click)

    def snapshot() -> None:
        root.update_idletasks()
        # ★ 必须用 **toplevel 帧句柄**（winfo_id 是子窗口，拿它 SetWindowPos
        #   抬不动父窗口，点击会落到别的应用上 —— 实测 clicks 一直是 0）
        frame = int(root.wm_frame(), 16)
        st = {
            "hwnd": frame,
            "frame_rect": list(win32gui.GetWindowRect(frame)),
            "client": [root.winfo_rootx(), root.winfo_rooty(),
                       root.winfo_width(), root.winfo_height()],
            "btn": [btn.winfo_rootx(), btn.winfo_rooty(),
                    btn.winfo_width(), btn.winfo_height()],
            "clicks": CLICKS,
        }
        win32gui.SetWindowPos(frame, -1, 0, 0, 0, 0, 0x0001 | 0x0002)
        with open(STATE, "w", encoding="utf-8") as fh:
            json.dump(st, fh)
        root.after(400, snapshot)

    root.after(300, snapshot)
    root.mainloop()
    return 0


# ─────────────────────── 父进程：跑轨道 ───────────────────────

def read_state() -> dict:
    for _ in range(50):
        try:
            with open(STATE, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            time.sleep(0.15)
    raise RuntimeError("子进程没写出 state.json")


def read_clicks() -> int:
    try:
        with open(CLICKS, encoding="utf-8") as fh:
            return len([x for x in fh.read().splitlines() if x.strip()])
    except Exception:
        return 0


def drive() -> int:
    from computer_mcp import live

    child = subprocess.Popen([sys.executable, os.path.abspath(__file__), "--app"],
                             env=dict(os.environ, NOPRED_RUN=RUN))
    ok = False
    try:
        st = read_state()
        hwnd = int(st["hwnd"])
        fl, ft, fr, fb = st["frame_rect"]
        fw, fh = fr - fl, fb - ft
        bx, by, bw, bh = st["btn"]
        # 相对 **帧窗口** 的比例（Runner 用的是 GetWindowRect(frame)）
        fx = (bx + bw / 2 - fl) / fw
        fy = (by + bh / 2 - ft) / fh
        print(f"   帧窗口 ({fl},{ft},{fw}x{fh}) 按钮中心比例=({fx:.3f},{fy:.3f})")
        print(f"   点击前 clicks={read_clicks()}")

        track = {
            "name": "nopred", "hwnd": hwnd,
            "steps": [
                # ★ 关键：只有 action，没有 expect
                {"name": "点按钮",
                 "action": {"kind": "click", "rel_frac": [fx, fy]},
                 "budget_ms": 1500, "timeout_ms": 5000},
            ],
        }
        t0 = time.time()
        res = live.tool_track({"action": "run", "track": track,
                               "hwnd": hwnd, "max_total_s": 20})
        dt = time.time() - t0
        clicks = read_clicks()
        status = res.get("status")
        print(f"   轨道: status={status} steps_done={res.get('steps_done')} 用时={dt:.2f}s")
        print(f"   点击后 clicks={clicks}")

        ok = (clicks == 1 and status == "done")
        if clicks == 0:
            print("   ✗ 复现了 bug：轨道说 done，但按钮一次都没被点（动作被跳过）")
        elif clicks == 1 and status == "done":
            print("   ✓ 通过：无 expect 的步骤确实执行了，且轨道正确报 done")
        else:
            print(f"   ⚠ 异常组合：clicks={clicks} status={status}")
    finally:
        child.terminate()
        try:
            child.wait(timeout=5)
        except Exception:
            child.kill()

    return 0 if ok else 1


def main() -> int:
    if "--app" in sys.argv:
        return run_app()
    return drive()


if __name__ == "__main__":
    sys.exit(main())
