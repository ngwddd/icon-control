"""MCP server adapter - supports stdio and HTTP/SSE transport modes."""

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
server = Server("computer-mcp")



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
            if name in getattr(__import__("computer_mcp.permission", fromlist=["x"]), "INPUT_TOOLS", ()):
                return format_response(
                    {"success": False, "blocked": True,
                     "error": f"权限闸门异常，按未授权处理：{_gate_exc}", "tool": name},
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
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


async def run_http(host: str = "127.0.0.1", port: int = 8000):
    """Run MCP server in HTTP/SSE mode.
    
    Implements HTTP/SSE transport for MCP server using aiohttp or similar.
    Note: The MCP Python SDK doesn't natively support HTTP/SSE transport,
    so we implement a custom HTTP server that handles MCP protocol over SSE.
    
    Args:
        host: Host to bind to
        port: Port to bind to
    """
    try:
        from aiohttp import web, web_response
        import json as json_lib
    except ImportError:
        raise ImportError(
            "aiohttp is required for HTTP/SSE mode. Install with: pip install aiohttp"
        )
    
    async def handle_sse(request):
        """Handle Server-Sent Events connection."""
        response = web_response.StreamResponse()
        response.headers['Content-Type'] = 'text/event-stream'
        response.headers['Cache-Control'] = 'no-cache'
        response.headers['Connection'] = 'keep-alive'
        await response.prepare(request)
        
        # Read from request and write to response
        # This is a simplified implementation - full MCP over SSE would need
        # proper message framing according to MCP spec
        try:
            async for line in request.content:
                # Process MCP messages (simplified - actual implementation would parse JSON-RPC)
                await response.write(f"data: {line.decode()}\n\n".encode())
        except Exception as e:
            await response.write(f"event: error\ndata: {json_lib.dumps({'error': str(e)})}\n\n".encode())
        finally:
            await response.write_eof()
        
        return response
    
    async def handle_mcp_message(request):
        """Handle MCP tool call via HTTP POST."""
        try:
            data = await request.json()
            tool_name = data.get("name")
            arguments = data.get("arguments", {})
            
            # Call the tool handler
            result = await call_tool(tool_name, arguments)
            
            # Convert MCP response format to JSON
            response_data = []
            for content in result:
                if hasattr(content, 'text'):
                    response_data.append({"type": "text", "text": content.text})
                elif hasattr(content, 'data'):
                    response_data.append({
                        "type": "image",
                        "data": content.data,
                        "mimeType": getattr(content, 'mimeType', 'image/png')
                    })
            
            return web.json_response({"content": response_data})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)
    
    app = web.Application()
    app.router.add_get('/sse', handle_sse)
    app.router.add_post('/mcp', handle_mcp_message)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    
    print(f"MCP server running in HTTP/SSE mode on http://{host}:{port}")
    print(f"SSE endpoint: http://{host}:{port}/sse")
    print(f"MCP endpoint: http://{host}:{port}/mcp")
    
    # Keep running
    try:
        await asyncio.Future()  # Run forever
    except KeyboardInterrupt:
        pass
    finally:
        await runner.cleanup()

