#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""selector_demo.py — 软选择器 vs 硬坐标 的可复现 A/B（双进程版）

为什么双进程：
    Windows 上 Tk 必须在**主线程**跑 mainloop，放子线程会报
    `RuntimeError: Calling Tcl from different apartment`。

结构：
    子进程（--app）  建窗口、把控件坐标写进 state.json、把点击记进 clicks.log、轮询 cmd.json 挪窗口
    父进程          截模板 → 改窗口位置尺寸 → A 硬坐标 / B 文本 / C 模板 各点一次 → 读 clicks.log

判定不靠截图猜：**被点窗口自己记账**（<Button-1> 计数）。

用法：  python tools/selector_demo.py
预期：  A 硬坐标失败，B 文本成功，C 模板成功
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
# 每轮独立文件名：多轮跑残留的子进程会互相覆盖同一个 state，实测卡过一次
RUN = os.environ.get("SEL_DEMO_RUN") or str(os.getpid())
STATE = os.path.join(TMP, f"sel_demo_{RUN}_state.json")
CLICKS = os.path.join(TMP, f"sel_demo_{RUN}_clicks.log")
CMD = os.path.join(TMP, f"sel_demo_{RUN}_cmd.json")
TPL_DIR = os.path.join(BASE, "templates")

W1, H1, X1, Y1 = 700, 500, 80, 80
W2, H2, X2, Y2 = 520, 380, 520, 300


# ─────────────────────────── 子进程：窗口 ───────────────────────────

def run_app() -> int:
    import tkinter as tk

    for p in (STATE, CLICKS, CMD):
        try:
            os.remove(p)
        except OSError:
            pass

    root = tk.Tk()
    root.title("selector-demo")
    root.geometry(f"{W1}x{H1}+{X1}+{Y1}")
    root.configure(bg="#20232a")
    root.attributes("-topmost", True)   # 否则被别的窗口盖住，OCR 会读到别处

    discover = tk.Label(root, text="发现", bg="#2f3542", fg="#8fd3ff",
                        font=("Microsoft YaHei", 16), width=8, height=2)
    discover.place(relx=0.10, rely=0.70)
    moments = tk.Label(root, text="朋友圈", bg="#2f3542", fg="#ffd479",
                       font=("Microsoft YaHei", 14), width=8, height=1)
    moments.place(relx=0.52, rely=0.12)
    status = tk.Label(root, text="clicks=0", bg="#20232a", fg="#9aa0a6",
                      font=("Consolas", 11))
    status.place(relx=0.02, rely=0.02)

    n = {"c": 0}

    def hit(name: str) -> None:
        n["c"] += 1
        status.configure(text=f"clicks={n['c']}")
        with open(CLICKS, "a", encoding="utf-8") as fh:
            fh.write(name + "\n")

    discover.bind("<Button-1>", lambda e: hit("discover"))
    moments.bind("<Button-1>", lambda e: hit("moments"))

    def snapshot() -> None:
        root.update_idletasks()
        data = {
            "client": [root.winfo_rootx(), root.winfo_rooty(),
                       root.winfo_width(), root.winfo_height()],
            "window": list(root.geometry().split("+")),
            "discover": [discover.winfo_rootx(), discover.winfo_rooty(),
                         discover.winfo_width(), discover.winfo_height()],
            "moments": [moments.winfo_rootx(), moments.winfo_rooty(),
                        moments.winfo_width(), moments.winfo_height()],
        }
        with open(STATE, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def poll_cmd() -> None:
        try:
            with open(CMD, encoding="utf-8") as fh:
                c = json.load(fh)
            os.remove(CMD)
            if c.get("op") == "place":
                root.geometry(f"{c['w']}x{c['h']}+{c['x']}+{c['y']}")
                root.after(400, snapshot)
        except Exception:
            pass
        root.after(120, poll_cmd)

    root.after(300, snapshot)
    root.after(200, poll_cmd)
    root.mainloop()
    return 0


# ─────────────────────────── 父进程：驱动 ───────────────────────────

def click(x: int, y: int) -> None:
    u = ctypes.windll.user32
    u.SetCursorPos(int(x), int(y))
    time.sleep(0.15)
    u.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.06)
    u.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.6)


