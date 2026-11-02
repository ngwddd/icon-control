"""panic_watch.py — 独立急停看守进程（"连按两下 ESC = 立刻松手"）

为什么要有它（用户 2026-10-25 要求）：
    机器人脚本自己也会检查急停标志，但如果脚本卡在一次长点击里、或者逻辑写漏了检查，
    光靠脚本自救不可靠。这个看守进程是**进程外**的，一旦听到两次 ESC，
    直接把所有正在跑的自动化进程杀掉 —— 物理上保证鼠标立刻不再动。

用法：
    venv\\Scripts\\python.exe panic_watch.py            # 前台看守（会打印）
    start /b venv\\Scripts\\python.exe panic_watch.py    # 后台看守

触发后行为：
    1. 立刻打印 ✋ 提示
    2. 枚举 python 进程里命令行含 *_bot*.py / *_run*.py / macro_run / desk.py 的，全部终止
    3. 打印被杀的 PID 列表，然后退出（不自动重启任何东西）
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "venv", "Lib", "site-packages"))

from computer_mcp import panic, process_registry, security  # noqa: E402

import psutil  # noqa: E402

# 哪些进程算"自动化进程"（急停时必须一并清掉）
AUTOMATION_PATTERNS = []  # Names never establish ownership.


def automation_pids(exclude_self: bool = True) -> list[tuple[int, str]]:
    me = os.getpid()
    hits: list[tuple[int, str]] = []
    for p in process_registry.registered():
        try:
            pid = p.pid
            if exclude_self and pid == me:
                continue
            hits.append((pid, 'registered Icon Control process'))
        except Exception:
            continue
    return hits


def main() -> int:
    sw = panic.PanicSwitch()
    sw.start()
    print(f"[watchdog] pid={os.getpid()} 看守中 —— 连按两下 ESC 我会立刻杀掉所有自动化进程", flush=True)

    while not sw.wait(timeout=0.5):
        pass

    print("[watchdog] ✋ 收到急停，开始清理自动化进程", flush=True)
    # Cooperative cancellation releases owned held inputs before forced exit.
    try:
        security.latch_stop()
    except Exception as exc:
        print('[watchdog] Durable stop failed; owned-process cleanup continues: '+type(exc).__name__,flush=True)
    time.sleep(.25)
    victims = [p for p in process_registry.registered() if p.pid != os.getpid()]
    if not victims:
        print("[watchdog] 没有发现正在跑的自动化进程（可能已经停了）", flush=True)
    for process in victims:
        pid = process.pid
        try:
            process.terminate()  # psutil verifies PID/create-time before termination.
            print(f"[watchdog]   ✓ 已终止 {pid}", flush=True)
        except Exception as exc:
            print(f"[watchdog]   ✗ {pid} 终止失败: {exc}", flush=True)

    time.sleep(1.0)
    left = [p for p in process_registry.registered() if p.pid != os.getpid()]
    if left:
        for process in left:
            try:
                process.kill()
                print(f"[watchdog]   ✓ 强杀 {process.pid}", flush=True)
            except Exception:
                pass

    print("[watchdog] 已松手，等你指示。", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
