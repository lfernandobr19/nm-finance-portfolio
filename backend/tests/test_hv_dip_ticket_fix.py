"""Regression tests for max_ticket order-value semantics (not per-share price)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.domain.models import (
    AccountCurrency,
    AssetClass,
    DividendFrequency,
    InvestmentAccount,
    StrategyKind,
    Suggestion,
    SuggestionStatus,
)
from app.services.approve_options import _max_amount_usd
from app.services.hv_dip.sizing import sizing_basis


def _account(**kw) -> InvestmentAccount:
    defaults = dict(
        id="acc1",
        name="NM",
        broker_code="tastytrade",
        currency=AccountCurrency.USD,
        cash_usd=1000.0,
        hv_dip_equity_usd=1000.0,
        max_ticket_brl=1000.0,
        hv_dip_cash_floor_pct=30.0,
        hv_dip_max_ticker_pct=80.0,
    )
    defaults.update(kw)
    return InvestmentAccount(**defaults)


def _suggestion(**kw) -> Suggestion:
    defaults = dict(
        id="s1",
        account_id="acc1",
        ticker="TSLA",
        strategy_kind=StrategyKind.hv_dip,
        asset_class=AssetClass.us_equity,
        dividend_frequency=DividendFrequency.other,
        score=70,
        swing_score_letter="B",
        entry_price=300.0,
        stop_price=290.0,
        target_price=320.0,
        status=SuggestionStatus.pending,
        reasons=[],
        metrics={"price": 300.0},
        price_explanation="",
        rule_version=1,
        proposed_amount_brl=6.56,
        expires_at=None,
    )
    defaults.update(kw)
    return Suggestion(**defaults)


def _basis(acc: InvestmentAccount, invested: float = 0.0):
    return sizing_basis(acc, invested_usd=invested)


def test_max_amount_usd_not_capped_by_proposed_tranche(monkeypatch):
    """max_ticket_brl is the order-value ceiling; proposed_amount_brl is NOT."""
    monkeypatch.setattr(
        "app.services.approve_options.deployed_on_ticker_usd",
        lambda *a, **k: 0.0,
    )
    monkeypatch.setattr(
        "app.services.hv_dip.sizing.invested_usd",
        lambda *a, **k: 0.0,
    )
    db = MagicMock()
    # cash 5000, ticket 500, but proposed tranche only 6.56 → ceiling must be 500.
    acc = _account(cash_usd=5000.0, hv_dip_equity_usd=5000.0, max_ticket_brl=500.0)
    sug = _suggestion(proposed_amount_brl=6.56)
    assert _max_amount_usd(db, acc, sug) == pytest.approx(500.0, abs=0.01)


def test_max_amount_usd_covers_one_expensive_share(monkeypatch):
    """With cash available, max amount must cover 1 share of an expensive ticker."""
    monkeypatch.setattr(
        "app.services.approve_options.deployed_on_ticker_usd",
        lambda *a, **k: 0.0,
    )
    monkeypatch.setattr(
        "app.services.hv_dip.sizing.invested_usd",
        lambda *a, **k: 0.0,
    )
    db = MagicMock()
    acc = _account(cash_usd=1000.0, hv_dip_equity_usd=1000.0, max_ticket_brl=1000.0)
    sug = _suggestion(ticker="AMZN", entry_price=31.82, proposed_amount_brl=6.56)
    assert _max_amount_usd(db, acc, sug) >= 31.82


def test_sizing_basis_cash_below_stale_equity_ref():
    """The bug that pinned the floor to hv_dip_equity_usd=100 when cash was 28.24.

    Old behaviour: equity_ref = max(28.24, 100) = 100 → floor 20% = 20 →
    spendable B = 8.24. New behaviour: equity = cash (+ invested) = 28.24 →
    floor 20% = 5.65 → deployable B = 22.59.
    """
    acc = _account(
        cash_usd=28.24,
        hv_dip_equity_usd=100.0,
        max_ticket_brl=1000.0,
        hv_dip_cash_floor_pct=20.0,
    )
    basis = _basis(acc, invested=0.0)
    assert basis.equity == pytest.approx(28.24, abs=0.01)
    assert basis.floor_cash == pytest.approx(5.648, abs=0.01)
    assert basis.deployable == pytest.approx(22.592, abs=0.01)
