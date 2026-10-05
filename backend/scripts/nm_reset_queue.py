"""One-shot reset: expire pending hv_dip suggestions + cancel submitted orders on tastytrade."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal
from app.domain.models import (
    InvestmentAccount,
    Order,
    OrderStatus,
    StrategyKind,
    Suggestion,
    SuggestionStatus,
)
from app.services.broker import get_broker_adapter

RESET_REASON = "manual_reset_pre_live_suggestions"
ORDER_NOTE = "reset manual M1.1"


def reset_queue(*, dry_run: bool = False) -> dict[str, int]:
    db = SessionLocal()
    stats = {"expired": 0, "cancelled": 0, "cancel_errors": 0}
    try:
        pending = (
            db.query(Suggestion)
            .filter(
                Suggestion.strategy_kind == StrategyKind.hv_dip,
                Suggestion.status == SuggestionStatus.pending,
            )
            .all()
        )
        for sug in pending:
            metrics = dict(sug.metrics or {})
            metrics["invalidated_reason"] = RESET_REASON
            sug.metrics = metrics
            sug.status = SuggestionStatus.expired
            stats["expired"] += 1
            print(f"expire pending {sug.ticker} id={sug.id[:8]}")

        waiting = (
            db.query(Order)
            .filter(
                Order.strategy_kind == StrategyKind.hv_dip,
                Order.status.in_(
                    [
                        OrderStatus.submitted,
                        OrderStatus.queued,
                        OrderStatus.awaiting_broker,
                    ]
                ),
            )
            .all()
        )
        for order in waiting:
            print(
                f"cancel {order.ticker} st={order.status} broker_id={order.broker_order_id}"
            )
            if dry_run:
                stats["cancelled"] += 1
                continue
            account = db.get(InvestmentAccount, order.account_id)
            adapter = get_broker_adapter(account) if account else None
            if adapter and order.broker_order_id:
                result = adapter.cancel_order(order)
                if result.error_message and result.status != OrderStatus.cancelled:
                    stats["cancel_errors"] += 1
                    print(f"  WARN cancel: {result.error_message[:200]}")
            order.status = OrderStatus.cancelled
            order.error_message = ORDER_NOTE
            payload = dict(order.execution_payload or {})
            payload["manual_reset_at"] = datetime.now(timezone.utc).isoformat()
            order.execution_payload = payload
            stats["cancelled"] += 1

        if dry_run:
            db.rollback()
            print("DRY RUN — no changes committed")
        else:
            db.commit()
            print("Committed.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="NM queue reset (Fase 0)")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    args = parser.parse_args()
    stats = reset_queue(dry_run=args.dry_run)
    print(
        f"Done: expired={stats['expired']} cancelled={stats['cancelled']} "
        f"errors={stats['cancel_errors']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
