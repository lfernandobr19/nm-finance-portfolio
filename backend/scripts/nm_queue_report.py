"""Report approved suggestions vs queue/rejected orders."""
from app.db import SessionLocal
from app.domain.models import (
    InvestmentAccount,
    Order,
    OrderStatus,
    StrategyKind,
    Suggestion,
    SuggestionStatus,
)
from sqlalchemy import desc


def main() -> None:
    db = SessionLocal()
    try:
        acc = (
            db.query(InvestmentAccount)
            .filter(InvestmentAccount.broker_code == "alpaca")
            .first()
        )
        if not acc:
            print("no account")
            return
        print(f"account={acc.name} cash_usd={acc.cash_usd}")

        approved = (
            db.query(Suggestion)
            .filter(
                Suggestion.account_id == acc.id,
                Suggestion.strategy_kind == StrategyKind.hv_dip,
                Suggestion.status == SuggestionStatus.approved,
            )
            .order_by(desc(Suggestion.acted_at))
            .all()
        )
        print(f"\nAPPROVED ({len(approved)}):")
        for s in approved:
            orders = (
                db.query(Order)
                .filter(Order.suggestion_id == s.id)
                .order_by(desc(Order.created_at))
                .all()
            )
            print(f"  {s.ticker} amt={s.proposed_amount_brl} sug={s.id[:8]}")
            if not orders:
                print("    NO ORDER")
            for o in orders:
                err = (o.error_message or "")[:160]
                print(f"    ord={o.id[:8]} st={o.status} qty={o.quantity} err={err}")

        waiting = (
            db.query(Order)
            .filter(
                Order.account_id == acc.id,
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
        print(f"\nIN QUEUE ({len(waiting)}):")
        for o in waiting:
            print(f"  {o.ticker} st={o.status} qty={o.quantity} id={o.broker_order_id}")

        rejected = (
            db.query(Order)
            .filter(
                Order.account_id == acc.id,
                Order.strategy_kind == StrategyKind.hv_dip,
                Order.status == OrderStatus.rejected,
            )
            .order_by(desc(Order.created_at))
            .limit(15)
            .all()
        )
        print(f"\nREJECTED ({len(rejected)}):")
        for o in rejected:
            err = (o.error_message or "")[:160]
            print(f"  {o.ticker} qty={o.quantity} err={err}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
