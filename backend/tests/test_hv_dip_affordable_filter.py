"""Tests for the Quick Target whole-lot affordability filter in the hv_dip cycle."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.models import AccountCurrency, InvestmentAccount
from app.services.hv_dip.engine import run_hv_dip_cycle


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


def _candidates() -> list[dict]:
    scored_b = MagicMock(letter="B", numeric_score=70, r_multiple=2.0, reasons=[])
    return [
        {
            # Expensive: risk budget ($1) can't buy even 1 whole share.
            "ticker": "AMD",
            "entry": 43.0,
            "scored": scored_b,
            "stop": 40.0,
            "target": 50.0,
            "setup_low": 39.0,
            "dip_pct": 10.0,
            "review_required": False,
            "review_reason": None,
            "rank": 50.0,
            "atr_pct": 4.0,
            "volume_ratio": 1.2,
        },
        {
            # Affordable: risk budget ($1) buys 2 whole shares at $5.
            "ticker": "LCID",
            "entry": 5.0,
            "scored": scored_b,
            "stop": 4.5,
            "target": 5.5,
            "setup_low": 4.4,
            "dip_pct": 12.0,
            "review_required": False,
            "review_reason": None,
            "rank": 60.0,
            "atr_pct": 5.0,
            "volume_ratio": 1.5,
        },
    ]


def _run(db, monkeypatch, deployed_fn=None):
    monkeypatch.setenv("HV_DIP_ENABLED", "true")
    from app.config import get_settings

    get_settings.cache_clear()
    # Affordability filter only: keep the auto-buy and news paths inert.
    monkeypatch.setattr(
        "app.services.hv_dip.engine.settings.hv_dip_auto_buy_enabled", False
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.active_bullish_events", lambda db, ticker: []
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.active_recovery_events", lambda db, ticker: []
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine._auto_deployed_today_usd", lambda db, account_id: 0.0
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.deployed_on_ticker_usd",
        deployed_fn or (lambda db, account_id, ticker: 0.0),
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
        "app.services.market_data.MarketDataClient.fetch_daily_bars_many",
        lambda self, tickers: {t: [] for t in tickers},
    )
    monkeypatch.setattr(
        "app.services.market_data.MarketDataClient.fetch_last_prices",
        lambda self, tickers: {t: 0.0 for t in tickers},
    )
    with patch("app.services.hv_dip.engine.analyze_ticker", side_effect=_candidates()):
        with patch("app.services.hv_dip.engine.hv_dip_tickers", return_value=["AMD", "LCID"]):
            with patch("app.services.hv_dip.engine._pending_hv", return_value=False):
                with patch("app.services.hv_dip.engine._open_position", return_value=None):
                    with patch("app.services.hv_dip.engine.notify_suggestion"):
                        created = run_hv_dip_cycle(db)
    get_settings.cache_clear()
    return created


def test_whole_lot_skips_unaffordable_expensive_share(monkeypatch):
    """Equal-risk sizing can't buy 1 whole share of AMD → skipped; LCID kept."""
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [_account()]
    db.add = MagicMock()
    db.flush = MagicMock()
    db.commit = MagicMock()

    created = _run(db, monkeypatch)
    tickers = {s.ticker for s in created}
    assert "AMD" not in tickers
    assert "LCID" in tickers


def test_concentration_cap_hides_ticker(monkeypatch):
    """A ticker at its hv_dip_max_ticker_pct cap is hidden (no deployable room)."""
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [_account()]
    db.add = MagicMock()
    db.flush = MagicMock()
    db.commit = MagicMock()

    def deployed_fn(db, account_id, ticker):
        # equity 100 × 80% cap = 80 → LCID at cap, no room left.
        return 80.0 if ticker == "LCID" else 0.0

    created = _run(db, monkeypatch, deployed_fn=deployed_fn)
    tickers = {s.ticker for s in created}
    assert "LCID" not in tickers  # concentration cap reached → hidden
