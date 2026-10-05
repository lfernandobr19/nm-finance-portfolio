"""Phase 1: T+2 settlement ledger + anti-GFV invariants."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.domain.models import (
    AccountCurrency,
    InvestmentAccount,
    Position,
    PositionExitReason,
    PositionStatus,
)
from app.services.hv_dip.settlement import (
    next_settlement_date,
    reserve_proceeds,
    settle_due,
    settled_usd,
)
from app.services.hv_dip.sizing import sizing_basis
from app.services.positions import close_position


def _account(**kw) -> InvestmentAccount:
    defaults = dict(
        id="acc1",
        name="NM USD Paper",
        owner_user_id="u1",
        broker_code="tastytrade",
        currency=AccountCurrency.USD,
        cash_usd=100.0,
        hv_dip_equity_usd=100.0,
        max_ticket_brl=100.0,
        hv_dip_cash_floor_pct=20.0,
        hv_dip_max_ticker_pct=80.0,
    )
    defaults.update(kw)
    return InvestmentAccount(**defaults)


def _position(acc_id: str = "acc1", *, opened_at: datetime) -> Position:
    return Position(
        id="p1",
        account_id=acc_id,
        order_id="o1",
        suggestion_id="s1",
        ticker="LCID",
        strategy_kind="hv_dip",
        quantity=10.0,
        entry_price=5.0,
        stop_price=4.5,
        target_price=6.0,
        status=PositionStatus.open,
        opened_at=opened_at,
    )


# --- settlement helpers -----------------------------------------------------

def test_settled_usd_subtracts_unsettled():
    acc = _account(cash_usd=100.0, unsettled_cash_usd=40.0)
    assert settled_usd(acc) == 60.0


def test_settled_usd_never_negative():
    acc = _account(cash_usd=10.0, unsettled_cash_usd=40.0)
    assert settled_usd(acc) == 0.0


def test_next_settlement_skips_weekend():
    # Friday -> +2 business days = Tuesday (skips Sat/Sun).
    fri = date(2026, 9, 4)  # a Friday
    assert next_settlement_date(fri, days=2) == date(2026, 9, 8)


def test_reserve_proceeds_sets_ledger():
    acc = _account()
    reserve_proceeds(acc, 25.0, days=2, today=date(2026, 9, 7))  # Monday
    assert acc.unsettled_cash_usd == 25.0
    assert acc.unsettled_until == date(2026, 9, 9)  # Wednesday


def test_settle_due_releases_after_date():
    acc = _account(unsettled_cash_usd=25.0, unsettled_until=date(2026, 9, 9))
    assert settle_due(acc, today=date(2026, 9, 8)) == 0.0  # not yet
    assert acc.unsettled_cash_usd == 25.0
    released = settle_due(acc, today=date(2026, 9, 9))
    assert released == 25.0
    assert acc.unsettled_cash_usd == 0.0
    assert acc.unsettled_until is None


# --- sizing uses settled cash ----------------------------------------------

def test_sizing_basis_deployable_uses_settled_not_gross():
    # $100 gross, $60 unsettled → only $40 settled is deployable above floor.
    # (Floor 20% of $100 equity = $20, so deployable = $40 settled - $20 = $20;
    #  gross cash would give $80 — proving deployable is settled-cash-aware.)
    acc = _account(cash_usd=100.0, unsettled_cash_usd=60.0, hv_dip_cash_floor_pct=20.0)
    basis = sizing_basis(acc, invested_usd=0.0)
    assert basis.settled == 40.0
    assert basis.deployable == pytest.approx(20.0)
    # A setup may dip into the floor but still only up to settled cash.
    assert basis.spendable("A") == pytest.approx(40.0)


def test_sizing_basis_deployable_above_floor():
    acc = _account(cash_usd=100.0, unsettled_cash_usd=0.0, hv_dip_cash_floor_pct=20.0)
    basis = sizing_basis(acc, invested_usd=0.0)
    assert basis.deployable == pytest.approx(80.0)


# --- anti-GFV + reserve on close -------------------------------------------

def test_close_position_gfv_blocks_same_day():
    db = MagicMock()
    acc = _account()
    db.get.return_value = acc
    pos = _position(opened_at=datetime.now(timezone.utc))
    with pytest.raises(ValueError, match="GFV"):
        close_position(db, pos, reason=PositionExitReason.manual, manual_price=5.5)


def test_close_position_reserves_proceeds():
    db = MagicMock()
    acc = _account(cash_usd=100.0)
    db.get.return_value = acc
    pos = _position(opened_at=datetime.now(timezone.utc) - timedelta(days=3))
    closed = close_position(
        db, pos, reason=PositionExitReason.manual, manual_price=5.5
    )
    proceeds = round(10.0 * 5.5, 2)
    assert closed.status == PositionStatus.closed
    # Cash credited AND proceeds reserved as unsettled (T+2).
    assert acc.cash_usd == pytest.approx(100.0 + proceeds)
    assert acc.unsettled_cash_usd == pytest.approx(proceeds)
    assert acc.unsettled_until is not None
