"""permission_bridge.py — 鼠标授权状态的「程序层」通道（替代 OCR）

为什么需要它：Host 侧原来靠 OCR 读界面上那个胶囊是不是绿的 —— 窗口一挪、一滚、
被遮挡、换分辨率就判不出来（fail closed 会拦掉所有鼠标操作）；更糟的是它还会
读到聊天正文里的「鼠标·已授权」字样而误判成已授权（假阳性，方向最危险）。

现在改成：GUI 上的插件把状态**直接上报**过来，Host 读状态文件即可。

端点（只听 127.0.0.1）
    POST /state   Authorization: Bearer <token>，body: {"granted": true|false}
    GET  /state   同样需要认证请求头

安全
    · 只 bind 127.0.0.1，不对外
    · **token** 从本机 `state/bridge-token.txt` 读取（不进源码、不进仓库；
      图片信标不带 Origin，只靠 Origin 校验等于对任何网页敞开，所以必须有 token）
    · 另外仍校验 Origin（dsh-app:// / file:// / 127.0.0.1 / localhost）
    · 只写一个 JSON 状态文件，不执行任何命令
"""

from __future__ import annotations

import argparse
import json
import hmac
import secrets
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from computer_mcp import security

DEFAULT_PORT = security.bridge_port()
ALLOW_ANY_PATH = "/state"
EVENTS_PATH = '/events'
STREAM_PING_SECONDS = 4.0
_streams = threading.BoundedSemaphore(8)

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", "..", ".."))
STATE_DIR = str(security.data_home() / 'state')
STATE_PATH = os.path.join(STATE_DIR, "mouse-permission.json")
LOG_PATH = os.path.join(STATE_DIR, "bridge.log")
TOKEN_PATH = str(security.token_path())

_lock = threading.RLock()

# Token is mandatory from the first request; there is no compatibility bypass.


def log(line: str) -> None:
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    except Exception:
        pass


def load_token() -> str:
    return security.load_token()


# ── 多窗口状态表（2026-11-02 修 bug）─────────────────────────────────
# 历史问题：所有窗口都往同一个状态文件写「自己的当前值」，后写的覆盖先写的。
# 于是一个窗口点了授权（绿），另一个窗口的心跳仍在上报 false，Host 就读到 false
# —— 表现就是「前端是绿的，后台被拦」。
# 现在按 client 分开记，并区分「用户动作」与「心跳」：
#   动作（点按钮）能改变全局授权；心跳只表示「这个窗口还活着、它当前是什么值」。
CLIENTS: dict[str, dict] = {}
_last_action = None
_revision = 0
_session = secrets.token_hex(16)
_client_sequences = {}
_last_event_stamp = int(time.time()*1000)
CLIENT_HB_TTL_S = 30.0          # 心跳多久内算这个窗口还活着
CLIENT_ACTION_TTL_S = 1800.0    # 用户动作的有效期（30 分钟）


def note_client(client: str, granted: bool, event: str) -> None:
    global _last_action, _revision
    now = time.time()
    key = (client or "default")[:64]
    CLIENTS[key] = {"granted": bool(granted), "ts": now, "event": event}
    if event == 'action':
        _revision += 1
        _last_action = (now, bool(granted), key)
    for k in list(CLIENTS):                    # 清掉陈旧条目，避免无限增长
        if now - CLIENTS[k]["ts"] > CLIENT_ACTION_TTL_S:
            CLIENTS.pop(k, None)


def effective_state() -> tuple:
    """Only the latest explicit user action may grant; heartbeats only keep it live."""
    now = time.time()
    if _last_action is None:
        return False, 'no-user-action'
    ts, granted, client = _last_action
    live = CLIENTS.get(client, {})
    if now - ts > CLIENT_ACTION_TTL_S or now - live.get('ts', 0) > CLIENT_HB_TTL_S:
        return False, 'expired'
    return granted, 'action@%ds' % int(now - ts)


def write_state(granted: bool, origin: str = "bridge",
                client: str = None, event: str = None, sequence=None, action_at=None) -> None:
    with _lock:
        global _last_event_stamp
        if event == 'action' and sequence is not None:
            if (type(sequence) is not int or sequence <= _client_sequences.get(client,0) or
                type(action_at) is not int or action_at < _last_event_stamp or
                (action_at == _last_event_stamp and granted and _last_action is not None and not _last_action[1]) or
                abs(time.time()*1000-action_at)>30000):
                return
            _client_sequences[client]=sequence
            _last_event_stamp=action_at
        _write_state_locked(granted, origin, client, event)

def _write_state_locked(granted, origin, client, event):
    now = time.time()
    if client is None and event is None:
        # A legacy caller cannot establish new authority without a user action.
        note_client("default", granted, "hb")
        eff, why = effective_state()
    else:
        note_client(client or "default", granted, event or "hb")
        eff, why = effective_state()
        if eff is None:                        # 理论上不会走到
            eff, why = bool(granted), "single"
    payload = {
        'session': _session,
        "revision": _revision,
        "granted": bool(eff),
        'authorized_at': _last_action[0] if _last_action else 0,
        'expires_at': min(now+15,(_last_action[0]+CLIENT_ACTION_TTL_S) if _last_action else now),
        "source": "bridge",
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "checked_at_ts": now,
        "screen_text": "",
        "origin": origin,
        "effective_from": why,
        "clients": {k: {"granted": v["granted"], "event": v["event"],
                        "age_s": round(now - v["ts"], 1)}
                    for k, v in list(CLIENTS.items())[:8]},
    }
    token = load_token()
    if not token:
        raise RuntimeError('Permission bridge requires a provisioned token')
    payload['signature'] = security.signature(payload, token)
    with _lock:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_PATH)


