"""Inspect NVDA submitted tastytrade orders and run reconcile (Phase 1 debug)."""
from __future__ import annotations

from app.config import get_settings
from app.db import SessionLocal
from app.domain.models import InvestmentAccount, Order, OrderStatus, Position, PositionStatus
from app.services.tastytrade_client import TastytradeClient
from app.services.tastytrade_reconcile import reconcile_submitted_tastytrade_orders


def main() -> None:
    get_settings.cache_clear()
    db = SessionLocal()
    try:
        accs = (
            db.query(InvestmentAccount)
            .filter(InvestmentAccount.broker_code == "tastytrade")
            .all()
        )
        for acc in accs:
            print(
                f"\n=== {acc.name} ({acc.id[:8]}...) cash_usd={acc.cash_usd} "
                f"mode={acc.execution_mode} ==="
            )
            orders = (
                db.query(Order)
                .filter(
                    Order.account_id == acc.id,
                    Order.ticker == "NVDA",
                    Order.status.in_(
                        (OrderStatus.submitted, OrderStatus.awaiting_broker, OrderStatus.queued)
                    ),
                )
                .order_by(Order.created_at.asc())
                .all()
            )
            if not orders:
                print("  no NVDA working orders")
            for o in orders:
                print(
                    f"  NVDA {o.side} qty={o.quantity} st={o.status} "
                    f"broker_id={o.broker_order_id} created={o.created_at}"
                )
            pos = (
                db.query(Position)
                .filter(Position.account_id == acc.id, Position.status == PositionStatus.open)
                .order_by(Position.opened_at)
                .all()
            )
            for p in pos:
                print(
                    f"  OPEN {p.ticker:6} qty={p.quantity} entry={p.entry_price} "
                    f"kind={p.strategy_kind}"
                )

        print("\n--- reconcile ---")
        n = reconcile_submitted_tastytrade_orders(db)
        print(f"updated={n}")
        db.expire_all()
        nvda = (
            db.query(Order)
            .filter(Order.ticker == "NVDA")
            .order_by(Order.created_at.desc())
            .limit(8)
            .all()
        )
        for o in nvda:
            print(
                f"  after {o.status} broker_id={o.broker_order_id} "
                f"err={str(o.error_message or '')[:80]}"
            )
    finally:
        db.close()

    client = TastytradeClient()
    if not client.configured():
        print("\n(tastytrade not configured)")
        return
    try:
        print("\n--- probe ---")
        ok = client.probe_account()
        print(f"GET /customers/me/accounts ok={ok} authority={client._authority_level}")
        try:
            live = client.list_live_orders()
        except Exception as exc:
            print(f"\nlive orders failed: {exc}")
            live = None
        if live is not None:
            print(f"\n=== tastytrade live orders n={len(live)} ===")
            for item in live[:20]:
                oid = item.get("id") or item.get("order-id")
                print(f"  {oid} {item.get('status')} {item.get('underlying-symbol') or item.get('symbol')}")
        try:
            from datetime import datetime, timedelta, timezone

            hist = client.list_orders(start_at=datetime.now(timezone.utc) - timedelta(days=2))
            print(f"\n=== tastytrade history n={len(hist)} ===")
            for item in hist[:20]:
                oid = item.get("id") or item.get("order-id")
                print(
                    f"  {oid} {item.get('status')} "
                    f"{item.get('underlying-symbol') or item.get('symbol')} "
                    f"ext={item.get('ext-client-order-id')}"
                )
        except Exception as exc:
            print(f"\nhistory orders failed: {exc}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
