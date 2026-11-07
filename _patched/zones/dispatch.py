"""zones/dispatch.py — 工具分发表（R4 从 mcp.py 搬出）

一行不改地把原来的 if/elif 链搬进来，只做成一个函数：
    dispatch(name, arguments, *, computer_state, mouse_controller, keyboard_controller)
        → {"result": dict | None, "screenshot_data": dict | None}

为什么不做成「每区一个 dict[name] = callable」：那需要拆开 80 个分支、逐个改造
闭包与默认参数，风险高收益低。先保证**行为零变化**，命名与分区细化放 R8。

依赖（全部来自 computer_mcp 内部与标准库）：
    actions.*  core.*  ui_ext  macro_ext  ocr_ext  anchor_mem  live/verify_flow/vision_state（分支内懒导入）
"""

from __future__ import annotations

import json
from typing import Any

from computer_mcp.actions import (
    keyboard as keyboard_actions,
    mouse as mouse_actions,
    screenshot as screenshot_actions,
    window as window_actions,
    focused_app as focused_app_actions,
    accessibility_tree as accessibility_tree_actions,
    config as config_actions,
)
from computer_mcp.core import screenshot as capture_core
from computer_mcp.core.state import ComputerState
from computer_mcp import ui_ext
from computer_mcp import macro_ext
from computer_mcp import ocr_ext
from computer_mcp import anchor_mem


def dispatch(name: str, arguments: dict, *, computer_state, mouse_controller,
             keyboard_controller) -> dict:
    from computer_mcp.execution import operation
    from computer_mcp.input_guard import MouseController, KeyboardController
    with operation(name, arguments):
        return _dispatch_impl(name, arguments, computer_state=computer_state,
            mouse_controller=mouse_controller if isinstance(mouse_controller, MouseController) else MouseController(mouse_controller),
            keyboard_controller=keyboard_controller if isinstance(keyboard_controller, KeyboardController) else KeyboardController(keyboard_controller))

