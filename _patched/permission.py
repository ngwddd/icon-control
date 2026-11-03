"""Execution authority: fresh HMAC-signed bridge state, physical takeover and emergency stop.
OCR and legacy cache readers remain diagnostic helpers and never grant authority.
DSH_MOUSE_GATE cannot disable this boundary. Explicit user actions alone grant;
revocation, expired state, listener failures and unknown tools fail closed.
"""

from __future__ import annotations

import json
import os
import re
import time
from computer_mcp import security

STATE_DIR = str(security.data_home() / 'state')
STATE_PATH = os.environ.get("DSH_MOUSE_STATE") or os.path.join(STATE_DIR, "mouse-permission.json")
CACHE_TTL_S = float(os.environ.get("DSH_MOUSE_TTL", "45"))

# 桥接状态（客户端插件经本地 HTTP 直报）的有效期：心跳 5s，15s 不更新即过期，
# 过期后退回 OCR 读屏幕 —— 桥挂了也不会一直"以为已授权"。
BRIDGE_TTL_S = float(os.environ.get("DSH_MOUSE_BRIDGE_TTL", "15"))

# 负向结果（未授权 / 读不到）的缓存时间。
# 原来负向结果也走 CACHE_TTL_S（45s）：一次 OCR 失败（窗口被挡、GUI 被切走、
# 胶囊被 OCR 认错）就会让你在接下来 45 秒里**连桥都不再问**，表现就是
# 「GUI 上是绿的，后台一直判灰」。现在负向只缓存 3 秒。
NEG_TTL_S = float(os.environ.get("DSH_MOUSE_NEG_TTL", "3"))

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

        # ── 2026-11-02 修 bug：OCR 读不清时**不许判灰** ──────────────────
        # 旧逻辑：只要文字里出现「鼠标」，而绿色没测到（窗口被遮挡 / 移出固定
        # 扫描区 / DPI 变了），或文字被 OCR 认成「床授权」，就直接 return False。
        # 结果是「前端明明是绿的，后台被拦」，而且写进缓存后还会持续 45 秒。
        # 现在：只有明确读到「未授权」才判灰；其余含糊情况一律返回 None，
        # 交给 status() 再问一次桥（桥才是权威信号）。
        if text and ("未授权" in text or "未授" in text):
            return False, text[:80]
        # 正面：绿色像素是权威信号，文字只要带「授权」且没有「未授权」即可
        #（容忍 OCR 把「已」认成别的字，例如实测过的「床授权」）
        if green is True and "鼠标" in text and "授权" in text and "未授权" not in text:
            return True, text[:80]
        if text and "鼠标" in text:
            return None, text[:80]          # 含糊 → 不表态
    return None, ""


_bridge_started = False


def _bridge_port() -> int:
    return security.bridge_port()


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


def _ttl_for(cached: dict) -> float:
    """这条缓存能信多久。

    · 桥来的 → BRIDGE_TTL_S（15s，桥每 5s 心跳一次）
    · 屏幕来的正向 → CACHE_TTL_S（45s，绿色胶囊不会莫名其妙变灰）
    · 屏幕来的负向 / 读不到 → NEG_TTL_S（3s，给桥一个马上翻案的机会）
    """
    if cached.get("source") == "bridge":
        return BRIDGE_TTL_S
    if cached.get("granted"):
        return CACHE_TTL_S
    return NEG_TTL_S


