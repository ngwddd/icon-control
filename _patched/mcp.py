"""MCP server adapter - supports stdio and HTTP/SSE transport modes."""

import asyncio
import json
from typing import Any, Union

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import ImageContent, TextContent, Tool
from pynput.keyboard import Controller as KeyboardController
from pynput.mouse import Controller as MouseController

from computer_mcp.actions import (
    keyboard as keyboard_actions,
    mouse as mouse_actions,
    screenshot as screenshot_actions,
    window as window_actions,
    config as config_actions,
)
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
    """List available tools."""
    return [
        Tool(
            name="click",
            description="Perform a mouse click at the current cursor position",
            inputSchema={
                "type": "object",
                "properties": {
                    "button": {
                        "type": "string",
                        "enum": ["left", "middle", "right"],
                        "description": "Mouse button to click",
                        "default": "left"
                    }
                }
            }
        ),
        Tool(
            name="double_click",
            description="Perform a double mouse click at the current cursor position",
            inputSchema={
                "type": "object",
                "properties": {
                    "button": {
                        "type": "string",
                        "enum": ["left", "middle", "right"],
                        "description": "Mouse button to click",
                        "default": "left"
                    }
                }
            }
        ),
        Tool(
            name="triple_click",
            description="Perform a triple mouse click at the current cursor position",
            inputSchema={
                "type": "object",
                "properties": {
                    "button": {
                        "type": "string",
                        "enum": ["left", "middle", "right"],
                        "description": "Mouse button to click",
                        "default": "left"
                    }
                }
            }
        ),
        Tool(
            name="button_down",
            description="Press and hold a mouse button",
            inputSchema={
                "type": "object",
                "properties": {
                    "button": {
                        "type": "string",
                        "enum": ["left", "middle", "right"],
                        "description": "Mouse button to press",
                        "default": "left"
                    }
                }
            }
        ),
        Tool(
            name="button_up",
            description="Release a mouse button",
            inputSchema={
                "type": "object",
                "properties": {
                    "button": {
                        "type": "string",
                        "enum": ["left", "middle", "right"],
                        "description": "Mouse button to release",
                        "default": "left"
                    }
                }
            }
        ),
        Tool(
            name="drag",
            description="Drag mouse from start to end position",
            inputSchema={
                "type": "object",
                "properties": {
                    "start": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "integer"},
                            "y": {"type": "integer"}
                        },
                        "required": ["x", "y"],
                        "description": "Start position"
                    },
                    "end": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "integer"},
                            "y": {"type": "integer"}
                        },
                        "required": ["x", "y"],
                        "description": "End position"
                    },
                    "button": {
                        "type": "string",
                        "enum": ["left", "middle", "right"],
                        "description": "Mouse button to use for drag",
                        "default": "left"
                    }
                },
                "required": ["start", "end"]
            }
        ),
        Tool(
            name="mouse_move",
            description="Move the mouse cursor to the specified coordinates",
            inputSchema={
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "X coordinate"},
                    "y": {"type": "integer", "description": "Y coordinate"}
                },
                "required": ["x", "y"]
            }
        ),
        Tool(
            name="type",
            description="Type the specified text",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to type"}
                },
                "required": ["text"]
            }
        ),
        Tool(
            name="key_down",
            description="Press and hold a key",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Key to press (e.g., 'ctrl', 'a', 'space')"}
                },
                "required": ["key"]
            }
        ),
        Tool(
            name="key_up",
            description="Release a key",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Key to release (e.g., 'ctrl', 'a', 'space')"}
                },
                "required": ["key"]
            }
        ),
        Tool(
            name="key_press",
            description="Press and release a key (convenience method)",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Key to press and release (e.g., 'ctrl', 'a', 'space')"}
                },
                "required": ["key"]
            }
        ),
        Tool(
            name="screenshot",
            description="Capture a screenshot of the display and return it as base64-encoded PNG",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="set_config",
            description="Configure observation options",
            inputSchema={
                "type": "object",
                "properties": {
                    "observe_screen": {
                        "type": "boolean",
                        "description": "Include screenshots in responses (default: true)",
                        "default": True
                    },
                    "observe_mouse_position": {
                        "type": "boolean",
                        "description": "Track and include mouse position",
                        "default": False
                    },
                    "observe_mouse_button_states": {
                        "type": "boolean",
                        "description": "Track and include mouse button states",
                        "default": False
                    },
                    "observe_keyboard_key_states": {
                        "type": "boolean",
                        "description": "Track and include keyboard key states",
                        "default": False
                    },
                    "observe_focused_app": {
                        "type": "boolean",
                        "description": "Include focused application information",
                        "default": False
                    },
                    "observe_accessibility_tree": {
                        "type": "boolean",
                        "description": "Include accessibility tree",
                        "default": False
                    },
                    "disallowed_hotkeys": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        },
                        "description": "List of hotkey strings to disallow (e.g., ['ctrl+c', 'alt+f4'])",
                        "default": []
                    },
                    "constrain_mouse_to_window": {
                        "oneOf": [
                            {"type": "null"},
                            {"type": "integer"},
                            {"type": "string"}
                        ],
                        "description": "Constrain mouse movement and clicks to window bounds. Set to window handle (int), window title pattern (str), or null to disable.",
                        "default": None
                    },
                    "observe_system_metrics": {
                        "type": "boolean",
                        "description": "Track and include system performance metrics (CPU, memory, disk I/O, network I/O)",
                        "default": False
                    }
                }
            }
        ),
        Tool(
            name="list_windows",
            description="List all visible windows with their handles, titles, processes, and bounds",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="switch_to_window",
            description="Switch focus to a window by handle or title pattern",
            inputSchema={
                "type": "object",
                "properties": {
                    "hwnd": {
                        "type": "integer",
                        "description": "Window handle (from list_windows)"
                    },
                    "title": {
                        "type": "string",
                        "description": "Window title pattern to search for (alternative to hwnd)"
                    }
                },
                "oneOf": [
                    {"required": ["hwnd"]},
                    {"required": ["title"]}
                ]
            }
        ),
        Tool(
            name="move_window",
            description="Move and/or resize a window to specified position and size",
            inputSchema={
                "type": "object",
                "properties": {
                    "hwnd": {
                        "type": "integer",
                        "description": "Window handle"
                    },
                    "x": {
                        "type": "integer",
                        "description": "X coordinate for window position"
                    },
                    "y": {
                        "type": "integer",
                        "description": "Y coordinate for window position"
                    },
                    "width": {
                        "type": "integer",
                        "description": "Window width (optional, preserves current if not specified)"
                    },
                    "height": {
                        "type": "integer",
                        "description": "Window height (optional, preserves current if not specified)"
                    }
                },
                "required": ["hwnd", "x", "y"]
            }
        ),
        Tool(
            name="resize_window",
            description="Resize a window to specified dimensions",
            inputSchema={
                "type": "object",
                "properties": {
                    "hwnd": {
                        "type": "integer",
                        "description": "Window handle"
                    },
                    "width": {
                        "type": "integer",
                        "description": "Window width"
                    },
                    "height": {
                        "type": "integer",
                        "description": "Window height"
                    }
                },
                "required": ["hwnd", "width", "height"]
            }
        ),
        Tool(
            name="minimize_window",
            description="Minimize a window",
            inputSchema={
                "type": "object",
                "properties": {
                    "hwnd": {
                        "type": "integer",
                        "description": "Window handle"
                    }
                },
                "required": ["hwnd"]
            }
        ),
        Tool(
            name="maximize_window",
            description="Maximize a window",
            inputSchema={
                "type": "object",
                "properties": {
                    "hwnd": {
                        "type": "integer",
                        "description": "Window handle"
                    }
                },
                "required": ["hwnd"]
            }
        ),
        Tool(
            name="restore_window",
            description="Restore a minimized or maximized window to normal state",
            inputSchema={
                "type": "object",
                "properties": {
                    "hwnd": {
                        "type": "integer",
                        "description": "Window handle"
                    }
                },
                "required": ["hwnd"]
            }
        ),
        Tool(
            name="set_window_topmost",
            description="Set or remove a window's always-on-top property",
            inputSchema={
                "type": "object",
                "properties": {
                    "hwnd": {
                        "type": "integer",
                        "description": "Window handle"
                    },
                    "topmost": {
                        "type": "boolean",
                        "description": "Whether window should be always on top",
                        "default": True
                    }
                },
                "required": ["hwnd"]
            }
        ),
        Tool(
            name="get_window_info",
            description="Get detailed information about a window",
            inputSchema={
                "type": "object",
                "properties": {
                    "hwnd": {
                        "type": "integer",
                        "description": "Window handle"
                    }
                },
                "required": ["hwnd"]
            }
        ),
        Tool(
            name="close_window",
            description="Close a window",
            inputSchema={
                "type": "object",
                "properties": {
                    "hwnd": {
                        "type": "integer",
                        "description": "Window handle"
                    }
                },
                "required": ["hwnd"]
            }
        ),
        Tool(
            name="snap_window_left",
            description="Snap window to fill left half of screen",
            inputSchema={
                "type": "object",
                "properties": {
                    "hwnd": {
                        "type": "integer",
                        "description": "Window handle"
                    }
                },
                "required": ["hwnd"]
            }
        ),
        Tool(
            name="snap_window_right",
            description="Snap window to fill right half of screen",
            inputSchema={
                "type": "object",
                "properties": {
                    "hwnd": {
                        "type": "integer",
                        "description": "Window handle"
                    }
                },
                "required": ["hwnd"]
            }
        ),
        Tool(
            name="snap_window_top",
            description="Snap window to fill top half of screen",
            inputSchema={
                "type": "object",
                "properties": {
                    "hwnd": {
                        "type": "integer",
                        "description": "Window handle"
                    }
                },
                "required": ["hwnd"]
            }
        ),
        Tool(
            name="snap_window_bottom",
            description="Snap window to fill bottom half of screen",
            inputSchema={
                "type": "object",
                "properties": {
                    "hwnd": {
                        "type": "integer",
                        "description": "Window handle"
                    }
                },
                "required": ["hwnd"]
            }
        ),
        Tool(
            name="screenshot_window",
            description="Capture screenshot of a specific window",
            inputSchema={
                "type": "object",
                "properties": {
                    "hwnd": {
                        "type": "integer",
                        "description": "Window handle"
                    }
                },
                "required": ["hwnd"]
            }
        ),
        Tool(
            name="list_virtual_desktops",
            description="List all virtual desktops with their IDs and names",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="switch_virtual_desktop",
            description="Switch to a virtual desktop by ID or name",
            inputSchema={
                "type": "object",
                "properties": {
                    "desktop_id": {
                        "type": "integer",
                        "description": "Virtual desktop ID (0-indexed)"
                    },
                    "name": {
                        "type": "string",
                        "description": "Virtual desktop name (alternative to desktop_id)"
                    }
                },
                "oneOf": [
                    {"required": ["desktop_id"]},
                    {"required": ["name"]}
                ]
            }
        ),
        Tool(
            name="move_window_to_virtual_desktop",
            description="Move a window to a different virtual desktop",
            inputSchema={
                "type": "object",
                "properties": {
                    "hwnd": {
                        "type": "integer",
                        "description": "Window handle"
                    },
                    "desktop_id": {
                        "type": "integer",
                        "description": "Target virtual desktop ID"
                    }
                },
                "required": ["hwnd", "desktop_id"]
            }
        ),
        # ---- DSH patch: cheap screen awareness without paying for a picture ----
        Tool(
            name="screen_state",
            description="Cheap screen check WITHOUT returning an image (~40 ms). Reports whether the screen changed since the last capture, by how much (mean abs diff %), and a short hash. Use this to poll instead of screenshot.",
            inputSchema={
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "Optional region left (default: full screen)"},
                    "y": {"type": "integer", "description": "Optional region top"},
                    "w": {"type": "integer", "description": "Optional region width"},
                    "h": {"type": "integer", "description": "Optional region height"}
                }
            }
        ),
        Tool(
            name="wait_for_change",
            description="Block until the screen changes above the threshold, or until timeout. Cheaper than the model polling screen_state in a loop.",
            inputSchema={
                "type": "object",
                "properties": {
                    "timeout_ms": {"type": "integer", "description": "Max time to wait (default 5000)", "default": 5000},
                    "poll_ms": {"type": "integer", "description": "Internal poll interval (default 120)", "default": 120}
                }
            }
        ),
        Tool(
            name="capture_config",
            description="Get or set capture settings: scale (default 0.5 -> 1280x720), quality (75), format (jpeg|png), diff_threshold (0.8 %), mask_bottom (60 px of taskbar ignored by change detection). Call with no args to just read them.",
            inputSchema={
                "type": "object",
                "properties": {
                    "scale": {"type": "number", "description": "Downscale factor, 1.0 = full resolution"},
                    "quality": {"type": "integer", "description": "JPEG quality 1-95"},
                    "format": {"type": "string", "enum": ["jpeg", "png"]},
                    "diff_threshold": {"type": "number", "description": "Mean abs diff % that counts as changed"},
                    "mask_bottom": {"type": "integer", "description": "Bottom pixel rows ignored by change detection"}
                }
            }
        ),
        # ---- DSH patch v0.2: staged verification ----
        Tool(
            name="verify_flow",
            description="Run staged verification and return per-stage evidence. Each stage may wait, then run assertions: kind=text|template|baseline|stable|file. Stages stop at the first failure (stop_on_fail) and the report can be written to a JSON file. Verification only - it performs no input actions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "stages": {
                        "type": "array",
                        "description": "Ordered stages: {name, wait_ms?, assert:[{kind, ...}]}",
                        "items": {"type": "object", "additionalProperties": True}
                    },
                    "stop_on_fail": {"type": "boolean", "default": True},
                    "report_path": {"type": "string", "description": "Optional JSON report path"}
                },
                "required": ["stages"]
            }
        ),
        # ---- DSH patch: vision state (template self-learning / baseline diff / stable sampling) ----
        Tool(
            name="capture_template",
            description="Save a screen region as a reusable template (grayscale PNG) under the tool's vision store. Use this for self-drawn UIs where UI Automation is blind: capture the button/icon once, then match_template finds it later. Give a tight region around the visual itself.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Template name"},
                    "x": {"type": "integer"}, "y": {"type": "integer"},
                    "w": {"type": "integer"}, "h": {"type": "integer"},
                    "hwnd": {"type": "integer", "description": "Optional: grab the window bitmap (works when covered)"},
                    "overwrite": {"type": "boolean", "default": True}
                },
                "required": ["name", "x", "y", "w", "h"]
            }
        ),
        Tool(
            name="match_template",
            description="Find a stored template on screen (grayscale template matching). Returns found/score and the ABSOLUTE screen x,y,w,h and center. No OCR, no UIA - works on games, Electron and CEF windows.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "confidence": {"type": "number", "default": 0.8},
                    "hwnd": {"type": "integer"},
                    "x": {"type": "integer"}, "y": {"type": "integer"},
                    "w": {"type": "integer"}, "h": {"type": "integer"}
                },
                "required": ["name"]
            }
        ),
        Tool(
            name="wait_template",
            description="Block until a template appears (appear=true) or disappears (appear=false), or until timeout. Event driven and cheaper than polling match_template from the model.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "timeout_ms": {"type": "integer", "default": 5000},
                    "poll_ms": {"type": "integer", "default": 120},
                    "appear": {"type": "boolean", "default": True},
                    "confidence": {"type": "number", "default": 0.8},
                    "hwnd": {"type": "integer"}
                },
                "required": ["name"]
            }
        ),
        Tool(
            name="click_template",
            description="Find a template and click its centre. No coordinate guessing. Optional offset [dx,dy] nudges the click point.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "confidence": {"type": "number", "default": 0.8},
                    "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
                    "offset": {"type": "array", "items": {"type": "integer"}},
                    "settle_ms": {"type": "integer", "default": 150},
                    "hwnd": {"type": "integer"}
                },
                "required": ["name"]
            }
        ),
        Tool(
            name="set_baseline",
            description="Remember what a screen region normally looks like. diff_baseline later reports how far the current pixels deviate - precise and cheap, and scoped to just that region.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "x": {"type": "integer"}, "y": {"type": "integer"},
                    "w": {"type": "integer"}, "h": {"type": "integer"},
                    "hwnd": {"type": "integer"}
                },
                "required": ["name", "x", "y", "w", "h"]
            }
        ),
        Tool(
            name="diff_baseline",
            description="Compare a region against its stored baseline. Returns diff (mean abs difference 0-255) and changed = diff >= threshold.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "threshold": {"type": "number", "default": 8.0},
                    "x": {"type": "integer"}, "y": {"type": "integer"},
                    "w": {"type": "integer"}, "h": {"type": "integer"},
                    "hwnd": {"type": "integer"}
                },
                "required": ["name"]
            }
        ),
        Tool(
            name="wait_baseline_change",
            description="Block until a region deviates from its baseline by more than threshold, or until timeout.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "threshold": {"type": "number", "default": 8.0},
                    "timeout_ms": {"type": "integer", "default": 5000},
                    "poll_ms": {"type": "integer", "default": 120},
                    "hwnd": {"type": "integer"}
                },
                "required": ["name"]
            }
        ),
        Tool(
            name="sample_stable",
            description="Sample a region several times and report whether it is stable (all hashes equal). Use it before trusting a state reading: this is how you avoid judging a UI while an animation is still running.",
            inputSchema={
                "type": "object",
                "properties": {
                    "times": {"type": "integer", "default": 2},
                    "gap_ms": {"type": "integer", "default": 200},
                    "x": {"type": "integer"}, "y": {"type": "integer"},
                    "w": {"type": "integer"}, "h": {"type": "integer"},
                    "hwnd": {"type": "integer"}
                }
            }
        ),
        Tool(
            name="hover_probe",
            description="Hover a point, wait, measure whether a region changed, then move the cursor away. This detects hover-revealed menus/buttons that never show up in a plain screenshot or a click.",
            inputSchema={
                "type": "object",
                "properties": {
                    "x": {"type": "integer"}, "y": {"type": "integer"},
                    "dwell_ms": {"type": "integer", "default": 400},
                    "threshold": {"type": "number", "default": 3.0},
                    "away_x": {"type": "integer"}, "away_y": {"type": "integer"},
                    "rx": {"type": "integer"}, "ry": {"type": "integer"},
                    "rw": {"type": "integer"}, "rh": {"type": "integer"},
                    "hwnd": {"type": "integer"}
                },
                "required": ["x", "y", "rx", "ry", "rw", "rh"]
            }
        ),
        Tool(
            name="vision_list",
            description="List stored templates and baselines (name, source region, size, creation time), plus live run statistics: calls, failures, retries, failure_rate. Use stats to spot a long automation that silently stopped working.",
            inputSchema={
                "type": "object",
                "properties": {
                    "reset_stats": {"type": "boolean", "default": False},
                    "delete": {"type": "string", "description": "Optional template name to delete"}
                }
            }
        ),
        # ---- DSH patch: batch gestures + UI Automation (fewer round trips, no pixel guessing) ----
        Tool(
            name="batch",
            description="Run a whole gesture sequence in ONE call. Each step: {action:'move'|'click'|'double_click'|'right_click'|'type'|'key'|'sleep'|'wait_change'|'screen_state'|'ui_click', ...}. Use this instead of many separate calls (each separate call costs a model round trip).",
            inputSchema={
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "description": "Ordered steps",
                        "items": {"type": "object", "additionalProperties": True}
                    },
                    "stop_on_error": {"type": "boolean", "default": True},
                    "default_sleep_ms": {"type": "integer", "default": 120}
                },
                "required": ["steps"]
            }
        ),
        Tool(
            name="ui_tree",
            description="Compact UI-Automation control tree for a window (or the focused one). Text only, no screenshot: control type + name + rect. Use it to find what is clickable before clicking.",
            inputSchema={
                "type": "object",
                "properties": {
                    "hwnd": {"type": "integer", "description": "Window handle (default: focused window)"},
                    "depth": {"type": "integer", "default": 3},
                    "max_nodes": {"type": "integer", "default": 60},
                    "only_named": {"type": "boolean", "default": True}
                }
            }
        ),
        Tool(
            name="ui_find",
            description="Find controls by accessible name (substring, or exact=true). Returns candidates with their centre coordinates. Cheaper and more reliable than reading a screenshot.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "hwnd": {"type": "integer"},
                    "depth": {"type": "integer", "default": 8},
                    "exact": {"type": "boolean", "default": False},
                    "index": {"type": "integer", "default": 0}
                },
                "required": ["name"]
            }
        ),
        Tool(
            name="ui_click",
            description="Move the real cursor to a control found by name and click it. No coordinate guessing.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "hwnd": {"type": "integer"},
                    "exact": {"type": "boolean", "default": False},
                    "index": {"type": "integer", "default": 0},
                    "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
                    "settle_ms": {"type": "integer", "default": 250}
                },
                "required": ["name"]
            }
        ),
        Tool(
            name="ui_invoke",
            description="Trigger a control by name through its Invoke pattern, without moving the cursor (fastest, non-intrusive). Falls back with a hint if the control has no Invoke.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "hwnd": {"type": "integer"},
                    "exact": {"type": "boolean", "default": False},
                    "index": {"type": "integer", "default": 0}
                },
                "required": ["name"]
            }
        ),
        Tool(
            name="ui_set_text",
            description="Set a text field's value through its Value pattern, without typing keystrokes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "text": {"type": "string"},
                    "hwnd": {"type": "integer"},
                    "exact": {"type": "boolean", "default": False},
                    "index": {"type": "integer", "default": 0}
                },
                "required": ["name", "text"]
            }
        ),
        # ---- DSH patch: named macros (one call replays a whole recorded gesture) ----
        Tool(
            name="macro_list",
            description="List saved macros (name, description, target window, step count).",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="macro_save",
            description="Save a macro. Steps use window-relative 'rel':[dx,dy] coordinates and can carry 'expect':{'changed':true,'timeout_ms':1200} to verify the step actually did something.",
            inputSchema={
                "type": "object",
                "properties": {
                    "spec": {
                        "type": "object",
                        "description": "{name, description?, window:{title_contains|process}, steps:[...]}",
                        "additionalProperties": True
                    }
                },
                "required": ["spec"]
            }
        ),
        Tool(
            name="macro_run",
            description="Replay a saved macro in ONE call. Coordinates are re-based onto the target window's current position. Use dry_run=true to see resolved absolute coordinates without clicking.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "params": {"type": "object", "description": "Values for ${placeholders}"},
                    "dry_run": {"type": "boolean", "default": False},
                    "default_gap_ms": {"type": "integer", "default": 140}
                },
                "required": ["name"]
            }
        ),
        # ---- DSH patch: 记忆库（学习过的元素坐标 + 视觉指纹）----
        Tool(
            name="anchor_mem",
            description="Learned anchor memory for UI elements: list / learn / verify / forget / stats. Stores normalised position + a 64-bit visual fingerprint + usage counters, so a click can be verified instead of guessed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "learn", "verify", "forget", "stats"]},
                    "app": {"type": "string"},
                    "key": {"type": "string"},
                    "hwnd": {"type": "integer"},
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "note": {"type": "string"}
                },
                "required": ["action"]
            }
        ),
        # ---- DSH patch: Windows built-in OCR (UI-Automation-blind apps) ----
        Tool(
            name="ocr_read",
            description="Read text off the screen with the Windows OCR engine and return the recognised lines with boxes. Text only - much cheaper than sending an image when all you need is what the UI says. Pass a region to scan just one window.",
            inputSchema={
                "type": "object",
                "properties": {
                    "x": {"type": "integer"}, "y": {"type": "integer"},
                    "w": {"type": "integer"}, "h": {"type": "integer"},
                    "max_lines": {"type": "integer", "default": 80},
                    "hwnd": {"type": "integer", "description": "Raise this window first, then OCR its rectangle"}
                }
            }
        ),
        Tool(
            name="find_text",
            description="OCR the screen (or a region) and find a string, tolerating OCR mistakes: whitespace between CJK glyphs is ignored and a single mis-read character still matches. Returns centre coordinates.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "x": {"type": "integer"}, "y": {"type": "integer"},
                    "w": {"type": "integer"}, "h": {"type": "integer"},
                    "min_ratio": {"type": "number", "default": 0.72},
                    "min_lcs_share": {"type": "number", "default": 0.6},
                    "max_lines": {"type": "integer", "default": 120},
                    "hwnd": {"type": "integer", "description": "Raise this window first, then OCR its rectangle"}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="click_text",
            description="Find a string with OCR and click it, in ONE call. The reliable way to click inside apps whose controls UIA cannot see (即时通讯软件（***）, Electron, custom-rendered UIs).",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "x": {"type": "integer"}, "y": {"type": "integer"},
                    "w": {"type": "integer"}, "h": {"type": "integer"},
                    "index": {"type": "integer", "default": 0},
                    "settle_ms": {"type": "integer", "default": 250},
                    "hwnd": {"type": "integer", "description": "Raise this window first, then OCR its rectangle"}
                },
                "required": ["query"]
            }
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[Union[TextContent, ImageContent]]:
    """Handle tool calls by routing to action functions."""
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

        
        # Mouse actions
        if name == "click":
            result = mouse_actions.click(
                button=arguments.get("button", "left"),
                controller=mouse_controller
            )
        elif name == "double_click":
            result = mouse_actions.double_click(
                button=arguments.get("button", "left"),
                controller=mouse_controller
            )
        elif name == "triple_click":
            result = mouse_actions.triple_click(
                button=arguments.get("button", "left"),
                controller=mouse_controller
            )
        elif name == "button_down":
            result = mouse_actions.button_down(
                button=arguments.get("button", "left"),
                controller=mouse_controller
            )
        elif name == "button_up":
            result = mouse_actions.button_up(
                button=arguments.get("button", "left"),
                controller=mouse_controller
            )
        elif name == "drag":
            result = mouse_actions.drag(
                start=arguments["start"],
                end=arguments["end"],
                button=arguments.get("button", "left"),
                controller=mouse_controller
            )
        elif name == "mouse_move":
            result = mouse_actions.move_mouse(
                x=arguments["x"],
                y=arguments["y"],
                controller=mouse_controller
            )
        
        # Keyboard actions
        elif name == "type":
            result = keyboard_actions.type_text(
                text=arguments["text"],
                controller=keyboard_controller
            )
        elif name == "key_down":
            result = keyboard_actions.key_down(
                key=arguments["key"],
                controller=keyboard_controller
            )
        elif name == "key_up":
            result = keyboard_actions.key_up(
                key=arguments["key"],
                controller=keyboard_controller
            )
        elif name == "key_press":
            result = keyboard_actions.key_press(
                key=arguments["key"],
                controller=keyboard_controller
            )
        
        # Screenshot actions
        elif name == "screenshot":
            screenshot_result = screenshot_actions.get_screenshot()
            if "error" not in screenshot_result:
                screenshot_data = screenshot_result
                result = {"success": True, "action": "screenshot"}
            else:
                result = screenshot_result
        
        # Config actions
        elif name == "set_config":
            # Update state config first
            for key in ["observe_screen", "observe_mouse_position", "observe_mouse_button_states", 
                       "observe_keyboard_key_states", "observe_focused_app", "observe_accessibility_tree", 
                       "disallowed_hotkeys", "constrain_mouse_to_window", "observe_system_metrics"]:
                if key in arguments:
                    computer_state.config[key] = arguments[key]
            result = {"success": True, "action": "set_config", "config": computer_state.config.copy()}
        
        # Window actions
        elif name == "list_windows":
            result = window_actions.list_windows()
        elif name == "switch_to_window":
            result = window_actions.switch_to_window(
                hwnd=arguments.get("hwnd"),
                title=arguments.get("title")
            )
        elif name == "move_window":
            result = window_actions.move_window(
                hwnd=arguments["hwnd"],
                x=arguments["x"],
                y=arguments["y"],
                width=arguments.get("width"),
                height=arguments.get("height")
            )
        elif name == "resize_window":
            result = window_actions.resize_window(
                hwnd=arguments["hwnd"],
                width=arguments["width"],
                height=arguments["height"]
            )
        elif name == "minimize_window":
            result = window_actions.minimize_window(hwnd=arguments["hwnd"])
        elif name == "maximize_window":
            result = window_actions.maximize_window(hwnd=arguments["hwnd"])
        elif name == "restore_window":
            result = window_actions.restore_window(hwnd=arguments["hwnd"])
        elif name == "set_window_topmost":
            result = window_actions.set_window_topmost(
                hwnd=arguments["hwnd"],
                topmost=arguments.get("topmost", True)
            )
        elif name == "get_window_info":
            result = window_actions.get_window_info(hwnd=arguments["hwnd"])
        elif name == "close_window":
            result = window_actions.close_window(hwnd=arguments["hwnd"])
        elif name == "snap_window_left":
            result = window_actions.snap_window_left(hwnd=arguments["hwnd"])
        elif name == "snap_window_right":
            result = window_actions.snap_window_right(hwnd=arguments["hwnd"])
        elif name == "snap_window_top":
            result = window_actions.snap_window_top(hwnd=arguments["hwnd"])
        elif name == "snap_window_bottom":
            result = window_actions.snap_window_bottom(hwnd=arguments["hwnd"])
        elif name == "screenshot_window":
            screenshot_result = window_actions.screenshot_window(hwnd=arguments["hwnd"])
            if "error" not in screenshot_result:
                screenshot_data = {
                    "format": screenshot_result.get("format", "base64_png"),
                    "data": screenshot_result.get("data"),
                    "width": screenshot_result.get("width"),
                    "height": screenshot_result.get("height")
                }
                result = {"success": screenshot_result.get("success"), "action": "screenshot_window", "hwnd": arguments["hwnd"]}
            else:
                result = screenshot_result
        
        # Virtual desktop actions
        elif name == "list_virtual_desktops":
            result = window_actions.list_virtual_desktops()
        elif name == "switch_virtual_desktop":
            result = window_actions.switch_virtual_desktop(
                desktop_id=arguments.get("desktop_id"),
                name=arguments.get("name")
            )
        elif name == "move_window_to_virtual_desktop":
            result = window_actions.move_window_to_virtual_desktop(
                hwnd=arguments["hwnd"],
                desktop_id=arguments["desktop_id"]
            )

        # ---- DSH patch: cheap screen awareness (never attaches a screenshot) ----
        elif name == "screen_state":
            region = None
            if all(k in arguments for k in ("x", "y", "w", "h")):
                region = {k: arguments[k] for k in ("x", "y", "w", "h")}
            result = capture_core.screen_state(region=region)
            screenshot_data = {"error": "intentionally skipped"}
        elif name == "wait_for_change":
            result = capture_core.wait_for_change(
                timeout_ms=int(arguments.get("timeout_ms", 5000)),
                poll_ms=int(arguments.get("poll_ms", 120)),
            )
            screenshot_data = {"error": "intentionally skipped"}
        elif name == "capture_config":
            updates = {k: arguments[k] for k in ("scale", "quality", "format", "diff_threshold", "mask_bottom")
                       if k in arguments}
            if updates:
                cfg = capture_core.set_capture_config(**updates)
                result = {"success": True, "action": "capture_config", "config": cfg, "updated": list(updates)}
            else:
                result = {"success": True, "action": "capture_config", "config": capture_core.get_capture_config()}
            screenshot_data = {"error": "intentionally skipped"}

        # ---- DSH patch v0.2: staged verification ----
        elif name == "verify_flow":
            from computer_mcp import verify_flow as _vf
            result = _vf.run(
                stages=arguments.get("stages") or [],
                stop_on_fail=bool(arguments.get("stop_on_fail", True)),
                report_path=arguments.get("report_path"),
            )
            result["success"] = bool(result.get("ok"))
            screenshot_data = {"error": "intentionally skipped"}
        # ---- DSH patch: vision state (template self-learning / baseline diff / stable sampling) ----
        elif name == "capture_template":
            from computer_mcp import vision_state as _vs
            result = _vs.capture_template(
                name=str(arguments["name"]),
                region={k: arguments[k] for k in ("x", "y", "w", "h")},
                hwnd=arguments.get("hwnd"),
                overwrite=bool(arguments.get("overwrite", True)),
            )
            screenshot_data = {"error": "intentionally skipped"}
        elif name == "match_template":
            from computer_mcp import vision_state as _vs
            reg = {k: arguments[k] for k in ("x", "y", "w", "h")} if all(
                k in arguments for k in ("x", "y", "w", "h")) else None
            result = _vs.match_template(
                name=str(arguments["name"]), region=reg, hwnd=arguments.get("hwnd"),
                confidence=float(arguments.get("confidence", 0.8)),
            )
            screenshot_data = {"error": "intentionally skipped"}
        elif name == "wait_template":
            from computer_mcp import vision_state as _vs
            result = _vs.wait_template(
                name=str(arguments["name"]),
                timeout_ms=int(arguments.get("timeout_ms", 5000)),
                poll_ms=int(arguments.get("poll_ms", 120)),
                appear=bool(arguments.get("appear", True)),
                confidence=float(arguments.get("confidence", 0.8)),
                hwnd=arguments.get("hwnd"),
            )
            screenshot_data = {"error": "intentionally skipped"}
        elif name == "click_template":
            from computer_mcp import vision_state as _vs
            result = _vs.click_template(
                name=str(arguments["name"]), mouse=mouse_controller,
                button=str(arguments.get("button", "left")),
                confidence=float(arguments.get("confidence", 0.8)),
                hwnd=arguments.get("hwnd"),
                settle_ms=int(arguments.get("settle_ms", 150)),
                offset=arguments.get("offset"),
            )
            screenshot_data = {"error": "intentionally skipped"}
        elif name == "set_baseline":
            from computer_mcp import vision_state as _vs
            result = _vs.set_baseline(
                name=str(arguments["name"]),
                region={k: arguments[k] for k in ("x", "y", "w", "h")},
                hwnd=arguments.get("hwnd"),
            )
            screenshot_data = {"error": "intentionally skipped"}
        elif name == "diff_baseline":
            from computer_mcp import vision_state as _vs
            reg = {k: arguments[k] for k in ("x", "y", "w", "h")} if all(
                k in arguments for k in ("x", "y", "w", "h")) else None
            result = _vs.diff_baseline(
                name=str(arguments["name"]), region=reg, hwnd=arguments.get("hwnd"),
                threshold=float(arguments.get("threshold", 8.0)),
            )
            screenshot_data = {"error": "intentionally skipped"}
        elif name == "wait_baseline_change":
            from computer_mcp import vision_state as _vs
            result = _vs.wait_baseline_change(
                name=str(arguments["name"]),
                threshold=float(arguments.get("threshold", 8.0)),
                timeout_ms=int(arguments.get("timeout_ms", 5000)),
                poll_ms=int(arguments.get("poll_ms", 120)),
                hwnd=arguments.get("hwnd"),
            )
            screenshot_data = {"error": "intentionally skipped"}
        elif name == "sample_stable":
            from computer_mcp import vision_state as _vs
            reg = {k: arguments[k] for k in ("x", "y", "w", "h")} if all(
                k in arguments for k in ("x", "y", "w", "h")) else None
            result = _vs.sample_stable(
                region=reg, hwnd=arguments.get("hwnd"),
                times=int(arguments.get("times", 2)), gap_ms=int(arguments.get("gap_ms", 200)),
            )
            screenshot_data = {"error": "intentionally skipped"}
        elif name == "hover_probe":
            from computer_mcp import vision_state as _vs
            away = None
            if "away_x" in arguments and "away_y" in arguments:
                away = (int(arguments["away_x"]), int(arguments["away_y"]))
            result = _vs.hover_probe(
                x=int(arguments["x"]), y=int(arguments["y"]),
                region={k: arguments[k] for k in ("rx", "ry", "rw", "rh")},
                hwnd=arguments.get("hwnd"),
                dwell_ms=int(arguments.get("dwell_ms", 400)),
                threshold=float(arguments.get("threshold", 3.0)),
                away=away, mouse=mouse_controller,
            )
            screenshot_data = {"error": "intentionally skipped"}
        elif name == "vision_list":
            from computer_mcp import vision_state as _vs
            out = _vs.list_templates()
            if arguments.get("delete"):
                out["deleted"] = _vs.delete_template(str(arguments["delete"]))
            out["stats"] = _vs.stats(reset=bool(arguments.get("reset_stats", False)))
            result = out
            screenshot_data = {"error": "intentionally skipped"}

        # ---- DSH patch: batch gestures + UI Automation (no screenshots attached) ----
        elif name == "batch":
            result = ui_ext.run_batch(
                steps=arguments.get("steps") or [],
                mouse=mouse_controller,
                keyboard=keyboard_controller,
                stop_on_error=bool(arguments.get("stop_on_error", True)),
                default_sleep_ms=int(arguments.get("default_sleep_ms", 120)),
            )
            screenshot_data = {"error": "intentionally skipped"}
        elif name == "ui_tree":
            result = ui_ext.ui_tree(
                hwnd=arguments.get("hwnd"),
                depth=int(arguments.get("depth", 3)),
                max_nodes=int(arguments.get("max_nodes", 60)),
                only_named=bool(arguments.get("only_named", True)),
            )
            screenshot_data = {"error": "intentionally skipped"}
        elif name == "ui_find":
            result = ui_ext.ui_find(
                name=str(arguments["name"]),
                hwnd=arguments.get("hwnd"),
                depth=int(arguments.get("depth", 8)),
                exact=bool(arguments.get("exact", False)),
                index=int(arguments.get("index", 0)),
            )
            screenshot_data = {"error": "intentionally skipped"}
        elif name == "ui_click":
            result = ui_ext.ui_click(
                name=str(arguments["name"]),
                hwnd=arguments.get("hwnd"),
                exact=bool(arguments.get("exact", False)),
                index=int(arguments.get("index", 0)),
                button=str(arguments.get("button", "left")),
                mouse=mouse_controller,
                settle_ms=int(arguments.get("settle_ms", 250)),
            )
            screenshot_data = {"error": "intentionally skipped"}
        elif name == "ui_invoke":
            result = ui_ext.ui_invoke(
                name=str(arguments["name"]),
                hwnd=arguments.get("hwnd"),
                exact=bool(arguments.get("exact", False)),
                index=int(arguments.get("index", 0)),
            )
            screenshot_data = {"error": "intentionally skipped"}
        elif name == "ui_set_text":
            result = ui_ext.ui_set_text(
                name=str(arguments["name"]),
                text=str(arguments["text"]),
                hwnd=arguments.get("hwnd"),
                exact=bool(arguments.get("exact", False)),
                index=int(arguments.get("index", 0)),
            )
            screenshot_data = {"error": "intentionally skipped"}

        # ---- DSH patch: named macros ----
        elif name == "macro_list":
            result = macro_ext.macro_list()
            screenshot_data = {"error": "intentionally skipped"}
        elif name == "macro_save":
            result = macro_ext.macro_save(spec=arguments.get("spec") or {})
            screenshot_data = {"error": "intentionally skipped"}
        elif name == "macro_run":
            result = macro_ext.run_macro(
                name=str(arguments["name"]),
                params=arguments.get("params") or {},
                mouse=mouse_controller,
                keyboard=keyboard_controller,
                dry_run=bool(arguments.get("dry_run", False)),
                default_gap_ms=int(arguments.get("default_gap_ms", 140)),
            )
            screenshot_data = {"error": "intentionally skipped"}

        # ---- DSH patch: 记忆库 ----
        elif name == "anchor_mem":
            act = str(arguments.get("action", "list"))
            app_id = str(arguments.get("app", ""))
            key_id = str(arguments.get("key", ""))
            if act == "list":
                result = anchor_mem.list_all()
            elif act == "stats":
                result = anchor_mem.stats(app_id or None)
            elif act == "forget":
                result = anchor_mem.forget(app_id, key_id or None)
            elif act == "verify":
                hwnd_arg = arguments.get("hwnd") or 0
                result = anchor_mem.verify(app_id, key_id, hwnd_arg)
            elif act == "learn":
                result = anchor_mem.learn(app_id, key_id,
                                          int(arguments.get("hwnd") or 0),
                                          int(arguments.get("x") or 0),
                                          int(arguments.get("y") or 0),
                                          note=str(arguments.get("note", "")))
            else:
                result = {"error": f"unknown action {act!r}"}
            screenshot_data = {"error": "intentionally skipped"}

        # ---- DSH patch: OCR ----
        elif name in ("ocr_read", "find_text", "click_text"):
            region = None
            if all(k in arguments for k in ("x", "y", "w", "h")):
                region = {k: arguments[k] for k in ("x", "y", "w", "h")}
            if name == "ocr_read":
                result = ocr_ext.ocr_read(region=region,
                                          max_lines=int(arguments.get("max_lines", 80)),
                                          hwnd=arguments.get("hwnd"))
            elif name == "find_text":
                result = ocr_ext.find_text(
                    query=str(arguments["query"]),
                    region=region,
                    min_ratio=float(arguments.get("min_ratio", 0.72)),
                    min_lcs_share=float(arguments.get("min_lcs_share", 0.6)),
                    max_lines=int(arguments.get("max_lines", 120)),
                    hwnd=arguments.get("hwnd"),
                )
            else:
                result = ocr_ext.click_text(
                    query=str(arguments["query"]),
                    region=region,
                    index=int(arguments.get("index", 0)),
                    mouse=mouse_controller,
                    settle_ms=int(arguments.get("settle_ms", 250)),
                    hwnd=arguments.get("hwnd"),
                )
            screenshot_data = {"error": "intentionally skipped"}

        else:
            result = {"error": f"Unknown tool: {name}"}
        
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

