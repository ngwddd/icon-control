"""MCP adapter for stdio and authenticated Streamable HTTP."""

import asyncio
import json
from typing import Any, Union

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import ImageContent, TextContent, Tool
from computer_mcp.input_guard import KeyboardController, MouseController

from computer_mcp.actions import (
    keyboard as keyboard_actions,
    mouse as mouse_actions,
    screenshot as screenshot_actions,
    window as window_actions,
    config as config_actions,
)
from computer_mcp import tool_registry
from computer_mcp import dataset
from computer_mcp.zones.dispatch import dispatch as _dispatch
from computer_mcp.core.response import format_response
from computer_mcp.core.state import ComputerState
# DSH patch: cheap capture / change-detection helpers (see core/screenshot.py)
from computer_mcp.core import screenshot as capture_core
# DSH patch: batch gestures + UI-Automation based clicking (see ui_ext.py)
from computer_mcp import ui_ext
# DSH patch: named macros with window-relative coordinates (see macro_ext.py)
from computer_mcp import macro_ext
# DSH patch: Windows built-in OCR, for UI-Automation-blind apps (see ocr_ext.py)
from computer_mcp import ocr_ext
from computer_mcp import anchor_mem


# Global state instance
computer_state = ComputerState()
mouse_controller = MouseController()
keyboard_controller = KeyboardController()

# Initialize MCP server
from computer_mcp import __version__
server = Server("computer-mcp", version=__version__)



@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools (registry-backed, R2)."""
    return tool_registry.all_tools()


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[Union[TextContent, ImageContent]]:
    """Handle tool calls (R5: wrapped by dataset tee)."""
    return await dataset.tee(
        name,
        arguments,
        lambda: _call_tool_impl(name, arguments),
        lambda n: tool_registry.zone_of(n),
    )


async def _call_tool_impl(name: str, arguments: dict[str, Any]) -> list[Union[TextContent, ImageContent]]:
    """真正的路由实现（被 call_tool 的 tee 包住）。"""
    try:
        # Update listeners based on config
        if computer_state.config["observe_mouse_position"] or computer_state.config["observe_mouse_button_states"]:
            computer_state.start_mouse_listener()
        else:
            computer_state.stop_mouse_listener()
        
        if computer_state.config["observe_keyboard_key_states"]:
            computer_state.start_keyboard_listener()
        else:
            computer_state.stop_keyboard_listener()
        
        # Route to appropriate action function
        result: dict[str, Any] | None = None
        screenshot_data: dict[str, Any] | None = None
        # ---- DSH patch v0.2: mouse permission HARD GATE ----
        # 输入类工具在执行前统一过闸门；未授权时直接返回结构化拒绝，不产生任何鼠标/键盘动作。
        try:
            from computer_mcp import permission as _perm_gate
            _gate_denial = _perm_gate.check_tool(name, arguments)
            if _gate_denial is not None:
                return format_response(_gate_denial, computer_state,
                                       screenshot_data={"error": "blocked by permission gate"})
        except Exception as _gate_exc:      # 闸门自身出错时 fail closed
            return format_response(
                {"success": False, "blocked": True,
                 "error": f"权限闸门异常，按未授权处理：{type(_gate_exc).__name__}", "tool": name},
                computer_state, screenshot_data={"error": "blocked by permission gate"})

        
        _out = _dispatch(name, arguments, computer_state=computer_state,
                         mouse_controller=mouse_controller,
                         keyboard_controller=keyboard_controller)
        result = _out["result"]
        screenshot_data = _out["screenshot_data"]
        # Format response using MCP format_response helper
        if result is None:
            result = {"error": "Action returned None"}
        
        return format_response(result, computer_state, screenshot_data=screenshot_data)
    
    except Exception as e:
        error_msg = {"error": str(e), "tool": name, "arguments": arguments}
        return [TextContent(type="text", text=json.dumps(error_msg))]


async def run_stdio():
    """Run MCP server in stdio mode."""
    from computer_mcp import permission
    permission._ensure_bridge()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


async def run_http(host: str = "127.0.0.1", port: int = 8000):
    """Authenticated MCP Streamable HTTP. Legacy fake SSE endpoint is removed."""
    from computer_mcp.transport import run_http as sdk_http
    await sdk_http(server, host, port)