def status(force: bool = False, agent_session_id=None) -> dict:
    """Only a fresh, signed bridge action is authority; OCR is diagnostic only."""
    now = time.time()
    cached = _read_state_file()
    try:
        age = now - float(cached['checked_at_ts']) if cached else -1
        if (cached and type(cached.get('granted')) is bool and
                cached.get('source') == 'bridge' and security.authentic(cached) and
                0 <= age < BRIDGE_TTL_S and now < float(cached.get('expires_at',now+BRIDGE_TTL_S)) and
                not security.stopped(cached)):
            from computer_mcp import capabilities, agent_session
            auth = cached.get('authorization', {})
            if cached.get('granted') and not capabilities.validate(auth):
                return dict(granted=False, source='bridge', reason='Approval record is invalid')
            if cached.get('granted') and auth.get('lease_expires_at') and \
                    now >= float(auth['lease_expires_at']):
                return dict(granted=False, source='bridge', reason='Lease expired')
            if cached.get('granted') and auth['agent_session'] != (agent_session_id or agent_session.current()):
                # A time-boxed lease covers every new process of the same identity.
                leased = auth.get('agent_id') and auth['agent_id'] == agent_session.identity()
                if not leased:
                    return dict(granted=False, source='bridge', reason='Approval belongs to another Agent session')
            if cached.get('granted'):
                from computer_mcp.consent_ipc import live_valid
                if not live_valid(cached, agent_session_id or agent_session.current()):
                    return dict(granted=False, source='unknown', reason='Live permission authority unavailable or revoked')
            return dict(cached, age_s=round(age, 3))
    except (ValueError, TypeError, KeyError):
        pass
    return dict(granted=False, source='unknown', age_s=0.0, screen_text='',
                checked_at='', reason='Missing, expired or unauthenticated bridge state')


_last_consent_request = 0.0
CONSENT_POPUP_INTERVAL_S = 20.0


def _request_consent() -> None:
    """A blocked call should bring up the approval window, not just an error."""
    global _last_consent_request
    if os.environ.get('ICON_CONTROL_AUTO_CONSENT') == '0':
        return
    now = time.time()
    if now - _last_consent_request < CONSENT_POPUP_INTERVAL_S:
        return
    _last_consent_request = now
    try:
        from computer_mcp import agent_session, consent_ipc
        consent_ipc.request('open', timeout_ms=300,
                            prefer_session=agent_session.current())
    except Exception:
        pass


def check_tool(name: str, arguments: dict | None = None) -> dict | None:
    """输入类工具的统一闸门。返回 None 表示放行，返回 dict 表示拒绝载荷。"""
    from computer_mcp import tool_registry, panic
    spec = tool_registry.get(name)
    if spec is None or not tool_registry.allowed(name):
        return dict(success=False, blocked=True, tool=name, error='Tool disabled or unknown')
    if not spec.needs_authority(arguments):
        return None
    st = status()
    if st["granted"]:
        from computer_mcp import capabilities
        why = capabilities.check_scope(st, spec, arguments)
        if why:
            _request_consent()
            return dict(success=False, blocked=True, tool=name, error=why)
        if set(spec.effects_for(arguments)) <= {'screen_read','observe'}:
            return None
        emergency = panic.default()
        if (emergency.triggered and isinstance(emergency.triggered_at_wall,(int,float)) and
                (st.get('authorized_at',0) > emergency.triggered_at_wall or
                 (getattr(emergency,'durable_saved',False) is True and not security.stopped(st)))):
            emergency.reset()
        if emergency.triggered or not emergency.ready:
            return dict(success=False, blocked=True, tool=name, permission=st,
                        error='Emergency stop active or listener unavailable')
        # P0-1：授权之外还看「控制权是否在用户手上」（用户随时可以夺回）
        try:
            from computer_mcp import control as _ctl
            why = _ctl.blocking_reason()
            if why:
                return {
                    "success": False,
                    "blocked": True,
                    "error": f"控制权在用户手上：{why}",
                    "tool": name,
                    "permission": st,
                    "control": _ctl.status(),
                    "hint": "真人鼠标持续移动满 1 秒才接管；键盘、点击和滚轮立即接管。闲置后可重新申请，原任务不会恢复。",
                }
        except Exception as exc:
            return dict(success=False, blocked=True, tool=name, error=f'Control guard unavailable: {exc}')
        return None
    _request_consent()
    return {
        "success": False,
        "blocked": True,
        "error": "桌面助手未授权：按 Ctrl+Alt+Shift+F9（或点托盘图标）打开授权窗口，点「一键授权」后重试。",
        "tool": name,
        "permission": st,
        "hint": "授权只由人触发；60 分钟内同一工作区的新进程自动沿用。",
    }


def require(tool: str = "unknown", arguments: dict | None = None) -> None:
    """非 MCP 路径（脚本、宏、测试）用这个：未授权就抛异常。"""
    denial = check_tool(tool, arguments)
    if denial is not None:
        raise PermissionDenied(denial['error'])


def enabled() -> bool:
    return True


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
