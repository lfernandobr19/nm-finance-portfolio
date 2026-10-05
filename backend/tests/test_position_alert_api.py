"""Tests that price_alert is exposed on positions API schema."""

from __future__ import annotations

from datetime import datetime, timezone

from app.schemas import PositionOut


def test_pos_out_includes_price_alert_and_pnl_pct():
    out = PositionOut(
        id="p1",
        account_id="a1",
        order_id="o1",
        suggestion_id="s1",
        ticker="MARA",
        strategy_kind="hv_dip",
        quantity=1.0,
        entry_price=10.0,
        stop_price=9.0,
        target_price=12.0,
        status="open",
        opened_at=datetime.now(timezone.utc),
        mark_price=11.0,
        cost_brl=10.0,
        market_value_brl=11.0,
        unrealized_pnl_brl=1.0,
        unrealized_pnl_pct=10.0,
        peak_unrealized_pct=15.0,
        price_alert="trailing",
    )
    assert out.price_alert == "trailing"
    assert out.unrealized_pnl_pct == 10.0
    assert out.peak_unrealized_pct == 15.0