def read_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {"granted": False, "source": "unknown"}


class Handler(BaseHTTPRequestHandler):
    server_version = "dsh-permission-bridge/1.1"

    def log_message(self, fmt, *args):      # 静音默认访问日志
        return

    def _cors(self) -> None:
        origin = self.headers.get('Origin')
        if origin and self._trusted_source(origin):
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        if self.headers.get('Access-Control-Request-Private-Network') == 'true':
            self.send_header('Access-Control-Allow-Private-Network', 'true')

    def _source_ok(self) -> bool:
        """来源校验：Origin 或 Referer 必须指向 DSH 自己的页面。

        · fetch 请求带 Origin（dsh-app:// 或 127.0.0.1）
        · 图片信标不带 Origin，但带 Referer（页面 URL）
        · CLI / 原生客户端两者都没有 → 放行（它与本进程同级权限，拦也没意义）
        远程网页的 Origin/Referer 是自己站点的 URL，会被拒。
        """
        origin = (self.headers.get("Origin") or "").strip().lower()
        referer = (self.headers.get("Referer") or "").strip().lower()
        if not origin and not referer:
            return True
        return all(self._trusted_source(value) for value in (origin, referer) if value)

    @staticmethod
    def _trusted_source(value):
        try:
            parsed = urlparse(value)
            return not parsed.username and not parsed.password and (
                parsed.scheme == 'dsh-app' or
                (parsed.scheme == 'file' and parsed.hostname in (None, '', 'localhost')) or
                (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost')))
        except ValueError:
            return False

    def _authorized(self, parsed) -> bool:
        path = parsed.path
        if path not in (ALLOW_ANY_PATH,EVENTS_PATH) or parsed.query:
            log(f"REJECT path={path}")
            return False
        if not self._source_ok():
            log(f"REJECT source path={path} "
                f"origin={self.headers.get('Origin')!r} referer={self.headers.get('Referer')!r}")
            return False
        # First request and every subsequent request require the installed secret.
        expected = load_token()
        got = self.headers.get('Authorization','')
        return bool(expected and hmac.compare_digest('Bearer '+expected, got))

    def do_OPTIONS(self):
        requested={h.strip().lower() for h in self.headers.get('Access-Control-Request-Headers','').split(',') if h.strip()}
        if (urlparse(self.path).path not in (ALLOW_ANY_PATH,EVENTS_PATH) or urlparse(self.path).query or
                not self._source_ok() or not requested <= {'authorization','content-type'}):
            self.send_error(403,'Preflight rejected');return
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if not self._authorized(parsed):
            self.send_response(403)
            self._cors()
            self.end_headers()
            return
        if parsed.path == EVENTS_PATH:
            if not _streams.acquire(blocking=False):
                self.send_error(503,'Too many event streams');return
            try:
                self.send_response(200)
                self.send_header('Content-Type','application/x-ndjson')
                self.send_header('Cache-Control','no-store')
                self.send_header('Connection','close')
                self._cors();self.end_headers()
                # Pings alone never refresh or grant authority. Only the
                # authenticated renderer acknowledgements are heartbeats.
                while True:
                    self.wfile.write(b'{"event":"heartbeat"}\n')
                    self.wfile.flush()
                    time.sleep(STREAM_PING_SECONDS)
            except (BrokenPipeError,ConnectionError,OSError):
                pass
            finally:
                _streams.release()
            return
        body = json.dumps(read_state(), ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        parsed = urlparse(self.path)
        if not self._authorized(parsed):
            self.send_response(403)
            self._cors()
            self.end_headers()
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n < 1 or n > 4096:
                self.send_error(413, 'Invalid body length')
                return
            raw = self.rfile.read(n).decode("utf-8", "replace") if n else "{}"
        except Exception:
            raw = "{}"
        if parsed.path != ALLOW_ANY_PATH:
            self.send_error(404);return
        try:
            data = json.loads(raw)
        except Exception:
            data = {}
        if not isinstance(data, dict) or "granted" not in data:
            self.send_response(400)
            self._cors()
            self.end_headers()
            return
        if type(data.get('granted')) is not bool:
            self.send_error(400, 'granted must be a boolean')
            return
        granted = data['granted']
        client = str(data.get("client") or "default")
        event = str(data.get("event") or "hb")
        if event not in ("action", "hb"):
            event = "hb"
        if event=='action' and (type(data.get('sequence')) is not int or type(data.get('action_at')) is not int):
            self.send_error(400,'Action sequence and time required');return
        write_state(granted, origin=str(data.get("origin") or "client"),
                    client=client, event=event,sequence=data.get('sequence') if event=='action' else None,
                    action_at=data.get('action_at') if event=='action' else None)
        log(f"POST granted={granted}")
        self.send_response(204)
        self._cors()
        self.end_headers()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args()
    os.makedirs(STATE_DIR, exist_ok=True)
    if not load_token():
        print('Bridge token missing; run the installer first.', file=sys.stderr)
        return 2
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    write_state(False, origin='startup', client='startup', event='action')
    log(f"bridge listening on 127.0.0.1:{args.port}")
    print(f"permission bridge: http://127.0.0.1:{args.port}{ALLOW_ANY_PATH}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
