"""M0 aceite smoke: Yahoo OHLC + hv_dip cycle (no Alpaca keys required)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal
from app.services.market_data import MarketDataClient
from app.services.hv_dip import run_hv_dip_cycle


def main() -> None:
    client = MarketDataClient()
    bars = client.fetch_daily_bars("TSLA", force=True)
    print(
        "yahoo/alpaca bars",
        len(bars),
        "last_close",
        round(bars[-1].close, 2) if bars else None,
    )

    from app.domain.models import InvestmentAccount, Suggestion, StrategyKind, SuggestionStatus
    from app.services.hv_dip.engine import analyze_ticker
    from app.services.hv_dip.universe import hv_dip_tickers

    hits = []
    for ticker in hv_dip_tickers():
        row = analyze_ticker(ticker, client)
        if row:
            hits.append((ticker, row["dip_pct"], row["scored"].letter))
    print("all_candidates", len(hits), hits[:8])

    db = SessionLocal()
    try:
        accs = db.query(InvestmentAccount).all()
        print("accounts", len(accs))
        for a in accs:
            print(
                "account",
                a.id,
                a.name,
                a.broker_code,
                getattr(a, "currency", None),
                getattr(a, "cash_usd", None),
            )

        pending = (
            db.query(Suggestion)
            .filter(
                Suggestion.account_id == "7fa92732-d890-41ba-ac47-13e4e5b3e67f",
                Suggestion.strategy_kind == StrategyKind.hv_dip,
                Suggestion.status == SuggestionStatus.pending,
            )
            .all()
        )
        print("pending_hv_dip", len(pending), [p.ticker for p in pending])

        created = run_hv_dip_cycle(db)
        db.commit()
        print("hv_dip_created", len(created))
        for s in created[:10]:
            print("suggestion", s.id, s.ticker, s.status)

        if not pending:
            pending = (
                db.query(Suggestion)
                .filter(
                    Suggestion.account_id == "7fa92732-d890-41ba-ac47-13e4e5b3e67f",
                    Suggestion.strategy_kind == StrategyKind.hv_dip,
                    Suggestion.status == SuggestionStatus.pending,
                )
                .all()
            )
        if pending:
            from app.domain.models import AccountMembership, Order, OrderStatus, SuggestionStatus as SS
            from app.services.orders import create_order_from_suggestion

            s = pending[0]
            mem = (
                db.query(AccountMembership)
                .filter(AccountMembership.account_id == s.account_id)
                .first()
            )
            user_id = mem.user_id if mem else None
            cash_before = float(getattr(db.get(InvestmentAccount, s.account_id), "cash_usd", 0) or 0)
            order = create_order_from_suggestion(
                db, s, acted_by_user_id=user_id, human_approved=True
            )
            s.status = SS.approved
            db.commit()
            db.refresh(order)
            acc = db.get(InvestmentAccount, s.account_id)
            cash_after = float(getattr(acc, "cash_usd", 0) or 0)
            mode = (order.execution_payload or {}).get("mode")
            print(
                "approve_smoke",
                s.ticker,
                order.status,
                order.broker_order_id,
                mode,
                "cash",
                cash_before,
                "->",
                cash_after,
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
