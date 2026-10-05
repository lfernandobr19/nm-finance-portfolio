"""One-time OAuth login for tastytrade sandbox → prints refresh token.

Uses redirect URI registered on the OAuth app (default http://localhost:8080/callback).
Run: cd backend && PYTHONPATH=. python scripts/tastytrade_oauth_login.py
"""

from __future__ import annotations

import http.server
import os
import threading
import urllib.parse
import webbrowser

import httpx

CLIENT_ID = os.environ.get("TASTYTRADE_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("TASTYTRADE_CLIENT_SECRET", "").strip()
REDIRECT_URI = os.environ.get("TASTYTRADE_REDIRECT_URI", "http://localhost:8080/callback").strip()
SCOPES = os.environ.get("TASTYTRADE_OAUTH_SCOPES", "read trade openid").strip()
TOKEN_URL = "https://api.cert.tastyworks.com/oauth/token"
AUTH_URL = os.environ.get(
    "TASTYTRADE_AUTH_URL", "https://cert-my.staging-tasty.works/auth.html"
).strip()


def main() -> int:
    if not CLIENT_ID or not CLIENT_SECRET:
        print("Set TASTYTRADE_CLIENT_ID and TASTYTRADE_CLIENT_SECRET env vars first.")
        return 1

    code_holder: dict[str, str] = {}
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != urllib.parse.urlparse(REDIRECT_URI).path:
                self.send_response(404)
                self.end_headers()
                return
            qs = urllib.parse.parse_qs(parsed.query)
            code = (qs.get("code") or [""])[0]
            if code:
                code_holder["code"] = code
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h1>OK</h1><p>Volte ao terminal.</p>")
            done.set()

        def log_message(self, fmt: str, *args: object) -> None:
            return

    parsed_redirect = urllib.parse.urlparse(REDIRECT_URI)
    port = parsed_redirect.port or 8080
    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    params = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
        }
    )
    url = f"{AUTH_URL}?{params}"
    print(f"Opening browser: {url}")
    webbrowser.open(url)
    print("Log in with your *sandbox* credentials (cert) and approve the app...")
    done.wait(timeout=300)
    server.shutdown()

    code = code_holder.get("code")
    if not code:
        print("FAIL: no authorization code received (timeout or denied).")
        return 2

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(TOKEN_URL, data=data)
        if resp.status_code >= 400:
            print(f"FAIL token exchange HTTP {resp.status_code}: {resp.text[:400]}")
            return 3
        payload = resp.json()

    refresh = str(payload.get("refresh_token") or "")
    if not refresh:
        print(f"FAIL: no refresh_token in response: {payload}")
        return 4

    print("\n=== TASTYTRADE_REFRESH_TOKEN (save to Ravenna .env) ===")
    print(refresh)
    print("=======================================================\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
