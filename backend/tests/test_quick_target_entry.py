"""Phase 4: Quick Target entry gates — recovery confirmation + equal-risk sizing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.domain.models import AccountCurrency, InvestmentAccount
from app.services.brapi_client import Bar
from app.services.hv_dip.engine import _equal_risk_sizing, build_hv_dip_setup
from app.services.hv_dip.sizing import sizing_basis

START = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _bar(i: int, price: float, volume: float = 3_000_000.0) -> Bar:
    return Bar(
        date=START + timedelta(days=i),
        open=price,
        high=price + 0.5,
        low=price - 0.5,
        close=price,
        volume=volume,
    )


def _account(**kw) -> InvestmentAccount:
    defaults = dict(
        id="acc1",
        name="NM",
        broker_code="tastytrade",
        currency=AccountCurrency.USD,
        cash_usd=1000.0,
        hv_dip_equity_usd=1000.0,
        max_ticket_brl=1000.0,
        hv_dip_cash_floor_pct=20.0,
        hv_dip_max_ticker_pct=80.0,
    )
    defaults.update(kw)
    return InvestmentAccount(**defaults)


# ---- equal-risk sizing ----

def test_equal_risk_qty_scales_with_stop_distance():
    """Wider stop → fewer shares for the same dollar risk budget."""
    acc = _account(cash_usd=1000.0)
    basis = sizing_basis(acc, invested_usd=0.0)  # settled = 1000
    # risk budget = 1% of 1000 = $10
    # 5% stop at $10 → risk/share $0.50 → 20 shares
    assert _equal_risk_sizing(basis, entry=10.0, stop=9.5) == 20
    # 10% stop at $10 → risk/share $1.00 → 10 shares
    assert _equal_risk_sizing(basis, entry=10.0, stop=9.0) == 10
    # stop too far (1 share risk > budget) → 0
    assert _equal_risk_sizing(basis, entry=200.0, stop=100.0) == 0


def test_equal_risk_qty_is_whole_shares():
    acc = _account(cash_usd=1000.0)
    basis = sizing_basis(acc, invested_usd=0.0)
    # $10 budget / $0.25 risk = 40 → integer (floor)
    qty = _equal_risk_sizing(basis, entry=5.0, stop=4.75)
    assert qty == 40
    assert isinstance(qty, int)


# ---- recovery hard gate ----

def test_build_rejects_without_recovery_confirmation():
    """A falling knife (no higher lows / no recovery-in-progress) is rejected."""
    bars = [_bar(i, 100.0 - i) for i in range(90)]  # monotonic decline
    row = build_hv_dip_setup("TEST", bars, min_dip_pct=3.0)
    assert row is None


def test_build_accepts_with_recovery_in_progress():
    """A dip that has bounced off the bottom (higher lows) passes the gate.

    Sub-$20 universe: decline 12 -> 7 (older trough), rally 7 -> 11, then a
    fresh 11 -> 9.5 dip. The recent trough (~9) sits above the older trough
    (~7), so `higher_lows_recent` / `recovery_in_progress` confirm the turn.
    """
    bars: list[Bar] = []
    for i in range(50):  # decline 12 -> 7
        bars.append(_bar(i, 12.0 - 5.0 * (i + 1) / 50))
    for j in range(30):  # rally 7 -> 11
        bars.append(_bar(50 + j, 7.0 + 4.0 * (j + 1) / 30))
    for k in range(10):  # fresh dip 11 -> 9.5
        bars.append(_bar(80 + k, 11.0 - 1.5 * (k + 1) / 10))
    row = build_hv_dip_setup("TEST", bars, min_dip_pct=3.0)
    # The rebound produces higher lows → recovery confirmed → setup emitted.
    assert row is not None
    assert row["recovery_in_progress"] is True
    assert row["higher_lows_recent"] is True


# ---- whole-lot universe (price cap) ----

def test_build_rejects_above_max_price():
    """Names above hv_dip_qt_max_price are excluded (whole-lot universe)."""
    bars = []
    for i in range(90):
        if i < 80:
            price = 80.0
        else:
            price = 80.0 - 0.2 * (i - 79)  # shallow dip
        bars.append(_bar(i, price))
    row = build_hv_dip_setup("TEST", bars, min_dip_pct=1.0)
    assert row is None  # price $80 > max $20
