"""permission.py — 鼠标接管的**硬闸门**（v0.3，颜色+文字双判）

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

# 桥接状态（客户端插件经本地 HTTP 直报）的有效期：心跳 5s，15s 不更新即过期，
# 过期后退回 OCR 读屏幕 —— 桥挂了也不会一直"以为已授权"。
BRIDGE_TTL_S = float(os.environ.get("DSH_MOUSE_BRIDGE_TTL", "15"))

# 会改变用户输入/焦点状态的工具 —— 这些必须先过闸门
INPUT_TOOLS = frozenset({
    "click", "double_click", "triple_click", "button_down", "button_up", "drag",
    "mouse_move", "type", "key_press", "key_down", "key_up",
    "batch", "ui_click", "ui_invoke", "ui_set_text",
    "macro_run", "click_text", "click_template", "hover_probe",
})

# 判断胶囊所在位置（GUI 输入框工具栏；从宽到窄多次尝试）
# 只扫「输入框工具栏」这一条窄带。
# ⚠ 原来第三条是 (0,1000,2560,440) —— 窗口下三分之一全都算进来，
#   OCR 会读到聊天正文里的“鼠标·已授权”字样，再撞上一处绿色像素就误判成已授权
#   （假阳性，最危险的方向）。现在宁可读不到（→ unknown → 按未授权处理）。
SCAN_REGIONS = (
    {"x": 900, "y": 1170, "w": 1250, "h": 110},
    {"x": 780, "y": 1120, "w": 1500, "h": 200},
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


def _green_capsule(region: dict) -> bool | None:
    """粗判：该区域内是否存在一个「绿色胶囊」形状的色块。

    绿色 = 用户在 GUI 上点了授权（GUI 用绿色表示已授权）。
    只读像素，不改任何状态。拿不准就返回 None（fail closed）。
    """
    try:
        import mss
        from PIL import Image
    except Exception:
        return None
    try:
        mon = {"left": int(region["x"]), "top": int(region["y"]),
               "width": int(region["w"]), "height": int(region["h"])}
        with mss.mss() as sct:
            shot = sct.grab(mon)
        im = Image.frombytes("RGB", shot.size, shot.rgb)
    except Exception:
        return None

    px = im.load()
    W, H = im.size
    xs, ys = [], []
    count = 0
    step = 1 if W * H <= 200_000 else 2
    for yy in range(0, H, step):
        for xx in range(0, W, step):
            r, g, b = px[xx, yy]
            if g > 110 and (g - r) > 45 and (g - b) > 35:
                count += 1
                xs.append(xx)
                ys.append(yy)
    if count < 25:
        return None
    bw = max(xs) - min(xs) + 1
    bh = max(ys) - min(ys) + 1
    # 胶囊形状：宽 50–420 px，高 8–70 px
    if 50 <= bw <= 420 and 8 <= bh <= 70:
        return True
    return None


def _read_pill() -> tuple[bool | None, str]:
    """读 GUI 上那个胶囊。返回 (granted|None, 屏幕文字片段)。

    v0.3：先读**颜色**（绿色=已授权），再用 OCR 文字交叉确认。
    原因：OCR 会把「已授权」认成「已授杈/已授捘」，只靠文字会误判为未知。
    """
    try:
        from computer_mcp import ocr_ext
    except Exception:
        ocr_ext = None

    for region in SCAN_REGIONS:
        # --- 1) 颜色判定（权威信号）---
        green = _green_capsule(region)

        # --- 2) 文字判定（交叉确认）---
        text = ""
        if ocr_ext is not None:
            try:
                res = ocr_ext.ocr_read(region=region, max_lines=20, upscale=1.8, boost=True)
                text = re.sub(r"\s+", "", " ".join(ln.get("text", "")
                                                   for ln in (res.get("lines") or [])))
            except Exception:
                text = ""

        if "鼠标" not in text and green is None:
            continue

        # 正面判定必须「绿 + 胶囊文字」同时成立；只有绿色块不算（聊天里也有绿）
        if green is True and "鼠标" in text and "已授权" in text and "未授权" not in text:
            return True, text[:80]
        if text and ("未授权" in text or "床授权" in text or "未授" in text):
            return False, text[:80]
        if text and "鼠标" in text:
            # 有胶囊文字但没检测到绿色 → 视为灰色（未授权）
            return False, text[:80]
    return None, ""


_bridge_started = False


def _bridge_port() -> int:
    try:
        return int(os.environ.get("DSH_MOUSE_BRIDGE_PORT", "18765"))
    except Exception:
        return 18765


def _port_open(port: int) -> bool:
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def _ensure_bridge() -> None:
    """桥没起来就顺手拉起来（自愈）。

    只在要走 OCR 之前调用一次；失败也无所谓 —— OCR 后备还在。
    DSH_MOUSE_BRIDGE=off 可关掉这个行为（纯离线/审计场景）。
    """
    global _bridge_started
    if _bridge_started:
        return
    _bridge_started = True
    if os.environ.get("DSH_MOUSE_BRIDGE", "on").strip().lower() in {"0", "off", "false", "no"}:
        return
    if _port_open(_bridge_port()):
        return
    try:
        import subprocess
        flags = 0
        if os.name == "nt":
            flags = 0x00000008 | 0x08000000      # DETACHED_PROCESS | CREATE_NO_WINDOW
        # 优先用包内模块启动（不依赖根目录脚本在不在）
        subprocess.Popen([os.sys.executable, "-m", "computer_mcp.permission_bridge"],
                         stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         creationflags=flags, close_fds=True)
    except Exception:
        pass


def status(force: bool = False) -> dict:
    """当前授权状态。命中缓存时几乎是零成本。"""
    now = time.time()
    if _gate_disabled():
        return {"granted": True, "source": "env-disabled", "age_s": 0.0,
                "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"), "screen_text": ""}

    cached = _read_state_file()
    if cached and not force:
        age = now - float(cached.get("checked_at_ts") or 0)
        ttl = BRIDGE_TTL_S if cached.get("source") == "bridge" else CACHE_TTL_S
        if 0 <= age < ttl:
            return {"granted": bool(cached["granted"]), "source": cached.get("source", "cache"),
                    "age_s": round(age, 1), "checked_at": cached.get("checked_at"),
                    "screen_text": cached.get("screen_text", "")}

    _ensure_bridge()
    time.sleep(0.7)
    refreshed = _read_state_file()
    if refreshed:
        age2 = time.time() - float(refreshed.get("checked_at_ts") or 0)
        if 0 <= age2 < BRIDGE_TTL_S:
            return {"granted": bool(refreshed["granted"]),
                    "source": refreshed.get("source", "cache"),
                    "age_s": round(age2, 1),
                    "checked_at": refreshed.get("checked_at"),
                    "screen_text": refreshed.get("screen_text", "")}

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