def read_state() -> dict:
    for _ in range(40):
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
    import mss
    import numpy as np
    from PIL import Image

    from computer_mcp import selector as S

    os.makedirs(TPL_DIR, exist_ok=True)

    # 清掉上一轮可能残留的 --app 子进程（它们会抢着写 state）
    try:
        import psutil

        for pr in psutil.process_iter(["name", "pid", "cmdline"]):
            cl = pr.info.get("cmdline") or []
            if any("selector_demo" in str(x) for x in cl) and "--app" in cl:
                try:
                    pr.terminate()
                except Exception:
                    pass
        time.sleep(0.4)
    except Exception:
        pass

    env = dict(os.environ, SEL_DEMO_RUN=RUN)
    child = subprocess.Popen([sys.executable, os.path.abspath(__file__), "--app"], env=env)
    results: list[tuple[str, bool, str]] = []
    try:
        st = read_state()
        dx, dy, dw, dh = st["discover"]
        cx1, cy1 = dx + dw // 2, dy + dh // 2
        print(f"   标定：发现 @({cx1},{cy1})  控件 {dw}x{dh}")

        # 裁模板（模拟第一次标定）
        with mss.mss() as sct:
            shot = sct.grab({"left": dx - 4, "top": dy - 4, "width": dw + 8, "height": dh + 8})
        img = np.asarray(Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX"))
        tpl_name = "demo_discover.png"
        Image.fromarray(img).save(os.path.join(TPL_DIR, tpl_name))
        print(f"   模板 {tpl_name} {dw + 8}x{dh + 8}")

        # 挪窗口 + 改尺寸
        with open(CMD, "w", encoding="utf-8") as fh:
            json.dump({"op": "place", "w": W2, "h": H2, "x": X2, "y": Y2}, fh)
        time.sleep(1.2)
        st = read_state()
        rect = tuple(st["client"])
        print(f"   已改窗口 → client={rect}（控件现在在 {st['discover'][:2]}）")

        # A 硬坐标（旧绝对位置）
        n0 = read_clicks()
        click(cx1, cy1)
        ok_a = read_clicks() > n0
        results.append(("A 硬坐标（旧绝对位置）", ok_a,
                        "应当失败" if not ok_a else "碰巧命中"))

        # B 文本（失败时把 OCR 原文打出来，避免瞎猜）
        S.clear_cache()
        r = S.resolve(rect, {"text": "发现", "within": [0, 0, 0.6, 1.0]})
        if not r["ok"]:
            from computer_mcp import ocr_ext

            dbg = ocr_ext.ocr_read(region={"x": rect[0], "y": rect[1],
                                           "w": rect[2], "h": rect[3]}, max_lines=10)
            lines = [str((ln or {}).get("text") or "") for ln in (dbg.get("lines") or [])]
            print(f"   [debug] 该区域 OCR 读到 {len(lines)} 行: {lines[:6]}")
        n0 = read_clicks()
        if r["ok"]:
            click(*r["at"])
        ok_b = read_clicks() > n0
        results.append(("B 软选择器·文本", ok_b, f"{r.get('detail', '')} → {r.get('at')}"))

        # C 模板
        S.clear_cache()
        r2 = S.resolve(rect, {"template": tpl_name, "min_score": 0.7}, template_dir=TPL_DIR)
        n0 = read_clicks()
        if r2["ok"]:
            click(*r2["at"])
        ok_c = read_clicks() > n0
        results.append(("C 软选择器·模板", ok_c, f"{r2.get('detail', '')} → {r2.get('at')}"))
    finally:
        child.terminate()
        try:
            child.wait(timeout=5)
        except Exception:
            child.kill()

    print("\n   " + "-" * 60)
    for name, ok, detail in results:
        print(f"   {'✓' if ok else '✗'} {name:22} {detail}")
    print("   " + "-" * 60)
    good = len(results) == 3 and (not results[0][1]) and results[1][1] and results[2][1]
    print(f"   结论：{'符合预期（硬坐标失败，软选择器成功）' if good else '不符合预期'}")
    return 0 if good else 1


def main() -> int:
    if "--app" in sys.argv:
        return run_app()
    return drive()


if __name__ == "__main__":
    sys.exit(main())
