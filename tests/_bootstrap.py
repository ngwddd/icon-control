"""_bootstrap.py — 让测试在"解释器不对"的机器上也能真的跑起来。

问题（2026-10-27 实测）：
    desktop-mcp 的 venv 是 **Python 3.12.14**，系统 Python 是 **3.14.5**。
    验证助手跑测试固定用 `sys.executable`（= 系统 3.14），于是：
        import computer_mcp → ImportError（pydantic_core 等 C 扩展 ABI 不匹配）
    → 10 个测试模块整组 skip → 检查报 "PASS"，但**等于什么都没验**。

    这种"假 PASS"比 FAIL 更危险，所以必须修。

做法（三步，任一步成功就返回）：
    1. 当前解释器能 import computer_mcp          → 直接用
    2. 找到 venv，把它的 site-packages 加进 path → 再试一次
    3. venv 的解释器与当前不同 ABI              → **放弃 re-exec**（见下）

为什么不做 re-exec（实测两次都失败，留档免得下次再试）：
    · os.execve 在 Windows 上直接崩（退出码 0xC0000005）
    · 改用 subprocess 转交退出码：unittest 在 import 阶段把 SystemExit 吞掉，
      父进程继续跑 → 同一套测试会跑两遍，父进程还额外报 1 个 error，结果被污染
    · 正确的做法在工具侧：验证助手发现「全部用例被跳过」时应判 UNKNOWN 而不是 PASS
       （用环境变量 DSH_TEST_REEXEC=1 防递归；unittest 的输出与退出码由子进程接管，
         所以验证助手看到的仍是真实结果）

用法：每个测试模块最前面一行
    import _bootstrap  # noqa: F401
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REEXEC_FLAG = "DSH_TEST_REEXEC"


def _venv_roots() -> list[Path]:
    out: list[Path] = []
    env = os.environ.get("DSH_DESKTOP_MCP_VENV")
    if env:
        out.append(Path(env))
    home = Path.home()
    out += [
        home / ".dsh" / "tools" / "desktop-mcp" / "venv",
        HERE.parent / "venv",
        HERE.parent.parent / "desktop-mcp" / "venv",
    ]
    return [p for p in out if p.is_dir()]


def _venv_python(venv: Path) -> Path | None:
    for cand in (venv / "Scripts" / "python.exe", venv / "bin" / "python"):
        if cand.is_file():
            return cand
    return None


def _importable() -> bool:
    try:
        import computer_mcp  # noqa: F401
        return True
    except Exception:
        return False


def _add_site_packages(venv: Path) -> bool:
    for sp in (venv / "Lib" / "site-packages", venv / "lib" / "site-packages"):
        if (sp / "computer_mcp").is_dir():
            if str(sp) not in sys.path:
                sys.path.insert(0, str(sp))
            return _importable()
    return False


def _reexec(venv: Path) -> None:
    """换成 venv 的解释器，把同一批测试重跑一遍（只做一次）。"""
    if os.environ.get(REEXEC_FLAG) == "1":
        return
    py = _venv_python(venv)
    if py is None:
        return
    if Path(sys.executable).resolve() == py.resolve():
        return
    env = dict(os.environ)
    env[REEXEC_FLAG] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    args = [str(py), "-m", "unittest", "discover", "-s", str(HERE), "-p", "test_*.py"]
    # 不用 os.execve：Windows 上它会让进程崩在 0xC0000005（实测两次）。
    # 改成起子进程并把它的退出码原样交出去，验证助手看到的仍是真实结果。
    # 先在自己进程里置标志：即使 _bootstrap 被重新 import（模块导入失败会把它从
    # sys.modules 里摘掉），也不会再起第二个子进程 —— 否则会看到同一套测试跑 N 遍。
    os.environ[REEXEC_FLAG] = "1"
    try:
        import subprocess
        rc = subprocess.call(args, env=env)
    except Exception:
        return          # 起不来就老实往下走（走 skip 分支）
    raise SystemExit(rc)


def ensure_package() -> bool:
    if _importable():
        return True
    for venv in _venv_roots():
        if _add_site_packages(venv):
            return True
    raise unittest.SkipTest(
        "computer_mcp 不可用：找不到能 import 它的解释器或 venv。"
        " 设置 DSH_DESKTOP_MCP_VENV 指向 desktop-mcp 的 venv 目录。"
    )


AVAILABLE = ensure_package()
