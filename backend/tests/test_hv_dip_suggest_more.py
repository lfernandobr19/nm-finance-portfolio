"""Tests for hv_dip "comprar mais" (suggest_more_for_ticker) and the raised tranche cap."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.domain.models import AccountCurrency, InvestmentAccount
from app.services.hv_dip.engine import suggest_more_for_ticker


def _account(**kw) -> InvestmentAccount:
    defaults = dict(
        id="a1",
        name="NM",
        broker_code="tastytrade",
        currency=AccountCurrency.USD,
        cash_usd=100.0,
        hv_dip_equity_usd=100.0,
        max_ticket_brl=1000.0,
        hv_dip_cash_floor_pct=20.0,
        hv_dip_max_ticker_pct=80.0,
    )
    defaults.update(kw)
    return InvestmentAccount(**defaults)


def _db(open_rows):
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = open_rows
    db.add = MagicMock()
    db.flush = MagicMock()
    db.commit = MagicMock()
    return db


def _row() -> dict:
    scored = MagicMock(letter="B", numeric_score=80, r_multiple=2.0, reasons=[])
    return {
        "ticker": "LCID",
        "entry": 10.0,
        "scored": scored,
        "stop": 9.0,
        "target": 12.0,
        "setup_low": 8.5,
        "dip_pct": 20.0,
        "review_required": False,
        "review_reason": None,
        "atr_pct": 4.0,
        "volume_ratio": 1.2,
    }


def _position(tranche):
    p = MagicMock()
    p.tranche_index = tranche
    return p


def _patch(monkeypatch):
    monkeypatch.setattr("app.services.hv_dip.engine._pending_hv", lambda db, aid, t: False)
    monkeypatch.setattr("app.services.hv_dip.engine.settings.hv_dip_max_tranches", 5)
    monkeypatch.setattr(
        "app.services.hv_dip.engine.deployed_on_ticker_usd",
        lambda db, aid, t: 0.0,
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.account_sizing_basis",
        lambda db, account: __import__(
            "app.services.hv_dip.sizing", fromlist=["sizing_basis"]
        ).sizing_basis(account, invested_usd=0.0),
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.active_thresholds",
        lambda db: {
            "min_dip_pct": 12.0,
            "min_recovery_rate": 0.6,
            "reject_fresh_high": True,
        },
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.create_order_from_suggestion",
        lambda db, s, acted_by_user_id=None: MagicMock(),
    )
    from app.services.desk_gate import GateVerdict

    monkeypatch.setattr(
        "app.services.desk_gate.apply_intent",
        lambda db, intent, **k: GateVerdict(
            allow=False, queued=True, reason="queued", enforce=True
        ),
    )
    monkeypatch.setattr("app.services.hv_dip.engine.notify_suggestion", lambda db, s: None)
    monkeypatch.setattr(
        "app.services.market_data.MarketDataClient.fetch_daily_bars", lambda self, t: []
    )
    monkeypatch.setattr(
        "app.services.market_data.MarketDataClient.fetch_last_prices",
        lambda self, ts: {"LCID": 10.0},
    )


def test_suggest_more_uses_next_tranche(monkeypatch):
    """Holding tranche 3 → "comprar mais" emits tranche 4 (cap raised to 5)."""
    _patch(monkeypatch)
    monkeypatch.setattr(
        "app.services.hv_dip.engine.build_hv_dip_setup",
        lambda t, bars, last_price=None, **kw: _row(),
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine._apply_catalysts",
        lambda db, candidates, bars_map: None,
    )
    sug = suggest_more_for_ticker(_db([_position(3)]), _account(), "LCID")
    assert sug.tranche_index == 4
    assert sug.ticker == "LCID"


def test_suggest_more_hits_cap(monkeypatch):
    """At the cap (5) → next tranche (6) is rejected."""
    _patch(monkeypatch)
    with pytest.raises(ValueError):
        suggest_more_for_ticker(_db([_position(5)]), _account(), "LCID")


def test_suggest_more_no_setup_raises(monkeypatch):
    """A ticker no longer in a dip (setup None) can't be "comprar mais"."""
    _patch(monkeypatch)
    monkeypatch.setattr(
        "app.services.hv_dip.engine.build_hv_dip_setup",
        lambda t, bars, last_price=None, **kw: None,
    )
    with pytest.raises(ValueError):
        suggest_more_for_ticker(_db([_position(1)]), _account(), "LCID")
