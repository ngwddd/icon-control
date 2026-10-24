"""desk.py - one-shot CLI for the computer-mcp MCP server.

Usage:
    desk.py --list                        list all tool names
    desk.py <tool> [json-args]            call one tool, print text result
    desk.py <tool> [json-args] --screen   also allow the automatic screenshot

Argument forms (Windows shells destroy inline JSON with quotes, prefer files):
    desk.py get_window_info '{"hwnd":123}'        inline (short args only)
    desk.py batch @C:\\path\\job.json              from a file
    desk.py batch C:\\path\\job.json               bare .json path works too
    desk.py batch -  < job.json                   read from stdin

Examples:
    desk.py list_windows
    desk.py batch @_batch_demo.json
    desk.py ui_tree '{"hwnd":123,"depth":4}'
    desk.py move_window '{"hwnd":123,"x":0,"y":0,"width":960,"height":1080}'

Safety defaults applied on every run:
    observe_screen = false            (JSON-only output unless --screen)
    disallowed_hotkeys = alt+f4, ctrl+alt+del, win+l
Kept ASCII-only on purpose.
"""

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

VENV_PY = os.path.join(os.path.expanduser("~"), ".dsh", "tools",
                      "desktop-mcp", "venv", "Scripts", "python.exe")
SERVER_ARGS = ["-m", "computer_mcp", "serve", "mcp"]
SAFE_HOTKEYS = ["alt+f4", "ctrl+alt+del", "win+l"]


async def run(tool: str, args: dict, want_screen: bool) -> int:
    params = StdioServerParameters(
        command=VENV_PY,
        args=SERVER_ARGS,
        env={"PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            if tool == "--list":
                tools = await session.list_tools()
                for t in tools.tools:
                    print(t.name)
                return 0

            await session.call_tool(
                "set_config",
                {
                    "observe_screen": bool(want_screen),
                    "disallowed_hotkeys": SAFE_HOTKEYS,
                },
            )

            res = await session.call_tool(tool, args)
            printed_text = False
            for c in res.content:
                txt = getattr(c, "text", None)
                if txt is not None:
                    print(txt)
                    printed_text = True
                elif getattr(c, "type", "") == "image" and want_screen:
                    print("[screenshot omitted by desk.py]")
            if not printed_text:
                print("[no text content returned]")
            return 0 if not getattr(res, "isError", False) else 2


def _load_args(argv: list[str]) -> dict:
    """Accept inline JSON, '@/path/to/file.json', a bare existing .json path,
    or '-' meaning read stdin. Windows shells mangle inline JSON badly, so the
    file/stdin forms are the reliable ones for anything with quotes."""
    if len(argv) < 2 or not argv[1].strip():
        return {}
    raw = argv[1].strip()

    if raw == "-":
        return json.load(sys.stdin)

    path = raw[1:] if raw.startswith("@") else raw
    if (raw.startswith("@") or path.lower().endswith(".json")) and os.path.exists(path):
        # utf-8-sig: files written by PowerShell's -Encoding UTF8 carry a BOM
        with open(path, "r", encoding="utf-8-sig") as fh:
            return json.load(fh)

    return json.loads(raw)


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        return 1
    want_screen = "--screen" in argv
    argv = [a for a in argv if a != "--screen"]
    tool = argv[0]
    args = _load_args(argv)
    return asyncio.run(run(tool, args, want_screen))


if __name__ == "__main__":
    sys.exit(main())