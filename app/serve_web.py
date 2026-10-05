"""Serve Flutter web and proxy /api to the NM Finance backend (avoids browser CORS/PNA)."""

from __future__ import annotations

import http.client
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

API_HOST = os.environ.get("FIIDESK_API_HOST", "<RAVENNA_TAILSCALE_IP>")
API_PORT = int(os.environ.get("FIIDESK_API_PORT", "8010"))
LISTEN_PORT = int(os.environ.get("FIIDESK_WEB_PORT", "4173"))
WEB_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build", "web")
PROXY_PREFIXES = ("/api/", "/health", "/docs", "/openapi.json", "/redoc")
LOG_FILE = Path(__file__).resolve().parent / "logs" / "serve_web.log"


def _log(msg: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(msg + "\n")
    except OSError:
        pass


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_ROOT, **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        _log("%s - %s" % (self.address_string(), fmt % args))

    def _is_proxy(self) -> bool:
        return self.path == "/health" or self.path.startswith(PROXY_PREFIXES)

    def do_OPTIONS(self) -> None:
        if self._is_proxy():
            self._proxy()
            return
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        if self._is_proxy():
            self._proxy()
            return
        super().do_GET()

    def do_POST(self) -> None:
        if self._is_proxy():
            self._proxy()
            return
        self.send_error(405)

    def do_PUT(self) -> None:
        if self._is_proxy():
            self._proxy()
            return
        self.send_error(405)

    def do_PATCH(self) -> None:
        if self._is_proxy():
            self._proxy()
            return
        self.send_error(405)

    def do_DELETE(self) -> None:
        if self._is_proxy():
            self._proxy()
            return
        self.send_error(405)

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")

    def _proxy(self) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path
        if parsed.query:
            path = f"{path}?{parsed.query}"
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(length) if length > 0 else None
        headers = {
            k: v
            for k, v in self.headers.items()
            if k.lower() not in {"host", "content-length", "connection", "transfer-encoding"}
        }
        try:
            conn = http.client.HTTPConnection(API_HOST, API_PORT, timeout=60)
            conn.request(self.command, path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            self.send_response(resp.status)
            for key, val in resp.getheaders():
                if key.lower() in {
                    "transfer-encoding",
                    "connection",
                    "content-encoding",
                    "content-length",
                }:
                    continue
                self.send_header(key, val)
            self.send_header("Content-Length", str(len(data)))
            self._cors()
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)
            conn.close()
        except Exception as exc:
            _log(f"proxy error: {exc}")
            self.send_error(502, f"Upstream error: {exc}")


def main() -> None:
    if not os.path.isdir(WEB_ROOT):
        _log(f"missing web build at {WEB_ROOT}")
        print(f"Missing web build at {WEB_ROOT}. Run: flutter build web", file=sys.stderr)
        sys.exit(1)
    server = ThreadingHTTPServer(("127.0.0.1", LISTEN_PORT), Handler)
    _log(f"NM Finance web on http://127.0.0.1:{LISTEN_PORT} (proxy -> {API_HOST}:{API_PORT})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
