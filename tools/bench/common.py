"""Shared helpers: make sure the benchmark targets exist before measuring."""
from __future__ import annotations

import subprocess
import time

import win32gui


def _windows(class_name: str) -> list[int]:
    found = []

    def visit(hwnd, acc):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetClassName(hwnd) == class_name:
            rect = win32gui.GetWindowRect(hwnd)
            if rect[2] - rect[0] > 300 and rect[3] - rect[1] > 200:
                acc.append(hwnd)
        return True

    win32gui.EnumWindows(visit, found)
    return found


def ensure_windows(target: str = "System32", timeout: float = 12.0) -> dict:
    """Open Explorer and Notepad when they are not already there.

    Without this a run silently measures nothing when the windows happen to be
    closed, which is worse than a slow run: it looks like a result.
    """
    started = []
    if not _windows("CabinetWClass"):
        subprocess.Popen(["explorer.exe", rf"C:\Windows\{target}"])
        started.append("explorer")
    if not _windows("Notepad"):
        subprocess.Popen(["notepad.exe"])
        started.append("notepad")

    deadline = time.time() + timeout
    while time.time() < deadline:
        explorer = _windows("CabinetWClass")
        notepad = _windows("Notepad")
        if explorer and notepad:
            time.sleep(1.0)                      # let the tree settle
            return {"explorer": explorer[0], "notepad": notepad[0],
                    "launched": started}
        time.sleep(0.4)
    return {"explorer": (_windows("CabinetWClass") or [None])[0],
            "notepad": (_windows("Notepad") or [None])[0],
            "launched": started}
