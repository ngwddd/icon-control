"""permission_bridge.py — 鼠标授权状态的「程序层」通道（替代 OCR）

为什么需要它：原来 Host 侧靠 OCR 读界面上那个胶囊是不是绿的 —— 窗口一挪、
一滚、被遮挡、分辨率变了就判不出来（fail closed 会拦掉所有鼠标操作）。

现在改成：GUI 上的插件把状态**直接 POST 过来**，Host 读文件即可。
OCR 只保留为后备（桥没起来 / 心跳过期时）。

协议（只听 127.0.0.1）
    POST /state              body: {"granted": true|false}   （text/plain 或 json）
    GET  /state              →  当前状态 JSON

安全
    · 只 bind 127.0.0.1，不对外
    · 校验 Origin：只接受 dsh-app:// / file:// / 127.0.0.1 / localhost，普通网页发不进来
    · 它只写一个 JSON 状态文件，不执行任何命令
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ALLOW_ANY_PATH = "/state"   # 不设 token：见下面的 Origin 校验
PORT = 18765

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(ROOT, "state")
STATE_PATH = os.path.join(STATE_DIR, "mouse-permission.json")
LOG_PATH = os.path.join(STATE_DIR, "bridge.log")

_lock = threading.Lock()


def log(line: str) -> None:
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    except Exception:
        pass


def write_state(granted: bool, origin: str = "bridge") -> None:
    now = time.time()
    payload = {
        "granted": bool(granted),
        "source": "bridge",
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "checked_at_ts": now,
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
    server_version = "dsh-permission-bridge/1.0"

    def log_message(self, fmt, *args):      # 静音默认访问日志
        return

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _authorized(self) -> bool:
        """只认 DSH 自己的页面（或本机原生客户端）。

        为什么不用 token：写死在源码里 → 发布到开源仓库等于公开；
        写进单独文件 → 浏览器读不到文件。而 Origin 由浏览器设置、普通网页改不了，
        所以「Origin 白名单 + 只听 127.0.0.1」在浏览器场景比 token 更硬；
        非浏览器客户端本来就能读本地文件，加 token 也没收益。
        """
        if self.path.split("?")[0] != ALLOW_ANY_PATH:
            return False
        origin = (self.headers.get("Origin") or "").strip().lower()
        if not origin:
            return True                      # CLI / 原生客户端
        return (origin.startswith("dsh-app://")
                or origin.startswith("file://")
                or origin.startswith("http://127.0.0.1")
                or origin.startswith("http://localhost"))


    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if not self._authorized():
            self.send_response(403); self.end_headers(); return
        body = json.dumps(read_state(), ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self._authorized():
            self.send_response(403); self.end_headers(); return
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
            self.send_response(400); self._cors(); self.end_headers(); return
        granted = bool(data.get("granted"))
        write_state(granted, origin=str(data.get("origin") or "client"))
        log(f"POST granted={granted} raw={raw[:120]!r}")
        self.send_response(204)
        self._cors()
        self.end_headers()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args()
    os.makedirs(STATE_DIR, exist_ok=True)
    log(f"bridge listening on 127.0.0.1:{args.port}")
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"permission bridge: http://127.0.0.1:{args.port}/state", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
