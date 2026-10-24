"""appkit.py — 应用的「启动 / 等窗口 / 干净退出」三件套。

为什需要它（2026-10-25 视频客户端（***）那次）：直接 `Popen(exe)` 启动视频客户端（***）会
**退出码 0 秒退、无窗口无报错**，必须经 Explorer shell（等同用户双击）才行；
而 `WM_CLOSE` 只关窗，进程还留在托盘里。这两件事每次都要重查一遍，所以固化下来。

用法：
    from computer_mcp import appkit            # 或把本文件放到包内
    appkit.launch("视频客户端（***）")                   # 按名字找快捷方式，走 Explorer shell
    appkit.wait_window(title_contains="哔哩", timeout_ms=20000)
    appkit.exit_app(process="视频客户端（***）.exe")

CLI（方便直接从 desk.py 之外调用）：
    python appkit.py launch "视频客户端（***）"
    python appkit.py wait --title 哔哩 --timeout 20000
    python appkit.py exit --process 视频客户端（***）.exe
"""

from __future__ import annotations

import ctypes
import glob
import json
import os
import subprocess
import sys
import time

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import win32con  # noqa: E402
import win32gui  # noqa: E402
import win32process  # noqa: E402
import psutil  # noqa: E402

PUBLIC_DESKTOP = r"C:\Users\Public\Desktop"
USER_DESKTOP = os.path.join(os.path.expanduser("~"), "Desktop")
START_MENU = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs")


# --------------------------------------------------------------------------- #
# 1. 找快捷方式
# --------------------------------------------------------------------------- #
def find_shortcut(name: str) -> str | None:
    """按名字找 .lnk，先精确、再前缀、最后包含 —— 不要反过来包含。

    反例（本文件曾踩过）：查 "音乐客户端（***）" 时，规则写成
    `base in name or name in base` 会让 *****.lnk**（base="即时通讯软件（***）"）抢先命中，
    于是启动的是 即时通讯软件（***） 而不是 音乐客户端（***），然后干等 25 秒窗口不出现。
    """
    query = (name or "").strip().lower()
    if not query:
        return None
    scored: list[tuple[int, str]] = []
    dirs = [PUBLIC_DESKTOP, USER_DESKTOP, START_MENU]
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        for lnk in glob.glob(os.path.join(d, "**", "*.lnk"), recursive=True):
            base = os.path.splitext(os.path.basename(lnk))[0].lower()
            if base == query:
                score = 100
            elif base.startswith(query):
                score = 80
            elif query in base:
                score = 60
            else:
                continue
            scored.append((score, lnk))
    if not scored:
        return None
    scored.sort(key=lambda t: (-t[0], len(t[1])))
    return scored[0][1]


def shortcut_target(lnk: str) -> tuple[str, str]:
    """返回 (目标 exe, 工作目录)；解析失败返回 ("", "")。"""
    try:
        import win32com.client
        sh = win32com.client.Dispatch("WScript.Shell")
        sc = sh.CreateShortcut(lnk)
        return sc.TargetPath or "", sc.WorkingDirectory or ""
    except Exception:
        return "", ""


