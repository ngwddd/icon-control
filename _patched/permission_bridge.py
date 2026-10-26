"""permission_bridge.py — 鼠标授权状态的「程序层」通道（替代 OCR）

为什么需要它：Host 侧原来靠 OCR 读界面上那个胶囊是不是绿的 —— 窗口一挪、一滚、
被遮挡、换分辨率就判不出来（fail closed 会拦掉所有鼠标操作）；更糟的是它还会
读到聊天正文里的「鼠标·已授权」字样而误判成已授权（假阳性，方向最危险）。

现在改成：GUI 上的插件把状态**直接上报**过来，Host 读状态文件即可。

端点（只听 127.0.0.1）
    GET  /beacon?k=<token>&granted=1|0   图片信标（最不容易被 CSP/CORS 拦）
    POST /state?k=<token>                body: {"granted": true|false}
    GET  /state?k=<token>                读当前状态（调试用）

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
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

DEFAULT_PORT = 18765
ALLOW_ANY_PATH = "/state"
BEACON_PATH = "/beacon"

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", "..", ".."))
STATE_DIR = os.path.join(ROOT, "state")
STATE_PATH = os.path.join(STATE_DIR, "mouse-permission.json")
LOG_PATH = os.path.join(STATE_DIR, "bridge.log")
TOKEN_PATH = os.path.join(STATE_DIR, "bridge-token.txt")

_lock = threading.Lock()

# 一旦收到过带 token 的请求，就再也不接受无 token 的请求（自动收紧）
_token_seen = False


def log(line: str) -> None:
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    except Exception:
        pass


def load_token() -> str:
    try:
        with open(TOKEN_PATH, encoding="utf-8") as fh:
            return fh.read().strip()
    except Exception:
        return ""


def write_state(granted: bool, origin: str = "bridge") -> None:
    payload = {
        "granted": bool(granted),
        "source": "bridge",
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "checked_at_ts": time.time(),
        "screen_text": "",
        "origin": origin,
    }
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
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _origin_ok(self) -> bool:
        origin = (self.headers.get("Origin") or "").strip().lower()
        if not origin:
            return True                      # CLI / 原生客户端 / 图片信标
        return (origin.startswith("dsh-app://")
                or origin.startswith("file://")
                or origin.startswith("http://127.0.0.1")
                or origin.startswith("http://localhost"))

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
        for value in (origin, referer):
            if not value:
                continue
            if (value.startswith("dsh-app://")
                    or value.startswith("file://")
                    or value.startswith("http://127.0.0.1")
                    or value.startswith("http://localhost")):
                return True
        return False

    def _authorized(self, parsed) -> bool:
        path = parsed.path
        if path not in (ALLOW_ANY_PATH, BEACON_PATH) and not path.startswith("/s/"):
            log(f"REJECT path={path}")
            return False
        if not self._source_ok():
            log(f"REJECT source path={path} "
                f"origin={self.headers.get('Origin')!r} referer={self.headers.get('Referer')!r}")
            return False
        # 带 token 时校验 token；不带 token 但来源合格也接受
        # （Host 缓存的插件模块在 DSH 重启前不会更新，不能因为没 token 就把用户晾着）
        global _token_seen
        expected = load_token()
        got = (parse_qs(parsed.query).get("k") or [""])[0]
        if expected and got:
            if got != expected:
                log(f"REJECT bad-token path={path}")
                return False
            _token_seen = True          # 客户端已升级：从此只收带 token 的
        elif expected and _token_seen:
            log(f"REJECT missing-token path={path}")
            return False
        return True

    def do_OPTIONS(self):
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
        if parsed.path == BEACON_PATH:
            q = parse_qs(parsed.query)
            granted = (q.get("granted") or ["0"])[0] in ("1", "true", "True")
            write_state(granted, origin="beacon")
            log(f"BEACON granted={granted}")
            self.send_response(204)
            self._cors()
            self.end_headers()
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
            raw = self.rfile.read(n).decode("utf-8", "replace") if n else "{}"
        except Exception:
            raw = "{}"
        try:
            data = json.loads(raw)
        except Exception:
            data = {}
        if "granted" not in data:
            self.send_response(400)
            self._cors()
            self.end_headers()
            return
        granted = bool(data.get("granted"))
        write_state(granted, origin=str(data.get("origin") or "client"))
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
        log("bridge: 没有 token 文件，将以「不校验 token」模式运行（只靠 Origin）")
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    log(f"bridge listening on 127.0.0.1:{args.port}")
    print(f"permission bridge: http://127.0.0.1:{args.port}{BEACON_PATH}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
