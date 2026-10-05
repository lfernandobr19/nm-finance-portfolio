"""Smoke tastytrade OAuth + account reachability."""

from __future__ import annotations

import sys

from app.config import get_settings
from app.services.tastytrade_client import TastytradeClient


def main() -> int:
    get_settings.cache_clear()
    client = TastytradeClient()
    if not client.configured():
        print("FAIL: tastytrade env incomplete (need client id/secret/refresh/account)")
        return 1
    try:
        token = client._ensure_access_token()  # noqa: SLF001
        print(f"OK token ({len(token)} chars) sandbox={client.settings.tastytrade_sandbox}")
        print(f"account={client.settings.tastytrade_account_number}")
        return 0
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