# --------------------------------------------------------------------------- #
# 2. 启动（必须走 Explorer shell）
# --------------------------------------------------------------------------- #
def launch(target: str, extra_args: str | None = None, settle_ms: int = 0) -> dict:
    """启动一个应用。

    target 可以是：应用名（"视频客户端（***）"）、.lnk 路径、或 .exe 路径。

    **一律经 explorer.exe 启动**（等同用户双击）：直接 CreateProcess 时，
    部分 Electron 应用（如视频客户端（***））会静默秒退，退出码 0 且没有任何提示。
    """
    path = target
    how = "path"
    if not os.path.exists(path):
        lnk = find_shortcut(target)
        if lnk:
            path, how = lnk, "shortcut"
        else:
            return {"ok": False, "error": f"找不到应用或快捷方式: {target!r}"}

    exe, workdir = ("", "")
    if path.lower().endswith(".lnk"):
        exe, workdir = shortcut_target(path)
    elif path.lower().endswith(".exe"):
        exe, workdir = path, os.path.dirname(path)

    # 启动前校验：目标 exe 的名字至少要跟请求里的一段对得上，否则拒绝启动
    req = (target or "").strip().lower()
    if exe and req and not path.lower().endswith(".exe"):
        exe_base = os.path.splitext(os.path.basename(exe))[0].lower()
        # 取请求里长度>=2 的片段（拉丁/数字部分）做交集判断
        latin = "".join(ch for ch in req if ch.isascii() and ch.isalnum())
        ok_names = (
            exe_base in req or req in exe_base
            or (latin and (latin in exe_base or exe_base in latin))
            or exe_base == req
        )
        if not ok_names:
            return {"ok": False,
                    "error": f"快捷方式『{os.path.basename(path)}』指向 {exe}，与请求 {target!r} 不符，已中止",
                    "target": path, "exe": exe,
                    "hint": "换个更精确的名字，或直接传 .lnk / .exe 的完整路径"}

    # Explorer shell 启动
    try:
        if extra_args:
            subprocess.run(["explorer.exe", path, extra_args], check=False)
        else:
            subprocess.run(["explorer.exe", path], check=False)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"explorer 启动失败: {exc}", "target": path}

    if settle_ms:
        time.sleep(settle_ms / 1000.0)

    return {
        "ok": True,
        "target": path,
        "how": how,
        "exe": exe,
        "workdir": workdir,
        "method": "explorer-shell",
        "note": "直接 Popen 会被某些 Electron 应用静默忽略，所以固定走 shell",
    }


# --------------------------------------------------------------------------- #
# 3. 找窗口 / 等窗口
# --------------------------------------------------------------------------- #
def _pid_info() -> dict[int, tuple[str, str]]:
    out: dict[int, tuple[str, str]] = {}
    for p in psutil.process_iter(["name", "pid", "exe"]):
        try:
            out[p.info["pid"]] = (p.info.get("name") or "", p.info.get("exe") or "")
        except Exception:
            continue
    return out


def find_windows(process: str | None = None,
                 exe_contains: str | None = None,
                 title_contains: str | None = None,
                 class_contains: str | None = None,
                 min_w: int = 200,
                 min_h: int = 150,
                 visible_only: bool = True) -> list[dict]:
    """按条件找顶层窗口。process 支持模糊（大小写不敏感），exe_contains 匹配完整路径。

    中文进程名（如 `视频客户端（***）.exe`）用 process 参数；不确定名字时用 exe_contains 更稳。
    """
    infos = _pid_info()
    found: list[dict] = []

    def _cb(hwnd, _):
        if visible_only and not win32gui.IsWindowVisible(hwnd):
            return
        rect = win32gui.GetWindowRect(hwnd)
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        if w < min_w or h < min_h:
            return
        title = win32gui.GetWindowText(hwnd)
        cls = win32gui.GetClassName(hwnd)
        if title_contains and title_contains.lower() not in title.lower():
            return
        if class_contains and class_contains.lower() not in cls.lower():
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            pid = 0
        name, exe = infos.get(pid, ("", ""))
        if process and process.lower() not in name.lower():
            return
        if exe_contains and exe_contains.lower() not in exe.lower():
            return
        found.append({
            "hwnd": hwnd, "pid": pid, "process": name, "exe": exe,
            "title": title, "class": cls,
            "rect": {"x": rect[0], "y": rect[1], "w": w, "h": h},
            "visible": bool(win32gui.IsWindowVisible(hwnd)),
            "minimized": bool(win32gui.IsIconic(hwnd)),
        })

    win32gui.EnumWindows(_cb, None)
    found.sort(key=lambda d: d["rect"]["w"] * d["rect"]["h"], reverse=True)
    return found


