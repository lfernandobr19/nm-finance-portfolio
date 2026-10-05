"""Reset NM ledger cash to match tastytrade sandbox balance."""
from __future__ import annotations

import argparse
import sys

import httpx

from app.config import get_settings
from app.db import SessionLocal
from app.domain.models import InvestmentAccount
from app.services.tastytrade_client import TastytradeClient


def _tt_cash(client: TastytradeClient) -> float:
    token = client._ensure_access_token()  # noqa: SLF001
    acc = (get_settings().tastytrade_account_number or "").strip()
    url = f"{client.base_url}/accounts/{acc}/balances"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    with httpx.Client(timeout=30.0) as http:
        resp = http.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json().get("data") or {}
    return float(data.get("cash-balance") or 0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cash", type=float, default=0, help="Override cash (0 = read from TT)")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    get_settings.cache_clear()
    client = TastytradeClient()
    target = args.cash if args.cash > 0 else _tt_cash(client)

    db = SessionLocal()
    try:
        acc = (
            db.query(InvestmentAccount)
            .filter(InvestmentAccount.broker_code == "alpaca")
            .first()
        )
        if not acc:
            print("No NM account")
            return 1
        print(f"{acc.name}: cash_usd {acc.cash_usd} -> {target:.2f}")
        print(f"hv_dip_equity_usd {acc.hv_dip_equity_usd} -> {target:.2f}")
        if not args.execute:
            print("Dry-run. Re-run with --execute to apply.")
            return 0
        acc.cash_usd = round(target, 2)
        acc.hv_dip_equity_usd = round(target, 2)
        db.commit()
        print("OK aligned.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
