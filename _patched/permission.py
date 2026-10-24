"""permission.py — 鼠标接管的**硬闸门**（v0.2）

v0.1 的授权开关只做到"agent 自己愿意先查一下"（`mouse_permission.py` 靠自觉）。
v0.2 把它下沉到执行点：**任何会动输入的工具，在真正执行之前都会被这里拦一次**，
未授权就直接返回结构化拒绝，根本不进入 mouse_actions / keyboard_actions。

判定来源（按优先级）
  1. 环境变量 `DSH_MOUSE_GATE=off`  → 整体放行（只给自动化测试用，会记录 reason）
  2. 状态文件（默认 `~/.dsh/tools/desktop-mcp/state/mouse-permission.json`）
     新鲜度 < TTL（默认 45 s）时直接复用，命中约 0 ms
  3. 状态过期 → 读 GUI 上那个胶囊（"鼠标·已授权 / 未授权"）→ 回写状态文件
  4. 读不到（GUI 没开 / OCR 失败）→ **fail closed**：拒绝

设计原则
  · **fail closed**：拿不准就算没授权。没授权时宁可什么都不做。
  · **只读授权**：这里只读，不写任何授权状态；授权只能由用户在 GUI 上点。
  · **零成本常驻**：缓存命中不截图，不给每次点击加 IO。

CLI:
    python -m computer_mcp.permission            # 打印状态
    python -m computer_mcp.permission --json     # 机器可读
"""

from __future__ import annotations

import json
import os
import re
import time

STATE_DIR = os.path.join(os.path.expanduser("~"), ".dsh", "tools", "desktop-mcp", "state")
STATE_PATH = os.environ.get("DSH_MOUSE_STATE") or os.path.join(STATE_DIR, "mouse-permission.json")
CACHE_TTL_S = float(os.environ.get("DSH_MOUSE_TTL", "45"))

# 会改变用户输入/焦点状态的工具 —— 这些必须先过闸门
INPUT_TOOLS = frozenset({
    "click", "double_click", "triple_click", "button_down", "button_up", "drag",
    "mouse_move", "type", "key_press", "key_down", "key_up",
    "batch", "ui_click", "ui_invoke", "ui_set_text",
    "macro_run", "click_text", "click_template", "hover_probe",
})

# 判断胶囊所在位置（GUI 输入框工具栏；从宽到窄多次尝试）
SCAN_REGIONS = (
    {"x": 900, "y": 1180, "w": 1200, "h": 120},
    {"x": 400, "y": 1120, "w": 2000, "h": 240},
    {"x": 0, "y": 1000, "w": 2560, "h": 440},
)


class PermissionDenied(RuntimeError):
    """未授权时抛出。"""


def _gate_disabled() -> bool:
    return os.environ.get("DSH_MOUSE_GATE", "on").strip().lower() in {"0", "off", "false", "no"}


def _read_state_file() -> dict | None:
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and "granted" in data:
            return data
    except Exception:
        pass
    return None


def _write_state_file(payload: dict) -> None:
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_PATH)
    except Exception:
        pass


def _read_pill() -> tuple[bool | None, str]:
    """读 GUI 上那个胶囊。返回 (granted|None, 屏幕文字片段)。"""
    try:
        from computer_mcp import ocr_ext
    except Exception:
        return None, "ocr_ext unavailable"

    for region in SCAN_REGIONS:
        try:
            res = ocr_ext.ocr_read(region=region, max_lines=20, upscale=1.8, boost=True)
        except Exception:
            continue
        text = re.sub(r"\s+", "", " ".join(ln.get("text", "") for ln in (res.get("lines") or [])))
        if "鼠标" not in text:
            continue
        if "已授权" in text:
            return True, text[:80]
        if "未授权" in text or "床授权" in text:   # OCR 常把"未"认成"床"
            return False, text[:80]
        return None, text[:80]
    return None, ""


def status(force: bool = False) -> dict:
    """当前授权状态。命中缓存时几乎是零成本。"""
    now = time.time()
    if _gate_disabled():
        return {"granted": True, "source": "env-disabled", "age_s": 0.0,
                "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"), "screen_text": ""}

    cached = _read_state_file()
    if cached and not force:
        age = now - float(cached.get("checked_at_ts") or 0)
        if 0 <= age < CACHE_TTL_S:
            return {"granted": bool(cached["granted"]), "source": cached.get("source", "cache"),
                    "age_s": round(age, 1), "checked_at": cached.get("checked_at"),
                    "screen_text": cached.get("screen_text", "")}

    granted, snippet = _read_pill()
    source = "screen" if granted is not None else "unknown"
    payload = {
        "granted": bool(granted),
        "source": source,
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "checked_at_ts": now,
        "screen_text": snippet,
    }
    _write_state_file(payload)
    return {"granted": bool(granted), "source": source, "age_s": 0.0,
            "checked_at": payload["checked_at"], "screen_text": snippet}


def check_tool(name: str, arguments: dict | None = None) -> dict | None:
    """输入类工具的统一闸门。返回 None 表示放行，返回 dict 表示拒绝载荷。"""
    if name not in INPUT_TOOLS:
        return None
    st = status()
    if st["granted"]:
        return None
    return {
        "success": False,
        "blocked": True,
        "error": "鼠标接管未授权：GUI 上的开关是灰色的。请让用户在界面上点亮「鼠标·已授权」后重试。",
        "tool": name,
        "permission": st,
        "hint": "这是硬闸门（v0.2）：未授权时任何输入类工具都在执行前被拦下，不会产生任何鼠标/键盘动作。",
    }


def require(tool: str = "unknown") -> None:
    """非 MCP 路径（脚本、宏、测试）用这个：未授权就抛异常。"""
    st = status()
    if not st["granted"]:
        raise PermissionDenied(
            f"鼠标接管未授权（tool={tool}, source={st['source']}）。"
            "请在 DSH 界面点亮「鼠标·已授权」。"
        )


def enabled() -> bool:
    return not _gate_disabled()


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--force", action="store_true", help="跳过缓存，重新读屏幕")
    args = ap.parse_args()

    st = status(force=args.force)
    if args.json:
        print(json.dumps(st, ensure_ascii=False, indent=2))
    else:
        print("鼠标接管权限：" + ("已授权（绿色）" if st["granted"] else "未授权（灰色）"))
        print(f"  来源={st['source']}  缓存年龄={st['age_s']}s  检查于={st['checked_at']}")
        if st["screen_text"]:
            print(f"  屏幕文字：{st['screen_text']!r}")
        if not st["granted"]:
            print("  → 输入类工具会被硬闸门拦下。")
    return 0 if st["granted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
