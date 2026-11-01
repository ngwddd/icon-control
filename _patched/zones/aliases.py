"""zones/aliases.py — 旧名 → 规范名（R8，domain_noun_verb）。

只做名字映射，不改任何行为。旧名永久保留（至少 6 个月），
因为宏、配方、历史脚本、以及用户自己的习惯都可能写的是旧名。
"""

from __future__ import annotations

ALIASES: dict[str, str] = {
    # 窗口（win_* 前缀，让同族工具按字母序聚在一起）
    "snap_window_left": "win_snap_left",
    "snap_window_right": "win_snap_right",
    "snap_window_top": "win_snap_top",
    "snap_window_bottom": "win_snap_bottom",
    "get_window_info": "win_info",
    "switch_to_window": "win_switch",
    "list_windows": "win_list",
    "move_window": "win_move",
    "resize_window": "win_resize",
    "close_window": "win_close",
    # 帧/判据（frame_* 前缀）
    "read_digits": "frame_digits_read",
    "screen_state": "frame_state",
    "world_state": "frame_world_state",
    "screen_layout": "frame_layout",
}

CANONICAL_ONLY = {v: k for k, v in ALIASES.items()}


def resolve(name: str) -> str:
    """任意名字（旧/新）→ 实现里用的名字（当前实现仍是旧名）。"""
    return CANONICAL_ONLY.get(name, name)


def canonical(name: str) -> str:
    """任意名字 → 规范名（新名）。"""
    return ALIASES.get(name, name)
