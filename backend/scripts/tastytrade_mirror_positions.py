"""Mirror fiidesk open hv_dip positions onto tastytrade sandbox (one-time).

Does NOT change fiidesk cash/positions — only submits missing broker orders.

  cd backend && PYTHONPATH=. python scripts/tastytrade_mirror_positions.py
  cd backend && PYTHONPATH=. python scripts/tastytrade_mirror_positions.py --execute
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

import httpx

from app.config import get_settings
from app.db import SessionLocal
from app.domain.models import InvestmentAccount, Order, Position, PositionStatus, StrategyKind
from app.services.tastytrade_client import TastytradeClient


def _tt_positions(client: TastytradeClient, token: str) -> dict[str, float]:
    acc = (get_settings().tastytrade_account_number or "").strip()
    url = f"{client.base_url}/accounts/{acc}/positions"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    with httpx.Client(timeout=30.0) as http:
        resp = http.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    items = data.get("data", data)
    if isinstance(items, dict):
        items = items.get("items") or []
    out: dict[str, float] = {}
    for row in items or []:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or row.get("underlying-symbol") or "").upper()
        qty = float(row.get("quantity") or row.get("quantity-direction") or 0)
        if sym and qty:
            out[sym] = out.get(sym, 0.0) + qty
    return out


def _already_mirrored(order: Order) -> bool:
    payload = order.execution_payload or {}
    mode = str(payload.get("mode") or "")
    if mode.startswith("tastytrade"):
        return True
    if payload.get("tastytrade_mirror"):
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Mirror open positions to tastytrade")
    parser.add_argument("--execute", action="store_true", help="Submit orders (default: dry-run)")
    parser.add_argument(
        "--bump-pct",
        type=float,
        default=1.5,
        help="Limit price bump above entry for fill odds (default 1.5%%)",
    )
    parser.add_argument("--account-id", default="", help="Optional fiidesk account UUID")
    args = parser.parse_args()

    get_settings.cache_clear()
    client = TastytradeClient()
    if not client.configured():
        print("FAIL: tastytrade env incomplete")
        return 1

    db = SessionLocal()
    try:
        q = db.query(InvestmentAccount).filter(InvestmentAccount.broker_code == "alpaca")
        if args.account_id:
            q = q.filter(InvestmentAccount.id == args.account_id)
        accounts = q.all()
        if not accounts:
            print("No alpaca/NM accounts found")
            return 1

        token = client._ensure_access_token()  # noqa: SLF001
        tt_qty = _tt_positions(client, token)
        print("tastytrade holdings:", tt_qty or "(empty)")

        planned: list[tuple[Position, Order, float, float]] = []
        for acc in accounts:
            positions = (
                db.query(Position)
                .filter(
                    Position.account_id == acc.id,
                    Position.status == PositionStatus.open,
                    Position.strategy_kind == StrategyKind.hv_dip,
                )
                .order_by(Position.opened_at)
                .all()
            )
            print(f"\n{acc.name}: {len(positions)} open hv_dip position(s)")
            for pos in positions:
                order = db.get(Order, pos.order_id)
                if not order:
                    print(f"  SKIP {pos.ticker}: missing order")
                    continue
                if _already_mirrored(order):
                    print(f"  SKIP {pos.ticker} qty={pos.quantity}: already mirrored")
                    continue
                sym = pos.ticker.upper()
                have = tt_qty.get(sym, 0.0)
                need = float(pos.quantity)
                if have >= need - 1e-6:
                    print(f"  SKIP {sym} qty={need}: tastytrade already has {have}")
                    continue
                limit = round(float(pos.entry_price) * (1.0 + args.bump_pct / 100.0), 2)
                cost = round(need * limit, 2)
                planned.append((pos, order, limit, cost))
                print(
                    f"  PLAN {sym} qty={need:.4f} limit={limit:.2f} "
                    f"~cost={cost:.2f} (entry={pos.entry_price:.2f})"
                )

        total = sum(c for *_, c in planned)
        print(f"\nTotal planned debit ~US$ {total:.2f} ({len(planned)} order(s))")
        if not planned:
            print("Nothing to mirror.")
            return 0
        if not args.execute:
            print("\nDry-run only. Re-run with --execute to submit to tastytrade.")
            return 0

        ok = 0
        for pos, order, limit, cost in planned:
            sym = pos.ticker.upper()
            try:
                data = client.submit_equity_limit_buy(
                    symbol=sym,
                    quantity=float(pos.quantity),
                    limit_price=limit,
                )
            except Exception as exc:
                print(f"  FAIL {sym}: {exc}")
                continue
            payload = dict(order.execution_payload or {})
            payload["tastytrade_mirror"] = True
            payload["mirrored_at"] = datetime.now(timezone.utc).isoformat()
            payload["tastytrade"] = data
            order.execution_payload = payload
            order_obj = data.get("data", data)
            if isinstance(order_obj, dict) and "order" in order_obj:
                order_obj = order_obj["order"]
            if isinstance(order_obj, dict):
                broker_id = str(order_obj.get("id") or order_obj.get("order-id") or "")
                if broker_id:
                    order.broker_order_id = broker_id
            ok += 1
            print(f"  OK {sym} qty={pos.quantity:.4f} limit={limit:.2f} broker={order.broker_order_id}")
        db.commit()
        print(f"\nSubmitted {ok}/{len(planned)} mirror order(s).")
        return 0 if ok == len(planned) else 2
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
