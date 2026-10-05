"""Smoke test for real FCM v1 push.

Sends a test message to one device token and prints the HTTP result so we can
verify end-to-end delivery without waiting for a worker cycle.

Usage:
    .venv/bin/python scripts/_fcm_smoke.py <device_token> [title] [body]
    # or read the token from env:
    FCM_SMOKE_TOKEN=<token> .venv/bin/python scripts/_fcm_smoke.py

Requires FCM_PROJECT_ID + FCM_SERVICE_ACCOUNT_JSON to be set (same as prod).
"""

from __future__ import annotations

import os
import sys

from app.config import get_settings
from app.services.notify import _fcm_access_token, _fcm_send_v1

settings = get_settings()


def main() -> int:
    token = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("FCM_SMOKE_TOKEN", "")
    title = sys.argv[2] if len(sys.argv) > 2 else "NM Finance · smoke"
    body = sys.argv[3] if len(sys.argv) > 3 else "Push FCM v1 funcionando — teste de entrega."

    if not token:
        print("NO_TOKEN: passe o device token como argv[1] ou FCM_SMOKE_TOKEN")
        return 2

    project_id = (settings.fcm_project_id or "").strip()
    service_account = (settings.fcm_service_account_json or "").strip()
    print(f"project_id={project_id!r}")
    print(f"service_account={'set' if service_account else 'MISSING'}")
    if not project_id or not service_account:
        print("NOT_CONFIGURED: defina FCM_PROJECT_ID e FCM_SERVICE_ACCOUNT_JSON no .env")
        return 3

    access_token = _fcm_access_token()
    if not access_token:
        print("NO_ACCESS_TOKEN: service account invalida ou sem escopo firebase.messaging")
        return 4

    ok, err_code = _fcm_send_v1(
        token,
        title,
        body,
        {"kind": "smoke", "account_id": "smoke"},
    )
    if ok:
        print("SENT_OK: mensagem aceita pelo FCM v1")
        return 0
    print(f"SENT_FAIL: error_code={err_code}")
    return 5


if __name__ == "__main__":
    raise SystemExit(main())