def _dispatch_impl(name: str, arguments: dict, *, computer_state, mouse_controller,
             keyboard_controller) -> dict:
    """执行非闸门部分的分发；返回 {result, screenshot_data}。"""
    from computer_mcp.zones import aliases as _aliases
    name = _aliases.resolve(name)      # 新名→旧名（实现仍是旧名）
    from computer_mcp import control as _ctl
    from computer_mcp.permission import INPUT_TOOLS as _INPUTS
    _is_input = name in _INPUTS
    if _is_input:
        _ctl.quiet()          # 注入前开静默窗：自己的事件不算用户接管
    result: dict[str, Any] | None = None
    screenshot_data: dict[str, Any] | None = None

    # Mouse actions
    if name == "click":
        result = mouse_actions.click(
            button=arguments.get("button", "left"),
            controller=mouse_controller,
            x=arguments.get("x"), y=arguments.get("y"),
            frame_id=arguments.get("frame_id")
        )
    elif name == "double_click":
        result = mouse_actions.double_click(
            button=arguments.get("button", "left"),
            controller=mouse_controller,
            x=arguments.get("x"), y=arguments.get("y"),
            frame_id=arguments.get("frame_id")
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
            controller=mouse_controller,
            frame_id=arguments.get("frame_id")
        )
    elif name == "scroll":
        result = mouse_actions.scroll(dy=arguments['dy'], dx=arguments.get('dx', 0),
                                      x=arguments.get('x'), y=arguments.get('y'), controller=mouse_controller)
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
        result["backend"] = capture_core.backend()          # P1-6：报告实际截图后端
        screenshot_data = {"error": "intentionally skipped"}

    # ---- v0.4: live perception / closed loop ----
    elif name == "capture_daemon":
        from computer_mcp import live as _live
        result = _live.tool_capture(arguments or {})
        result.setdefault("success", result.get("ok") is True and not result.get("error"))
        screenshot_data = {"error": "intentionally skipped"}
    elif name == "sense":
        from computer_mcp import live as _live
        result = _live.tool_sense(arguments or {})
        result.setdefault("success", result.get("ok") is True and not result.get("error"))
        screenshot_data = {"error": "intentionally skipped"}
    elif name == "watch":
        from computer_mcp import live as _live
        result = _live.tool_watch(arguments or {})
        result.setdefault("success", result.get("ok") is True and not result.get("error"))
        screenshot_data = {"error": "intentionally skipped"}
    elif name == "probe":
        from computer_mcp import live as _live
        result = _live.tool_probe(arguments or {})
        result.setdefault("success", result.get("ok") is True and not result.get("error"))
        screenshot_data = {"error": "intentionally skipped"}
    elif name == "snapshot":
        from computer_mcp import live as _live
        result = _live.tool_snapshot(arguments or {})
        result.setdefault("success", result.get("ok") is True and not result.get("error"))
        screenshot_data = {"error": "intentionally skipped"}
    elif name == "run_script":
        from computer_mcp import live as _live
        result = _live.tool_run_script(arguments or {})
        result.setdefault("success", result.get("ok") is True and not result.get("error"))
        screenshot_data = {"error": "intentionally skipped"}
    elif name == "act_until":
        from computer_mcp import live as _live
        result = _live.tool_act_until(arguments or {})
        result.setdefault("success", result.get("ok") is True and not result.get("error"))
        screenshot_data = {"error": "intentionally skipped"}
    elif name == "frame_mark":
        from computer_mcp import live as _live
        result = _live.tool_frame_mark(arguments or {})
        result.setdefault("success", result.get("ok") is True and not result.get("error"))
        screenshot_data = {"error": "intentionally skipped"}
    elif name == "frame_diff":
        from computer_mcp import live as _live
        result = _live.tool_frame_diff(arguments or {})
        result.setdefault("success", result.get("ok") is True and not result.get("error"))
        screenshot_data = {"error": "intentionally skipped"}
    elif name == "trace":
        from computer_mcp import live as _live
        result = _live.tool_trace(arguments or {})
        result.setdefault("success", result.get("ok") is True and not result.get("error"))
        screenshot_data = {"error": "intentionally skipped"}
    elif name == "glyph":
        from computer_mcp import live as _live
        result = _live.tool_glyph(arguments or {})
        result.setdefault("success", result.get("ok") is True and not result.get("error"))
        screenshot_data = {"error": "intentionally skipped"}
    elif name == "read_digits":
        from computer_mcp import live as _live
        result = _live.tool_read_digits(arguments or {})
        result.setdefault("success", result.get("ok") is True and not result.get("error"))
        screenshot_data = {"error": "intentionally skipped"}
    elif name == "hud":
        from computer_mcp import live as _live
        result = _live.tool_hud(arguments or {})
        result.setdefault("success", result.get("ok") is True and not result.get("error"))
        screenshot_data = {"error": "intentionally skipped"}
    elif name == "track":
        from computer_mcp import live as _live
        result = _live.tool_track(arguments or {})
        result.setdefault("success", result.get("ok") is True and not result.get("error"))
        screenshot_data = {"error": "intentionally skipped"}
    elif name == "layout_mem":
        from computer_mcp import live as _live
        result = _live.tool_layout_mem(arguments or {})
        result.setdefault("success", result.get("ok") is True and not result.get("error"))
        screenshot_data = {"error": "intentionally skipped"}
    elif name == "screen_layout":
        from computer_mcp import live as _live
        result = _live.tool_screen_layout(arguments or {})
        result.setdefault("success", result.get("ok") is True and not result.get("error"))
        screenshot_data = {"error": "intentionally skipped"}
    elif name == "world_state":
        from computer_mcp import live as _live
        result = _live.tool_world_state(arguments or {})
        result.setdefault("success", result.get("ok") is True and not result.get("error"))
        screenshot_data = {"error": "intentionally skipped"}
    elif name == "servo":
        from computer_mcp import live as _live
        result = _live.tool_servo(arguments or {})
        result.setdefault("success", result.get("ok") is True and not result.get("error"))
        screenshot_data = {"error": "intentionally skipped"}
    elif name == "navigate":
        from computer_mcp import live as _live
        result = _live.tool_navigate(arguments or {})
        result.setdefault("success", result.get("ok") is True and not result.get("error"))
        screenshot_data = {"error": "intentionally skipped"}
    elif name == "housekeeping":
        from computer_mcp import live as _live
        result = _live.tool_housekeeping(arguments or {})
        result.setdefault("success", result.get("ok") is True and not result.get("error"))
        screenshot_data = {"error": "intentionally skipped"}
    elif name == "record":
        from computer_mcp import live as _live
        result = _live.tool_record(arguments or {})
        result.setdefault("success", result.get("ok") is True and not result.get("error"))
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
            ref=arguments.get('ref'),
            name=str(arguments.get("name", "")),
            element_id=arguments.get("element_id"),
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
    

    if name == "dataset_explore":
        from computer_mcp.dataset import explore as _de
        result = _de.run(int(arguments.get("steps", 12)),
                         int(arguments.get("interval_ms", 400)),
                         arguments.get("seed"))

    if name == "find_element":
        from computer_mcp.zones import sense_fallback as _sf
        srcs = arguments.get("sources") or ("uia", "ocr", "template")
        result = _sf.find_element(str(arguments.get("query", "")),
                                  hwnd=arguments.get("hwnd"),
                                  limit=int(arguments.get("limit", 5)),
                                  sources=tuple(srcs))

    if name == "find_elements_ranked":
        from computer_mcp import element_ops as _eo
        from computer_mcp.zones import sense_fallback as _sf
        srcs = arguments.get("sources") or ("uia", "ocr", "template")
        payload = _sf.find_element(str(arguments.get("query", "")),
                                   hwnd=arguments.get("hwnd"),
                                   limit=int(arguments.get("limit", 5)),
                                   sources=tuple(srcs),
                                   min_confidence=float(arguments.get("min_confidence", 0.0)))
        if arguments.get("include_state") and payload.get("ok"):
            target_hwnd = payload.get("hwnd") or arguments.get("hwnd")
            for candidate in payload.get("candidates", []):
                if not candidate.get("path") or not target_hwnd:
                    continue
                try:
                    candidate["state"] = _eo.read_state(int(target_hwnd), candidate["path"])
                except Exception as exc:                # noqa: BLE001
                    candidate["state_error"] = f"{type(exc).__name__}: {exc}"
        result = payload

    if name in ("element_state", "element_action"):
        from computer_mcp import element_ops as _eo
        from computer_mcp import snapshots as _snap
        from computer_mcp import ui_ext as _ui
        position = {}
        try:
            if arguments.get("ref"):
                position = _snap.resolve(str(arguments["ref"]), arguments.get("hwnd"))
                target = dict(position)
            else:
                found = _ui.ui_find(name=str(arguments.get("name", "")),
                                    hwnd=arguments.get("hwnd"),
                                    exact=bool(arguments.get("exact", False)),
                                    index=0)
                target = dict(found.get("target") or {})
        except _snap.StaleReference as exc:
            result = dict(ok=False, code="stale_element", error=str(exc))
        except Exception as exc:                        # noqa: BLE001
            result = dict(ok=False, error=f"{type(exc).__name__}: {exc}")
        else:
            path = target.get("path")
            hwnd = target.get("hwnd") or arguments.get("hwnd") or position.get("hwnd")
            if not path or not hwnd:
                result = dict(ok=False, code="no_path",
                              error="该元素没有可复用的 UIA 路径（OCR/模板命中），请用坐标操作")
            elif name == "element_state":
                try:
                    result = dict(ok=True, hwnd=int(hwnd), path=path,
                                  state=_eo.read_state(int(hwnd), str(path)))
                except Exception as exc:                # noqa: BLE001
                    result = dict(ok=False, hwnd=int(hwnd), path=path,
                                  error=f"{type(exc).__name__}: {exc}")
            else:
                action = str(arguments.get("action", "auto"))
                try:
                    before = _eo.read_state(int(hwnd), str(path))
                except Exception:                       # noqa: BLE001
                    before = {}
                try:
                    outcome = _eo.perform(int(hwnd), str(path), action,
                                          arguments.get("value"), mouse_controller)
                except Exception as exc:                # noqa: BLE001
                    outcome = dict(ok=False, error=f"{type(exc).__name__}: {exc}")
                outcome.update(hwnd=int(hwnd), path=path, action_requested=action)
                if outcome.get("ok") and arguments.get("verify", True):
                    try:
                        after = _eo.read_state(int(hwnd), str(path))
                    except Exception:                   # noqa: BLE001
                        after = {}
                    outcome["after"] = after
                    verdict = "executed_unverified"
                    if action == "set_value" or outcome.get("action") == "set_value":
                        expected = arguments.get("value")
                        if after.get("value") is not None and expected is not None:
                            verdict = ("verified_success" if str(after["value"]) == str(expected)
                                       else "no_effect")
                    elif "toggle" in (action, outcome.get("action")):
                        if before.get("toggle") is not None and after.get("toggle") is not None:
                            verdict = ("verified_success" if before["toggle"] != after["toggle"]
                                       else "no_effect")
                    elif "select" in (action, outcome.get("action")):
                        if after.get("selected") is not None:
                            verdict = "verified_success" if after["selected"] else "no_effect"
                    outcome["verification"] = verdict
                result = outcome

    if name == "type_verified":
        import time as _time
        from computer_mcp import element_ops as _eo
        from computer_mcp import snapshots as _snap
        from computer_mcp import ui_ext as _ui
        text = str(arguments.get("text", ""))
        hwnd = arguments.get("hwnd")
        target = {}
        try:
            if arguments.get("ref"):
                target = _snap.resolve(str(arguments["ref"]), hwnd)
                hwnd = target.get("hwnd") or hwnd
            elif arguments.get("name"):
                found = _ui.ui_find(name=str(arguments["name"]), hwnd=hwnd,
                                    exact=bool(arguments.get("exact", False)), index=0)
                target = dict(found.get("target") or {})
                hwnd = hwnd or target.get("hwnd")
        except _snap.StaleReference as exc:
            result = dict(ok=False, code="stale_element", error=str(exc))
        except Exception as exc:                        # noqa: BLE001
            result = dict(ok=False, error=f"{type(exc).__name__}: {exc}")
        else:
            path = target.get("path")
            if path and hwnd:
                try:
                    _eo.perform(int(hwnd), str(path), "focus", None, mouse_controller)
                except Exception:                       # noqa: BLE001
                    pass
            typed = keyboard_actions.type_text(text=text, controller=keyboard_controller)
            if arguments.get("clear_first"):
                # Select all then overwrite: the common "replace the field" idiom.
                keyboard_actions.key_down("ctrl", controller=keyboard_controller)
                keyboard_actions.key_press("a", controller=keyboard_controller)
                keyboard_actions.key_up("ctrl", controller=keyboard_controller)
                typed = keyboard_actions.type_text(text=text, controller=keyboard_controller)
            after = None
            if path and hwnd:
                for _ in range(3):
                    _time.sleep(0.12)
                    try:
                        after = _eo.read_state(int(hwnd), str(path))
                    except Exception:                   # noqa: BLE001
                        after = None
                    if after and after.get("value") is not None:
                        break
            value = None if after is None else after.get("value")
            if value is None:
                verdict, reason = "executed_unverified", "no_readable_target"
            else:
                expected = text.rstrip("\n")
                got = str(value)
                if got == expected or got.endswith(expected):
                    verdict, reason = "verified_success", ""
                else:
                    verdict, reason = "no_effect", "value_mismatch"
            result = dict(ok=True, action="type_verified", text=text, typed=typed,
                          value=value, verification=verdict, reason=reason,
                          hwnd=int(hwnd) if hwnd else None, path=path)
            if arguments.get("submit") and verdict == "verified_success":
                keyboard_actions.key_press("enter", controller=keyboard_controller)
                result["submitted"] = True

    if name == "wait_for":
        from computer_mcp.zones import wait_for as _wf
        result = _wf.run(kind=str(arguments.get("kind", "change")),
                         query=arguments.get("query"),
                         element_id=arguments.get("element_id"),
                         timeout_ms=int(arguments.get("timeout_ms", 5000)),
                         interval_ms=int(arguments.get("interval_ms", 150)))

    if name == "control_status":
        from computer_mcp import control as _ctl
        result = _ctl.status()
        from computer_mcp.runtime_contract import describe
        result['runtime_contract'] = describe()
        # v1.4.0: report which execution policy is in force and what it thinks
        # the runtime state is (ready / user_takeover / stopped / error), so a
        # caller no longer has to interpret "granted / lease / scope".
        from computer_mcp import policy as _policy
        result['policy'] = dict(mode=_policy.mode(), runtime=_policy.runtime_state())
        if _policy.is_local():
            # Headless has no consent service; querying it only produces a
            # misleading "caller_granted: false" next to an executable tool.
            result["authorization_diagnostic"] = dict(
                agent_session=_policy.agent_session.current(),
                caller_granted=result['policy']['runtime'] == 'ready',
                source='local-policy')
        else:
            from computer_mcp.permission import caller_diagnostic
            result["authorization_diagnostic"] = caller_diagnostic(
                arguments.get("requested_scopes"), arguments.get("hwnd"))

    elif name == "control_claim":
        from computer_mcp import control as _ctl
        act = str(arguments.get("action", "claim"))
        result = (_ctl.release(str(arguments.get("reason", "agent release")))
                  if act == "release"
                  else _ctl.claim(str(arguments.get("reason", "agent"))))

    if name == "dataset_status":
        from computer_mcp import dataset as _ds
        result = _ds.status()
    if name == "dataset_query":
        from computer_mcp.dataset import query as _dq
        kw = {"tool": arguments.get("tool"), "zone": arguments.get("zone"),
              "verdict": arguments.get("verdict"), "days": arguments.get("days"),
              "limit": arguments.get("limit", 20)}
        rows = _dq.search(**kw)
        payload = {"success": True, "count": len(rows), "items": rows}
        if arguments.get("group_by"):
            payload["grouped"] = _dq.group_by(arguments["group_by"], arguments.get("days"))
        result = payload

    elif name == "dataset_promote":
        from computer_mcp.dataset import promote as _dp
        result = _dp.promote(arguments.get("episode_id", ""), arguments.get("note", ""))

    elif name == "dataset_export":
        from computer_mcp.dataset import export as _de
        result = {"success": True, **_de.export(arguments.get("days", 7), arguments.get("tag"))}
    elif name == "dataset_triage":
        from computer_mcp.dataset import triage as _dt
        result = _dt.run(arguments.get("days", 1), arguments.get("min_count", 3),
                         bool(arguments.get("dry_run", False)))


    if _is_input:
        _ctl.quiet()
    return {"result": result, "screenshot_data": screenshot_data}
