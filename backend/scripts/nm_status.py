"""Post close-all status for NM account."""
from app.db import SessionLocal
from app.domain.models import (
    InvestmentAccount,
    Position,
    PositionStatus,
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
        print("no alpaca account")
        raise SystemExit(1)
    closed = (
        db.query(Position)
        .filter(
            Position.account_id == acc.id,
            Position.status == PositionStatus.closed,
            Position.strategy_kind == StrategyKind.hv_dip,
        )
        .all()
    )
    pnl = sum(float(p.realized_pnl_brl or 0) for p in closed)
    pending = (
        db.query(Suggestion)
        .filter(
            Suggestion.account_id == acc.id,
            Suggestion.strategy_kind == StrategyKind.hv_dip,
            Suggestion.status == SuggestionStatus.pending,
        )
        .count()
    )
    open_n = (
        db.query(Position)
        .filter(
            Position.account_id == acc.id,
            Position.status == PositionStatus.open,
            Position.strategy_kind == StrategyKind.hv_dip,
        )
        .count()
    )
    print(f"account={acc.name}")
    print(f"cash_usd={acc.cash_usd}")
    print(f"open_hv_dip={open_n}")
    print(f"closed_hv_dip={len(closed)}")
    print(f"realized_pnl_total={round(pnl, 2)}")
    print(f"pending_suggestions={pending}")
    print(f"hv_dip_max_positions={acc.hv_dip_max_positions}")
finally:
    db.close()
