"""Retry failed tastytrade orders + run hv_dip cycle for new pending."""
from __future__ import annotations

import sys

from app.db import SessionLocal
from app.domain.models import (
    InvestmentAccount,
    Order,
    OrderStatus,
    Position,
    PositionStatus,
    StrategyKind,
    Suggestion,
    SuggestionStatus,
)
from app.services.hv_dip.engine import run_hv_dip_cycle
from app.services.orders import create_order_from_suggestion


def main() -> int:
    db = SessionLocal()
    try:
        created = run_hv_dip_cycle(db)
        db.commit()
        print(f"hv_dip_created={len(created)}")
        for s in created[:5]:
            print(f"  NEW {s.ticker} score={s.score} amt={s.proposed_amount_brl}")

        acc = (
            db.query(InvestmentAccount)
            .filter(InvestmentAccount.broker_code == "alpaca")
            .first()
        )
        if not acc:
            return 1

        pending = (
            db.query(Suggestion)
            .filter(
                Suggestion.account_id == acc.id,
                Suggestion.strategy_kind == StrategyKind.hv_dip,
                Suggestion.status == SuggestionStatus.pending,
            )
            .order_by(Suggestion.score.desc())
            .all()
        )
        print(f"\npending={len(pending)}")
        for s in pending[:5]:
            print(f"  {s.ticker} score={s.score} amt={s.proposed_amount_brl}")

        # Retry approved suggestions without open position (failed broker)
        approved = (
            db.query(Suggestion)
            .filter(
                Suggestion.account_id == acc.id,
                Suggestion.strategy_kind == StrategyKind.hv_dip,
                Suggestion.status == SuggestionStatus.approved,
            )
            .order_by(Suggestion.created_at.desc())
            .limit(10)
            .all()
        )
        for sug in approved:
            open_pos = (
                db.query(Position)
                .filter(
                    Position.suggestion_id == sug.id,
                    Position.status == PositionStatus.open,
                )
                .count()
            )
            if open_pos:
                continue
            last = (
                db.query(Order)
                .filter(Order.suggestion_id == sug.id)
                .order_by(Order.created_at.desc())
                .first()
            )
            if last and last.status not in (OrderStatus.rejected,):
                continue
            print(f"\nRETRY {sug.ticker} suggestion={sug.id[:8]}")
            order = create_order_from_suggestion(
                db, sug, human_approved=True, acted_by_user_id=None
            )
            db.commit()
            mode = (order.execution_payload or {}).get("mode")
            print(
                f"  order={order.id[:8]} status={order.status} qty={order.quantity} "
                f"mode={mode} err={order.error_message or ''}"
            )

        return 0
    except Exception as exc:
        db.rollback()
        print(f"FAIL: {exc}")
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
