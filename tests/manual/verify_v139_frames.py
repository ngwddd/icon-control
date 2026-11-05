# -*- coding: utf-8 -*-
"""Real-desktop evidence for the v1.3.9 frame_id coordinate contract.

Run with the icon-control venv and the overlay package:

    set PYTHONPATH=<repo>/.runtime
    set ICON_CONTROL_HOME=<repo>/.runtime/frame-home
    python tests/manual/verify_v139_frames.py

It opens its own Tk window (so no user window is touched), captures the screen,
maps the window centre from image coordinates to physical pixels, then moves the
window and proves the old frame is rejected. The window is destroyed and the
temporary trust record revoked afterwards.
"""
from __future__ import annotations

import json
import os
import sys
import time
import tkinter as tk
from pathlib import Path

HOME = Path(os.environ.get("ICON_CONTROL_HOME", "")).resolve()
REPORT = Path(__file__).resolve().parents[2] / "docs" / "v1.3" / "evidence" / "v139-frames-desktop.json"


def _force_foreground(hwnd: int) -> None:
    """Windows refuses SetForegroundWindow across threads; attach first."""
    import win32api
    import win32gui
    import win32process
    foreground = win32gui.GetForegroundWindow()
    current = win32api.GetCurrentThreadId()
    other, _ = win32process.GetWindowThreadProcessId(foreground) if foreground else (0, 0)
    attached = False
    try:
        if other and other != current:
            win32process.AttachThreadInput(current, other, True)
            attached = True
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
    finally:
        if attached:
            win32process.AttachThreadInput(current, other, False)


def main() -> int:
    from computer_mcp import security, trust
    from computer_mcp.core import screenshot as capture
    import win32con
    import win32gui
    import win32process

    security.provision_token()
    trust.grant(confirm=lambda: True)          # test harness, not a product path
    results: dict = {"home": str(HOME), "steps": []}

    root = tk.Tk()
    root.title("IC139 frame probe")
    root.geometry("320x200+220+180")
    root.attributes("-topmost", True)
    root.update()
    root.lift()
    root.focus_force()
    root.update()
    probe = int(root.wm_frame(), 16)
    _force_foreground(probe)
    time.sleep(0.8)
    if win32gui.GetForegroundWindow() != probe:
        raise SystemExit("could not bring the probe window to the foreground")

    try:
        hwnd = int(root.winfo_id())
        top = win32gui.GetAncestor(hwnd, 2) or hwnd
        shot = capture.capture_screenshot()
        frame_id = shot["frame_id"]
        # Move the window the frame actually recorded (foreground at capture).
        target = shot.get("hwnd") or top
        _, owner_pid = win32process.GetWindowThreadProcessId(target)
        results["probe_owner_pid"] = owner_pid
        results["self_pid"] = os.getpid()
        if owner_pid != os.getpid():
            raise SystemExit("captured foreground window does not belong to the probe: "
                             f"{target} pid={owner_pid}")
        x0, y0, src_w, src_h = shot["source_rect"]
        img_w, img_h = shot["image_size"]
        left, top_y, right, bottom = win32gui.GetWindowRect(top)
        centre = ((left + right) // 2, (top_y + bottom) // 2)
        image_point = ((centre[0] - x0) * img_w / src_w,
                       (centre[1] - y0) * img_h / src_h)
        mapped = capture.to_physical(frame_id, *image_point)
        inside = left <= mapped[0] <= right and top_y <= mapped[1] <= bottom
        delta = (abs(mapped[0] - centre[0]), abs(mapped[1] - centre[1]))
        results["steps"].append(dict(
            name="map_window_centre",
            frame_id=frame_id,
            foreground_hwnd_at_capture=shot.get("hwnd"),
            probe_hwnd=top,
            source_rect=shot["source_rect"],
            image_size=shot["image_size"],
            window_rect=[left, top_y, right, bottom],
            image_point=[round(image_point[0], 2), round(image_point[1], 2)],
            expected=centre, mapped=list(mapped), inside_window=inside,
            delta_px=list(delta), pass_=bool(inside and max(delta) <= 2)))

        root.geometry("320x200+%d+%d" % (left + 80, top_y + 60))
        root.update()
        # Tk geometry moves its own toplevel; make sure the frame's window moved
        # too, otherwise move it explicitly.
        after = win32gui.GetWindowRect(target)
        if after == [left, top_y, right, bottom]:
            win32gui.SetWindowPos(target, 0, left + 80, top_y + 60, 0, 0,
                                  win32con.SWP_NOSIZE | win32con.SWP_NOZORDER)
        time.sleep(0.6)
        results["moved_window_rect"] = list(win32gui.GetWindowRect(target))
        rejected = False
        message = ""
        try:
            capture.to_physical(frame_id, *image_point)
        except ValueError as exc:
            rejected = True
            message = str(exc)
        results["steps"].append(dict(
            name="moved_window_rejects_frame",
            moved_by=[80, 60], rejected=rejected, message=message,
            pass_=rejected and "moved" in message))
    finally:
        try:
            root.destroy()
        except Exception:
            pass
        try:
            trust.revoke()
        except Exception:
            pass

    passed = all(step["pass_"] for step in results["steps"])
    results["ok"] = passed
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                      encoding="utf-8", newline="\n")
    for step in results["steps"]:
        print(("PASS " if step["pass_"] else "FAIL ") + step["name"],
              json.dumps({k: v for k, v in step.items()
                          if k not in ("name", "pass_")}, ensure_ascii=False))
    print("report:", REPORT)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
