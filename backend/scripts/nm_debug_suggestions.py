"""Debug NM suggestions/orders after approve."""
from app.db import SessionLocal
from app.domain.models import (
    InvestmentAccount,
    Order,
    OrderStatus,
    StrategyKind,
    Suggestion,
    SuggestionStatus,
)

db = SessionLocal()
try:
    acc = (
        db.query(InvestmentAccount)
        .filter(InvestmentAccount.broker_code == "alpaca")
        .first()
    )
    if not acc:
        print("no account")
        raise SystemExit(1)
    print(f"account={acc.name} cash_usd={acc.cash_usd}")

    for label, statuses in [
        ("pending", [SuggestionStatus.pending]),
        ("recent_any", None),
    ]:
        q = db.query(Suggestion).filter(
            Suggestion.account_id == acc.id,
            Suggestion.strategy_kind == StrategyKind.hv_dip,
        )
        if statuses:
            q = q.filter(Suggestion.status.in_(statuses))
        else:
            q = q.order_by(Suggestion.created_at.desc()).limit(8)
        rows = q.all() if statuses else q.all()
        print(f"\n--- {label} ({len(rows)}) ---")
        for s in rows:
            print(
                f"  {s.id[:8]} {s.ticker} status={s.status} score={s.score} "
                f"amt={s.proposed_amount_brl} created={s.created_at}"
            )

    orders = (
        db.query(Order)
        .filter(Order.account_id == acc.id, Order.strategy_kind == StrategyKind.hv_dip)
        .order_by(Order.created_at.desc())
        .limit(5)
        .all()
    )
    print(f"\n--- recent orders ({len(orders)}) ---")
    for o in orders:
        mode = (o.execution_payload or {}).get("mode", "?")
        err = o.error_message or ""
        print(
            f"  {o.id[:8]} {o.ticker} st={o.status} qty={o.quantity:.4f} "
            f"limit={o.limit_price:.2f} mode={mode}"
        )
        if err:
            print(f"    err={err}")
        if o.execution_payload:
            print(f"    payload={o.execution_payload}")
finally:
    db.close()
