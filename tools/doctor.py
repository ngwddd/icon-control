"""doctor.py — 桌面自动化环境一键体检。

为什么需要它：2026-10-25 那次排查里，70% 的时间花在"到底是环境问题还是代码问题"上，
而且我自己写的诊断工具还骗了我两轮。这个脚本把所有**能自动判定的环境前提**
一次列清楚，并且对每一项都给出「可信 / 不可信 / 异常」三态，不给含糊结论。

用法：
    venv\\Scripts\\python.exe doctor.py            # 人类可读
    venv\\Scripts\\python.exe doctor.py --json     # 机器可读（供 agent 判断）

退出码：
    0 = 全部正常
    1 = 有警告（能跑，但某些能力受限）
    2 = 有致命问题（鼠标/键盘这类核心能力不可用）
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import win32gui  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

# 已知会拦截模拟输入的驱动/服务（按命中即提示处置）
SUSPECT_DRIVERS = {
    "CCInputProtector": "笔记本 Control Center 的输入保护驱动（会拦 SendInput）",
    "hrdevmon": "安全软件（***）设备监控驱动",
    "sysdiag": "安全软件（***）核心驱动",
    "hrwfpdrv": "安全软件（***）防火墙（网络类，不是输入）",
    "***": "安全软件（***） NDIS 网络过滤（停它会断网）",
    "HKKbdFltr": "OEM 键盘类过滤驱动",
    "HKMouFltr": "OEM 鼠标类过滤驱动",
    "nfwfp": "NetFilter SDK WFP（网络类）",
}


def _r(label: str, status: str, detail: str, hint: str = "") -> dict:
    return {"label": label, "status": status, "detail": detail, "hint": hint}


# --------------------------------------------------------------------------- #
# 1. 进程身份
# --------------------------------------------------------------------------- #
def check_identity() -> list[dict]:
    out: list[dict] = []
    try:
        adv = ctypes.windll.advapi32
        k32 = ctypes.windll.kernel32
        adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        adv.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        h = wintypes.HANDLE()
        if adv.OpenProcessToken(k32.GetCurrentProcess(), 0x0008, ctypes.byref(h)):
            size = wintypes.DWORD(0)
            adv.GetTokenInformation(h, 25, None, 0, ctypes.byref(size))   # TokenIntegrityLevel
            buf = ctypes.create_string_buffer(size.value)
            if adv.GetTokenInformation(h, 25, buf, size, ctypes.byref(size)):
                sid_ptr = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
                adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
                s = ctypes.c_wchar_p()
                if adv.ConvertSidToStringSidW(sid_ptr, ctypes.byref(s)):
                    names = {"S-1-16-4096": "LOW", "S-1-16-8192": "MEDIUM",
                             "S-1-16-12288": "HIGH", "S-1-16-16384": "SYSTEM"}
                    lvl = names.get(s.value, s.value)
                    bad = lvl == "LOW"
                    out.append(_r("完整性级别", "warn" if bad else "ok", lvl,
                                  "LOW 级别无法向普通窗口注入输入" if bad else ""))
            elev = wintypes.DWORD(0)
            ret = wintypes.DWORD(0)
            if adv.GetTokenInformation(h, 20, ctypes.byref(elev), ctypes.sizeof(elev), ctypes.byref(ret)):
                out.append(_r("管理员权限", "ok" if elev.value else "warn",
                              "已提权" if elev.value else "普通用户",
                              "停服务/改驱动需要管理员；可用 Start-Process -Verb RunAs 触发 UAC"))
            ac = wintypes.DWORD(0)
            if adv.GetTokenInformation(h, 29, ctypes.byref(ac), ctypes.sizeof(ac), ctypes.byref(ret)):
                out.append(_r("AppContainer", "warn" if ac.value else "ok",
                              "在沙箱里" if ac.value else "不在沙箱里",
                              "AppContainer 会限制跨进程输入" if ac.value else ""))
        else:
            out.append(_r("令牌", "unknown", "OpenProcessToken 失败"))
    except Exception as exc:  # noqa: BLE001
        out.append(_r("令牌", "unknown", f"读取失败: {exc}"))
    return out


# --------------------------------------------------------------------------- #
# 2. DPI / 屏幕
# --------------------------------------------------------------------------- #
def check_display() -> list[dict]:
    out: list[dict] = []
    u32 = ctypes.windll.user32
    w = u32.GetSystemMetrics(0)
    h = u32.GetSystemMetrics(1)
    try:
        dpi = u32.GetDpiForSystem()
    except Exception:
        dpi = 0
    scale = round(dpi / 96, 2) if dpi else None
    ok = w >= 640 and h >= 480
    out.append(_r("屏幕", "ok" if ok else "fatal", f"{w}x{h}",
                  "" if ok else "分辨率异常"))
    out.append(_r("DPI", "ok" if dpi else "warn", f"{dpi} ({scale}x)",
                  "" if dpi == 96 else "非 100% 缩放时务必先 SetProcessDpiAwareness(2)，否则坐标会偏"))
    try:
        remote = u32.GetSystemMetrics(0x1000)
        out.append(_r("远程会话", "warn" if remote else "ok",
                      "是（RDP）" if remote else "否",
                      "远程会话里合成输入的可见性可能不同" if remote else ""))
    except Exception:
        pass
    return out


# --------------------------------------------------------------------------- #
# 3. 输入链路（唯一可信判据：系统文本编辑器打字 + 剪贴板回读）
# --------------------------------------------------------------------------- #
def check_input() -> list[dict]:
    out: list[dict] = []
    try:
        import win32clipboard
    except Exception as exc:  # noqa: BLE001
        return [_r("输入链路", "unknown", f"win32clipboard 不可用: {exc}")]

    def set_clip(t: str) -> None:
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(t)
        win32clipboard.CloseClipboard()

    def get_clip() -> str:
        try:
            win32clipboard.OpenClipboard()
            d = win32clipboard.GetClipboardData()
            win32clipboard.CloseClipboard()
            return str(d)
        except Exception:  # noqa: BLE001
            return ""

    # L1 光标移动（不经过 SendInput）
    try:
        from pynput.mouse import Controller as MouseController
        mc = MouseController()
        mc.position = (300, 300)
        time.sleep(0.12)
        a = win32gui.GetCursorPos()
        mc.position = (700, 500)
        time.sleep(0.12)
        b = win32gui.GetCursorPos()
        near = (abs(a[0] - 300) <= 40 and abs(a[1] - 300) <= 40
                and abs(b[0] - 700) <= 40 and abs(b[1] - 500) <= 40)
        out.append(_r("光标移动(SetCursorPos)", "ok" if near else "fatal",
                      f"{a} -> {b}", "" if near else "连光标都移不动：进程没有桌面权限"))
    except Exception as exc:  # noqa: BLE001
        out.append(_r("光标移动(SetCursorPos)", "fatal", f"{exc}"))

    # L2 键盘注入（系统文本编辑器 + 剪贴板回读）
    mark = f"对话壳（***）_DOCTOR_{int(time.time()) % 100000}"
    set_clip("SENTINEL")
    probe_name = f"doctor_probe_{os.getpid()}_{int(time.time()) % 1000}.txt"
    target = os.path.join(os.environ.get("TEMP", "."), probe_name)
    try:
        with open(target, "w", encoding="utf-8"):
            pass
    except OSError:
        target = None

    hwnd = 0
    try:
        from pynput.keyboard import Controller as KeyboardController, Key
        kb = KeyboardController()
        if target:
            subprocess.Popen(["***.exe", target])
            time.sleep(3.0)
            found: list[int] = []

            def _cb(h, _):
                if (win32gui.IsWindowVisible(h)
                        and probe_name.lower() in win32gui.GetWindowText(h).lower()):
                    found.append(h)
            win32gui.EnumWindows(_cb, None)
            hwnd = found[0] if found else 0

        fg_ok = False
        if hwnd:
            try:
                from computer_mcp import macro_ext
                macro_ext._ensure_usable(hwnd)
            except Exception:
                try:
                    win32gui.SetForegroundWindow(hwnd)
                except Exception:
                    pass
            time.sleep(0.7)
            fg_ok = win32gui.GetForegroundWindow() == hwnd

        if not hwnd:
            out.append(_r("键盘注入", "unknown", "没能打开系统文本编辑器靶子"))
        elif not fg_ok:
            out.append(_r("键盘注入", "unknown",
                          "系统文本编辑器没拿到前台，本次判定不可信",
                          "改用人工确认：手动点进任意输入框，用 desk.py 发一次 type"))
        else:
            kb.type(mark)
            time.sleep(0.8)
            kb.press(Key.ctrl); kb.press("a"); kb.release("a"); kb.release(Key.ctrl)
            time.sleep(0.3)
            kb.press(Key.ctrl); kb.press("c"); kb.release("c"); kb.release(Key.ctrl)
            time.sleep(0.9)
            got = get_clip()
            ok = mark in got
            hint = ""
            if not ok:
                hint = ("真被拦：先看有没有模态对话框挡着，再查 CCInputProtector / OEM 类过滤驱动"
                        "（见 SUSPECT_DRIVERS）")
            out.append(_r("键盘注入", "ok" if ok else "fatal",
                          f"回读={got[:28]!r}", hint))
            # 收拾现场
            try:
                kb.press(Key.ctrl); kb.press("a"); kb.release("a"); kb.release(Key.ctrl)
                time.sleep(0.2)
                kb.press(Key.delete); kb.release(Key.delete)
                time.sleep(0.4)
                win32gui.PostMessage(hwnd, 0x0010, 0, 0)
                time.sleep(0.8)
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        out.append(_r("键盘注入", "unknown", f"{exc}"))
    finally:
        if target and os.path.exists(target):
            try:
                os.remove(target)
            except OSError:
                pass
    return out


# --------------------------------------------------------------------------- #
# 4. 输入相关驱动 / 服务
# --------------------------------------------------------------------------- #
def check_drivers() -> list[dict]:
    out: list[dict] = []
    try:
        ps = (
            "Get-CimInstance Win32_SystemDriver | Where-Object { $_.State -eq 'Running' } | "
            "Select-Object Name,State | ConvertTo-Json -Compress"
        )
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, timeout=60,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        data = json.loads(r.stdout or "[]")
        if isinstance(data, dict):
            data = [data]
        running = {str(d.get("Name", "")): d for d in data}
        hits = [n for n in running if n in SUSPECT_DRIVERS]
        if hits:
            for n in hits:
                out.append(_r(f"驱动 {n}", "warn", "运行中", SUSPECT_DRIVERS[n]))
        else:
            out.append(_r("输入相关驱动", "ok", "没有已知的输入拦截驱动在跑"))
    except Exception as exc:  # noqa: BLE001
        out.append(_r("输入相关驱动", "unknown", f"枚举失败: {exc}"))
    return out


# --------------------------------------------------------------------------- #
# 5. 补丁与工具注册
# --------------------------------------------------------------------------- #
def check_patch() -> list[dict]:
    out: list[dict] = []
    try:
        from computer_mcp import anchor_mem, macro_ext, ocr_ext, ui_ext  # noqa: F401
        mods = ["anchor_mem", "macro_ext", "ocr_ext", "ui_ext"]
        out.append(_r("扩展模块", "ok", "全部可导入: " + ", ".join(mods)))
    except Exception as exc:  # noqa: BLE001
        out.append(_r("扩展模块", "fatal", f"导入失败: {exc}",
                      "跑 _patched\\reapply.py 重新打补丁"))

    try:
        import computer_mcp
        mcp_src = open(os.path.join(os.path.dirname(computer_mcp.__file__), "mcp.py"),
                       encoding="utf-8").read()
        added = ["screen_state", "wait_for_change", "capture_config", "batch", "ui_tree",
                 "ui_find", "ui_click", "ui_invoke", "ui_set_text", "macro_list",
                 "macro_save", "macro_run", "ocr_read", "find_text", "click_text",
                 "anchor_mem"]
        missing = [n for n in added if f'"{n}"' not in mcp_src and f"'{n}'" not in mcp_src]
        out.append(_r("工具注册", "ok" if not missing else "fatal",
                      f"16 个新增 MCP 工具全部注册" if not missing else f"缺 {len(missing)}: " + ", ".join(missing),
                      "" if not missing else "跑 _patched\\reapply.py 重新打补丁"))
    except Exception as exc:  # noqa: BLE001
        out.append(_r("工具注册", "unknown", f"{exc}"))

    # _patched 与安装副本是否一致
    try:
        import computer_mcp
        pkg = os.path.dirname(computer_mcp.__file__)
        drift = []
        for name in ("macro_ext.py", "anchor_mem.py", "ocr_ext.py", "ui_ext.py", "mcp.py"):
            a = os.path.join(pkg, name)
            b = os.path.join(HERE, "_patched", name)
            if os.path.exists(a) and os.path.exists(b):
                if open(a, "rb").read() != open(b, "rb").read():
                    drift.append(name)
        out.append(_r("补丁一致性", "ok" if not drift else "warn",
                      "一致" if not drift else "漂移: " + ", ".join(drift),
                      "" if not drift else "把 venv 里的文件同步回 _patched\\"))
    except Exception as exc:  # noqa: BLE001
        out.append(_r("补丁一致性", "unknown", f"{exc}"))
    return out


# --------------------------------------------------------------------------- #
# 6. 记忆库
# --------------------------------------------------------------------------- #
def check_memory() -> list[dict]:
    out: list[dict] = []
    try:
        from computer_mcp import anchor_mem
        st = anchor_mem.stats() if hasattr(anchor_mem, "stats") else {}
        inner = st.get("stats", {}) if isinstance(st, dict) else {}
        apps = len(inner)
        elems = sum(v.get("elements", 0) for v in inner.values() if isinstance(v, dict))
        hits = sum(v.get("hits", 0) for v in inner.values() if isinstance(v, dict))
        misses = sum(v.get("misses", 0) for v in inner.values() if isinstance(v, dict))
        out.append(_r("记忆库", "ok" if elems else "warn",
                      f"{apps} 个应用 / {elems} 个元素 / 命中 {hits} / 未命中 {misses}",
                      "" if elems else "还没有学到任何锚点；跑一次真实任务即可自动积累"))
    except Exception as exc:  # noqa: BLE001
        out.append(_r("记忆库", "unknown", f"{exc}"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    results: list[dict] = []
    for fn in (check_identity, check_display, check_input,
               check_drivers, check_patch, check_memory):
        try:
            results.extend(fn())
        except Exception as exc:  # noqa: BLE001
            results.append(_r(fn.__name__, "unknown", f"检查本身抛异常: {exc}"))

    fatal = [r for r in results if r["status"] == "fatal"]
    warn = [r for r in results if r["status"] == "warn"]
    code = 2 if fatal else (1 if warn else 0)

    if args.json:
        print(json.dumps({"exit": code, "checks": results}, ensure_ascii=False, indent=2))
        return code

    icon = {"ok": "✓", "warn": "!", "fatal": "✗", "unknown": "?"}
    print("=== 桌面自动化环境体检 ===")
    for r in results:
        print(f"  {icon.get(r['status'], '?')} {r['label']:22} {r['detail']}")
        if r["hint"]:
            print(f"      → {r['hint']}")
    print()
    if fatal:
        print(f"结论：{len(fatal)} 项致命 / {len(warn)} 项警告 —— 核心能力不可用，先修下面这些：")
        for r in fatal:
            print(f"  · {r['label']}: {r['detail']}")
    elif warn:
        print(f"结论：可用，但 {len(warn)} 项警告需要注意。")
    else:
        print("结论：全部正常，可以开工。")
    return code


if __name__ == "__main__":
    sys.exit(main())
