"""mouse_permission.py — 读 GUI 上那个「鼠标·已授权 / 未授权」开关的真实状态。

为什么要单独做这个：这个开关是**用户授权控制**（user-only authority），
按设计只能由人在 GUI 里点，agent 不许自己把它打开。所以 agent 侧只做**只读检查**：
动鼠标之前先跑这个脚本，未授权就停手、问用户。

判据只认屏幕上的那个胶囊按钮（它的文案是稳定且机器可读的）：
    绿色 + "鼠标·已授权"  → exit 0
    灰色 + "鼠标·未授权"  → exit 2
    找不到按钮          → exit 3（当未授权对待）

用法：
    venv\\Scripts\\python.exe mouse_permission.py          # 打印状态并给退出码
    venv\\Scripts\\python.exe mouse_permission.py --quiet  # 只给退出码
"""

from __future__ import annotations

import argparse
import os
import re
import sys

try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "venv", "Lib", "site-packages"))

GRANTED, DENIED, UNKNOWN = 0, 2, 3

# 输入框工具栏那一条带；胶囊在「完全权限」右侧、模型选择器左侧
SEARCH_REGIONS = [
    {"x": 900, "y": 1180, "w": 1200, "h": 120},
    {"x": 0, "y": 1100, "w": 2560, "h": 300},
]


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def read_state() -> tuple[int, str]:
    """复用硬闸门的状态（v0.4：**桥优先**，OCR 只当后备）。

    以前这里直接调 _read_pill() 读屏幕，结果被聊天记录里的“鼠标·已授权”字样
    骗成已授权（假阳性 —— 最危险的方向）。现在统一走 permission.status()：
      来源 bridge  → 客户端插件经本地 HTTP 直报，最可信
      来源 screen  → OCR 后备（扫描区域已收窄到输入框工具栏）
      来源 unknown → 读不到，按未授权处理
    """
    try:
        from computer_mcp import permission as _perm
    except Exception as exc:
        return UNKNOWN, f"permission import failed: {exc}"
    try:
        st = _perm.status()
    except Exception as exc:
        return UNKNOWN, f"status() failed: {exc}"
    detail = f"source={st.get('source')}  age={st.get('age_s')}s"
    if st.get("granted"):
        return GRANTED, detail
    if st.get("source") in ("bridge", "screen"):
        return DENIED, detail
    return UNKNOWN, detail


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    code, text = read_state()
    label = {GRANTED: "已授权（绿色）", DENIED: "未授权（灰色）", UNKNOWN: "读不到开关"}[code]
    if not args.quiet:
        print(f"鼠标接管权限：{label}")
        print(f"  判定依据：{text}")
        if code != GRANTED:
            print("  → 未授权：不得移动鼠标 / 按键 / 点击。请让用户在 GUI 里点一下开关。")
    return code


if __name__ == "__main__":
    sys.exit(main())
