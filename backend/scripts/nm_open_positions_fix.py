"""Diagnose filled orders without positions; run reconcile + backfill."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal
from app.domain.models import Order, OrderStatus, Position, StrategyKind, Suggestion
from app.services.positions import open_position_from_fill
from app.services.tastytrade_reconcile import reconcile_submitted_tastytrade_orders

db = SessionLocal()
try:
    filled = (
        db.query(Order)
        .filter(Order.status == OrderStatus.filled, Order.strategy_kind == StrategyKind.hv_dip)
        .order_by(Order.updated_at.desc())
        .all()
    )
    print(f"FILLED ORDERS: {len(filled)}")
    for o in filled:
        pos = db.query(Position).filter(Position.order_id == o.id).first()
        print(
            f"  {o.ticker} ord={o.id[:8]} qty={o.quantity} px={o.filled_price} "
            f"pos={'YES' if pos else 'MISSING'}"
        )

    sub = db.query(Order).filter(Order.status == OrderStatus.submitted).all()
    print(f"SUBMITTED (queue): {len(sub)}")
    for o in sub:
        print(f"  {o.ticker} broker_id={o.broker_order_id} qty={o.quantity} limit={o.limit_price}")

    n = reconcile_submitted_tastytrade_orders(db)
    print(f"reconcile updated: {n}")

    backfilled = 0
    for o in filled:
        if db.query(Position).filter(Position.order_id == o.id).first():
            continue
        sug = db.get(Suggestion, o.suggestion_id)
        try:
            open_position_from_fill(db, o, sug)
            backfilled += 1
            print(f"  backfilled position for {o.ticker}")
        except Exception as exc:
            print(f"  backfill FAILED {o.ticker}: {exc}")

    db.commit()
    open_n = (
        db.query(Position)
        .filter(Position.status == "open", Position.strategy_kind == StrategyKind.hv_dip)
        .count()
    )
    print(f"open positions now: {open_n}, backfilled: {backfilled}")
finally:
    db.close()
