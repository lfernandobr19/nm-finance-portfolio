"""Tests for hv_dip approve amount options."""

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
from app.services.approve_options import build_approve_options, validate_approve_amount


def _account(**kw) -> InvestmentAccount:
    defaults = dict(
        id="acc1",
        name="NM",
        broker_code="tastytrade",
        currency=AccountCurrency.USD,
        cash_usd=50.0,
        hv_dip_equity_usd=50.0,
        max_ticket_brl=12.0,
        hv_dip_cash_floor_pct=30.0,
        hv_dip_max_ticker_pct=80.0,
    )
    defaults.update(kw)
    return InvestmentAccount(**defaults)


def _suggestion(**kw) -> Suggestion:
    defaults = dict(
        id="s1",
        account_id="acc1",
        ticker="LCID",
        strategy_kind=StrategyKind.hv_dip,
        asset_class=AssetClass.us_equity,
        dividend_frequency=DividendFrequency.other,
        score=70,
        swing_score_letter="B",
        entry_price=5.0,
        stop_price=4.5,
        target_price=6.0,
        status=SuggestionStatus.pending,
        reasons=[],
        metrics={"price": 5.0},
        price_explanation="",
        rule_version=1,
        proposed_amount_brl=10.0,
        expires_at=None,
    )
    defaults.update(kw)
    return Suggestion(**defaults)


def test_build_approve_options_fractional(monkeypatch):
    monkeypatch.setattr(
        "app.services.approve_options._hv_dip_live_price",
        lambda s: (5.0, "test"),
    )
    monkeypatch.setattr(
        "app.services.approve_options.is_fractional_blocked",
        lambda t: False,
    )
    monkeypatch.setattr(
        "app.services.approve_options._amount_allowed",
        lambda db, account, suggestion, amount: True,
    )
    db = MagicMock()
    opts = build_approve_options(db, _account(), _suggestion())
    assert opts["fractional_allowed"] is True
    assert opts["approvable"] is True
    assert opts["max_amount_usd"] >= 10.0


def test_build_approve_options_whole_share_only(monkeypatch):
    monkeypatch.setattr(
        "app.services.approve_options._hv_dip_live_price",
        lambda s: (43.0, "test"),
    )
    monkeypatch.setattr(
        "app.services.approve_options.is_fractional_blocked",
        lambda t: True,
    )
    monkeypatch.setattr(
        "app.services.approve_options._amount_allowed",
        lambda db, account, suggestion, amount: amount <= 50.0,
    )
    monkeypatch.setattr(
        "app.services.approve_options._max_amount_usd",
        lambda db, account, suggestion: 50.0,
    )
    db = MagicMock()
    opts = build_approve_options(
        db,
        _account(max_ticket_brl=50.0),
        _suggestion(ticker="U", proposed_amount_brl=50.0),
    )
    assert opts["fractional_allowed"] is False
    assert opts["approvable"] is True
    assert all(o["mode"] == "limit_live" for o in opts["options"])
    assert opts["options"][0]["quantity"] == 1.0


def test_build_approve_options_empty_when_unaffordable(monkeypatch):
    monkeypatch.setattr(
        "app.services.approve_options._hv_dip_live_price",
        lambda s: (43.0, "test"),
    )
    monkeypatch.setattr(
        "app.services.approve_options.is_fractional_blocked",
        lambda t: True,
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []
    opts = build_approve_options(db, _account(max_ticket_brl=11.0), _suggestion(ticker="AMD"))
    assert opts["approvable"] is False
    assert opts["options"] == []
    assert "fractional" in (opts["block_reason"] or "").lower()


def test_validate_fractional_free_amount(monkeypatch):
    monkeypatch.setattr(
        "app.services.approve_options.build_approve_options",
        lambda db, acc, sug: {
            "approvable": True,
            "block_reason": None,
            "fractional_allowed": True,
            "max_amount_usd": 12.0,
            "options": [],
        },
    )
    monkeypatch.setattr(
        "app.services.approve_options.assert_hv_dip_guards",
        lambda *a, **k: None,
    )
    db = MagicMock()
    validate_approve_amount(db, _account(), _suggestion(), 8.5)


def test_validate_rejects_invalid_whole_share(monkeypatch):
    monkeypatch.setattr(
        "app.services.approve_options.build_approve_options",
        lambda db, acc, sug: {
            "approvable": True,
            "block_reason": None,
            "fractional_allowed": False,
            "max_amount_usd": 50.0,
            "options": [{"amount_usd": 43.0, "quantity": 1.0, "label": "1", "mode": "limit_live"}],
        },
    )
    db = MagicMock()
    with pytest.raises(ValueError, match="não permitido"):
        validate_approve_amount(db, _account(), _suggestion(ticker="U"), 44.0)
