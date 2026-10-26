r"""Re-apply the Shell desktop-MCP patch after reinstalling/upgrading computer-mcp.

Copies the patched files from this folder into site-packages and then verifies
that the server exposes the expected tools.

Usage:  venv\Scripts\python.exe _patched\reapply.py
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
SP = os.path.join(BASE, "venv", "Lib", "site-packages", "computer_mcp")
PY = os.path.join(BASE, "venv", "Scripts", "python.exe")

FILES = [
    ("core_screenshot.py", os.path.join(SP, "core", "screenshot.py")),
    ("mcp.py", os.path.join(SP, "mcp.py")),
    ("cli.py", os.path.join(SP, "cli.py")),
    ("ui_ext.py", os.path.join(SP, "ui_ext.py")),
    ("macro_ext.py", os.path.join(SP, "macro_ext.py")),
    ("ocr_ext.py", os.path.join(SP, "ocr_ext.py")),
    ("anchor_mem.py", os.path.join(SP, "anchor_mem.py")),
]

EXPECT = [
    "screen_state", "wait_for_change", "capture_config",
    "batch", "ui_tree", "ui_find", "ui_click", "ui_invoke", "ui_set_text",
    "macro_list", "macro_save", "macro_run",
    "ocr_read", "find_text", "click_text",
]


def main() -> int:
    if not os.path.isdir(SP):
        print("computer_mcp not found at", SP)
        return 1
    for src_name, dst in FILES:
        src = os.path.join(HERE, src_name)
        if not os.path.exists(src):
            print("missing patch file:", src)
            return 1
        if not os.path.exists(dst + ".orig"):
            shutil.copy2(dst, dst + ".orig")
            print("backed up ->", os.path.basename(dst) + ".orig")
        shutil.copy2(src, dst)
        print("patched ->", dst)

    check = subprocess.run(
        [PY, "-c",
         "import computer_mcp.mcp as m;"
         "import asyncio;"
         "ts=[t.name for t in asyncio.run(m.list_tools())];"
         "print(len(ts));"
         "print([n for n in %r if n not in ts])" % (EXPECT,)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    print("--- verify ---")
    print((check.stdout or "").strip())
    if check.returncode != 0:
        print((check.stderr or "")[-500:])
    print("done; restart Shell to load it")
    return 0


if __name__ == "__main__":
    sys.exit(main())