def wait_window(timeout_ms: int = 20000, poll_ms: int = 300, **criteria) -> dict:
    """等到出现满足条件的窗口，或超时。返回 {"ok", "elapsed_ms", "window"|"error"}。"""
    t0 = time.perf_counter()
    last: list[dict] = []
    while True:
        last = find_windows(**criteria)
        if last:
            return {"ok": True,
                    "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
                    "window": last[0]}
        if (time.perf_counter() - t0) * 1000 >= timeout_ms:
            return {"ok": False,
                    "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
                    "error": f"等待窗口超时（{timeout_ms} ms）",
                    "criteria": criteria}
        time.sleep(poll_ms / 1000.0)


# --------------------------------------------------------------------------- #
# 3.5 激活窗口（多策略，实测 AttachThreadInput 最靠得住）
# --------------------------------------------------------------------------- #
def activate(hwnd: int, tries: int = 3) -> dict:
    """把窗口弄到前台。返回 {"ok", "method", "foreground"}。

    Windows 经常拒绝 SetForegroundWindow（返回错误或静默失败），
    实测顺序：AttachThreadInput → minimize+restore → SetForegroundWindow。
    音乐客户端（***）这类标题为空、被大窗覆盖的应用，只有 AttachThreadInput 能拉上来。
    """
    u32 = ctypes.windll.user32
    k32 = ctypes.windll.kernel32

    def _is_fg() -> bool:
        return win32gui.GetForegroundWindow() == hwnd

    def _attach_force() -> None:
        fg = u32.GetForegroundWindow()
        try:
            t_fg = win32process.GetWindowThreadProcessId(fg)[0]
        except Exception:
            t_fg = 0
        t_me = k32.GetCurrentThreadId()
        attached = False
        try:
            if t_fg and t_fg != t_me:
                attached = bool(u32.AttachThreadInput(t_fg, t_me, True))
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
        finally:
            if attached:
                u32.AttachThreadInput(t_fg, t_me, False)

    def _restore_force() -> None:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.3)
        win32gui.SetForegroundWindow(hwnd)

    methods = (("attach_input", _attach_force),
               ("restore+setforeground", _restore_force),
               ("setforeground", lambda: win32gui.SetForegroundWindow(hwnd)))
    for name, fn in methods:
        for _ in range(max(1, tries)):
            try:
                fn()
            except Exception:
                pass
            time.sleep(0.35)
            if _is_fg():
                return {"ok": True, "method": name,
                        "foreground": win32gui.GetWindowText(win32gui.GetForegroundWindow())}
    return {"ok": False, "method": None,
            "foreground": win32gui.GetWindowText(win32gui.GetForegroundWindow())}


# --------------------------------------------------------------------------- #
# 4. 退出（关窗 ≠ 退出，必须清进程）
# --------------------------------------------------------------------------- #
def _pids_matching(process: str | None, exe_contains: str | None) -> set[int]:
    out: set[int] = set()
    for pid, (name, exe) in _pid_info().items():
        if process and process.lower() not in name.lower():
            continue
        if exe_contains and exe_contains.lower() not in exe.lower():
            continue
        if process or exe_contains:
            out.add(pid)
    return out


def exit_app(process: str | None = None,
             exe_contains: str | None = None,
             timeout_ms: int = 8000,
             force: bool = True) -> dict:
    """先温和关闭所有窗口，超时后强制结束进程。返回计数与过程。"""
    if not (process or exe_contains):
        return {"ok": False, "error": "process 与 exe_contains 至少要给一个"}

    pids = _pids_matching(process, exe_contains)
    before = len(pids)
    if not pids:
        return {"ok": True, "already_exited": True, "pids_before": 0}

    windows_closed = 0

    def _cb(hwnd, _):
        nonlocal windows_closed
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            return
        if pid in pids and win32gui.IsWindowVisible(hwnd):
            try:
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                windows_closed += 1
            except Exception:
                pass

    win32gui.EnumWindows(_cb, None)

    t0 = time.perf_counter()
    while (time.perf_counter() - t0) * 1000 < timeout_ms:
        if not _pids_matching(process, exe_contains):
            return {"ok": True, "pids_before": before, "windows_closed": windows_closed,
                    "method": "wm_close",
                    "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)}
        time.sleep(0.3)

    remaining = _pids_matching(process, exe_contains)
    terminated = 0
    if force:
        for pid in remaining:
            try:
                psutil.Process(pid).terminate()
                terminated += 1
            except Exception:
                pass
        for _ in range(20):
            if not _pids_matching(process, exe_contains):
                break
            time.sleep(0.2)

    left = len(_pids_matching(process, exe_contains))
    return {
        "ok": left == 0,
        "pids_before": before,
        "windows_closed": windows_closed,
        "terminated": terminated,
        "pids_after": left,
        "method": "wm_close+terminate" if terminated else "wm_close",
        "note": "关窗不等于退出：托盘驻留的进程必须显式结束" if terminated else "",
    }


# --------------------------------------------------------------------------- #
# 5. 按条件关窗（任务收尾用：本次开过的窗口要自己关掉）
# --------------------------------------------------------------------------- #
def close_windows(process: str | None = None,
                  exe_contains: str | None = None,
                  title_contains: str | None = None,
                  exact_title: str | None = None,
                  wait_ms: int = 1500) -> dict:
    """关掉满足条件的可见窗口（只发 WM_CLOSE，不杀进程）。

    用于任务收尾：把自己打开的窗口关掉，别留给用户手动收拾。
    注意：只关窗口不动进程，避免误杀用户正在用的应用。
    """
    targets: list[dict] = []

    def _cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if exact_title is not None and title.strip() != exact_title:
            return
        if title_contains and title_contains.lower() not in title.lower():
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            pr = psutil.Process(pid)
            name, exe = pr.name(), pr.exe()
        except Exception:
            name, exe = "", ""
        if process and process.lower() not in name.lower():
            return
        if exe_contains and exe_contains.lower() not in exe.lower():
            return
        targets.append({"hwnd": hwnd, "pid": pid, "title": title, "process": name})

    win32gui.EnumWindows(_cb, None)

    closed = 0
    for t in targets:
        try:
            win32gui.PostMessage(t["hwnd"], win32con.WM_CLOSE, 0, 0)
            closed += 1
        except Exception:
            pass

    if wait_ms:
        time.sleep(wait_ms / 1000.0)

    still = 0
    for t in targets:
        try:
            if win32gui.IsWindow(t["hwnd"]) and win32gui.IsWindowVisible(t["hwnd"]):
                still += 1
        except Exception:
            pass

    return {"ok": still == 0, "found": len(targets), "closed": closed,
            "still_open": still,
            "windows": [{"hwnd": t["hwnd"], "title": t["title"][:30]} for t in targets]}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    args = argv[2:]

    def opt(name: str, default: str | None = None) -> str | None:
        if name in args:
            i = args.index(name)
            if i + 1 < len(args):
                return args[i + 1]
        return default

    if cmd == "launch":
        name = opt("--name") or (args[0] if args and not args[0].startswith("--") else None)
        if not name:
            print("用法: appkit.py launch <应用名|lnk|exe>")
            return 2
        res = launch(name, settle_ms=int(opt("--settle", "0") or 0))
    elif cmd == "wait":
        res = wait_window(
            timeout_ms=int(opt("--timeout", "20000") or 20000),
            process=opt("--process"),
            exe_contains=opt("--exe"),
            title_contains=opt("--title"),
        )
    elif cmd == "exit":
        res = exit_app(process=opt("--process"), exe_contains=opt("--exe"),
                       timeout_ms=int(opt("--timeout", "8000") or 8000))
    elif cmd == "find":
        res = {"windows": find_windows(process=opt("--process"),
                                       exe_contains=opt("--exe"),
                                       title_contains=opt("--title"))}
    elif cmd == "close":
        res = close_windows(process=opt("--process"),
                            exe_contains=opt("--exe"),
                            title_contains=opt("--title"),
                            exact_title=opt("--exact"))
    elif cmd == "shortcut":
        lnk = find_shortcut(args[0]) if args else None
        res = {"shortcut": lnk, "target": shortcut_target(lnk)[0] if lnk else ""}
    else:
        print(f"未知命令: {cmd}")
        return 2

    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
