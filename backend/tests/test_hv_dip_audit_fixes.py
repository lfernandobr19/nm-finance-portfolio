"""Regression coverage for the four hv_dip code bugs from the strategy audit.

1. Auto-buy ValueError must not roll back the whole cycle.
2. Cash floor / ticker cap use real equity (cash + invested), not a stale
   hv_dip_equity_usd reference.
3. Learn-loop thresholds actually reach build_hv_dip_setup.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.domain.models import (
    AccountCurrency,
    AssetClass,
    DividendFrequency,
    ExecutionMode,
    InvestmentAccount,
    StrategyKind,
    Suggestion,
    SuggestionStatus,
)
from app.services.hv_dip.engine import (
    _create_suggestion,
    build_hv_dip_setup,
    run_hv_dip_cycle,
)
from app.services.hv_dip.sizing import sizing_basis
from app.services.orders import assert_hv_dip_guards


def _account(**kw) -> InvestmentAccount:
    defaults = dict(
        id="a1",
        name="NM",
        broker_code="tastytrade",
        currency=AccountCurrency.USD,
        execution_mode=ExecutionMode.paper,
        cash_usd=100.0,
        hv_dip_equity_usd=100.0,
        max_ticket_brl=1000.0,
        hv_dip_cash_floor_pct=20.0,
        hv_dip_max_ticker_pct=80.0,
        hv_dip_max_positions=4,
        automation_paused=False,
    )
    defaults.update(kw)
    return InvestmentAccount(**defaults)


def _scored(letter="B"):
    return MagicMock(letter=letter, numeric_score=80, r_multiple=2.0, reasons=[])


def _row(ticker="AMD", dip_pct=18.0, entry=10.0, letter="B"):
    return {
        "ticker": ticker,
        "entry": entry,
        "scored": _scored(letter),
        "stop": entry * 0.9,
        "target": entry * 1.2,
        "setup_low": entry * 0.88,
        "recent_high": entry * 1.2,
        "days_since_recent_high": 5,
        "dip_pct": dip_pct,
        "review_required": False,
        "review_reason": None,
        "rank": 50.0 + dip_pct,
        "atr_pct": 4.0,
        "volume_ratio": 1.2,
        "weekly_range_pct": 8.0,
        "recovery_rate": 0.7,
        "round_trips": 3,
        "quality_tier": "large",
        "is_fresh_high": False,
        "structural_decline": False,
        "catalyst": None,
        "risky_recovery": False,
    }


def _nested_ok():
    @contextmanager
    def _cm():
        yield

    return _cm()


# --------------------------------------------------------------------------- #
# 1. Auto-buy guard failure must keep the suggestion as pending
# --------------------------------------------------------------------------- #
def test_auto_buy_guard_failure_keeps_suggestion_pending(monkeypatch):
    """When create_order_from_suggestion raises ValueError, the suggestion
    survives as pending with the block reason attached — the cycle must not
    abort."""
    monkeypatch.setattr(
        "app.services.hv_dip.engine.settings.hv_dip_auto_buy_enabled", True
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.settings.hv_dip_auto_buy_min_dip_pct", 15.0
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.settings.hv_dip_auto_buy_daily_cash_pct", 50.0
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.settings.hv_dip_qt_risk_pct", 1.0
    )
    monkeypatch.setattr(
        "app.services.desk_judgment.load_news", lambda *a, **k: []
    )
    monkeypatch.setattr(
        "app.services.desk_judgment.load_memories", lambda *a, **k: []
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.deployed_on_ticker_usd",
        lambda *a, **k: 0.0,
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.account_sizing_basis",
        lambda db, account: sizing_basis(account, invested_usd=0.0),
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine._auto_deployed_today_usd",
        lambda *a, **k: 0.0,
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.notify_suggestion", lambda *a, **k: None
    )

    def _refuse(*a, **k):
        raise ValueError("Limite de 4 tickers High-Vol abertos atingido")

    monkeypatch.setattr(
        "app.services.hv_dip.engine.create_order_from_suggestion", _refuse
    )
    from app.services.desk_gate import GateVerdict

    monkeypatch.setattr(
        "app.services.desk_gate.apply_intent",
        lambda db, intent, **k: GateVerdict(
            allow=True, queued=False, reason="ok", enforce=True
        ),
    )

    db = MagicMock()
    db.begin_nested.side_effect = lambda: _nested_ok()
    db.add = MagicMock()
    db.flush = MagicMock()

    expires = datetime.now(timezone.utc)
    sug = _create_suggestion(
        db, _account(), _row(dip_pct=18.0), tranche=1, expires_at=expires
    )
    assert sug is not None
    assert sug.status == SuggestionStatus.pending
    assert sug.acted_at is None
    assert sug.review_reason is not None
    assert "Auto-buy bloqueado" in sug.review_reason
    assert "Limite de 4 tickers" in sug.review_reason


def test_auto_buy_failure_does_not_abort_sibling_suggestions(monkeypatch):
    """One refused auto-buy must not cost the other tickers in the same cycle."""
    monkeypatch.setattr("app.services.hv_dip.engine.settings.hv_dip_enabled", True)
    monkeypatch.setattr(
        "app.services.hv_dip.engine.settings.hv_dip_auto_buy_enabled", True
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.settings.hv_dip_auto_buy_min_dip_pct", 15.0
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.settings.hv_dip_auto_buy_daily_cash_pct", 50.0
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.settings.hv_dip_qt_risk_pct", 1.0
    )
    monkeypatch.setattr(
        "app.services.desk_judgment.load_news", lambda *a, **k: []
    )
    monkeypatch.setattr(
        "app.services.desk_judgment.load_memories", lambda *a, **k: []
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.deployed_on_ticker_usd",
        lambda *a, **k: 0.0,
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.account_sizing_basis",
        lambda db, account: sizing_basis(account, invested_usd=0.0),
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine._auto_deployed_today_usd",
        lambda *a, **k: 0.0,
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.active_bullish_events", lambda *a, **k: []
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.active_recovery_events", lambda *a, **k: []
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
        "app.services.hv_dip.engine.notify_suggestion", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "app.services.market_data.MarketDataClient.fetch_daily_bars_many",
        lambda self, tickers: {t: [] for t in tickers},
    )
    monkeypatch.setattr(
        "app.services.market_data.MarketDataClient.fetch_last_prices",
        lambda self, tickers: {t: 10.0 for t in tickers},
    )

    calls = {"n": 0}

    def _order(db, suggestion, acted_by_user_id=None):
        calls["n"] += 1
        if suggestion.ticker == "AMD":
            raise ValueError("Limite de 4 tickers High-Vol abertos atingido")
        return MagicMock()

    monkeypatch.setattr(
        "app.services.hv_dip.engine.create_order_from_suggestion", _order
    )
    from app.services.desk_gate import GateVerdict

    monkeypatch.setattr(
        "app.services.desk_gate.apply_intent",
        lambda db, intent, **k: GateVerdict(
            allow=True, queued=False, reason="ok", enforce=True
        ),
    )

    candidates = [
        _row("AMD", dip_pct=18.0),
        _row("LCID", dip_pct=20.0, entry=5.0),
    ]

    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [_account()]
    db.begin_nested.side_effect = lambda: _nested_ok()
    db.add = MagicMock()
    db.flush = MagicMock()
    db.commit = MagicMock()

    with patch(
        "app.services.hv_dip.engine.analyze_ticker",
        side_effect=candidates,
    ):
        with patch(
            "app.services.hv_dip.engine.hv_dip_tickers",
            return_value=["AMD", "LCID"],
        ):
            with patch(
                "app.services.hv_dip.engine._pending_hv", return_value=False
            ):
                with patch(
                    "app.services.hv_dip.engine._open_position", return_value=None
                ):
                    created = run_hv_dip_cycle(db)

    tickers = {s.ticker for s in created}
    assert tickers == {"AMD", "LCID"}
    amd = next(s for s in created if s.ticker == "AMD")
    lcid = next(s for s in created if s.ticker == "LCID")
    assert amd.status == SuggestionStatus.pending
    assert "Auto-buy bloqueado" in (amd.review_reason or "")
    assert lcid.status == SuggestionStatus.auto_approved


# --------------------------------------------------------------------------- #
# 2. Ticker concentration cap activates on real equity
# --------------------------------------------------------------------------- #
def test_ticker_cap_uses_real_equity_not_stale_ref():
    """With cash=28.24 and hv_dip_equity_usd=100, the old formula made the
    80% ticker cap US$ 80 — above total cash, so the guard never fired. With
    real equity the cap is 80% of 28.24 = 22.59."""
    acc = _account(
        cash_usd=28.24,
        hv_dip_equity_usd=100.0,
        hv_dip_cash_floor_pct=20.0,
        hv_dip_max_ticker_pct=80.0,
    )
    basis = sizing_basis(acc, invested_usd=0.0)
    assert basis.ticker_cap == pytest.approx(22.592, abs=0.01)
    # Cap is below the stale-ref value of 80 that made the guard inert.
    assert basis.ticker_cap < 30.0


def test_assert_hv_dip_guards_blocks_over_real_ticker_cap(monkeypatch):
    """Deployed near the real-equity ticker cap → ValueError."""
    monkeypatch.setattr(
        "app.services.orders.account_sizing_basis",
        lambda db, account: sizing_basis(account, invested_usd=20.0),
    )
    # cash 28.24 + invested 20 = equity 48.24 → 80% cap = 38.59
    # already deployed 35 on ticker → room ~3.59; order of 10 must fail.
    monkeypatch.setattr(
        "app.services.orders.deployed_on_ticker_usd",
        lambda *a, **k: 35.0,
    )
    monkeypatch.setattr(
        "app.services.orders.count_open_hv_dip_tickers", lambda *a, **k: 1
    )

    acc = _account(
        cash_usd=28.24,
        hv_dip_equity_usd=100.0,
        hv_dip_cash_floor_pct=20.0,
        hv_dip_max_ticker_pct=80.0,
    )
    sug = Suggestion(
        id="s1",
        account_id=acc.id,
        ticker="LCID",
        strategy_kind=StrategyKind.hv_dip,
        asset_class=AssetClass.us_equity,
        dividend_frequency=DividendFrequency.other,
        score=80,
        swing_score_letter="A",
        entry_price=5.0,
        status=SuggestionStatus.pending,
        reasons=[],
        metrics={},
        price_explanation="",
        rule_version=2,
        proposed_amount_brl=10.0,
        tranche_index=1,
        review_required=False,
    )
    db = MagicMock()
    # already-open check: count() > 0 must be a real bool
    db.query.return_value.filter.return_value.count.return_value = 1
    with pytest.raises(ValueError, match="Teto .* no ticker"):
        assert_hv_dip_guards(
            db, acc, sug, amount_usd=10.0, human_approved=True
        )


# --------------------------------------------------------------------------- #
# 3. Learn-loop thresholds reach the engine
# --------------------------------------------------------------------------- #
def _dip_bars(dip_pct: float, n: int = 90):
    """Synthetic daily bars ending in a controlled dip from a recent high."""
    from app.services.brapi_client import Bar

    high = 15.0
    close = high * (1.0 - dip_pct / 100.0)
    bars = []
    # Rising into a fresh-ish high, then falling to `close`.
    for i in range(n - 10):
        px = 10.0 + i * 0.02
        bars.append(
            Bar(
                date=datetime(2025, 1, 1, tzinfo=timezone.utc),
                open=px,
                high=px + 0.1,
                low=px - 0.1,
                close=px,
                volume=5_000_000,
            )
        )
    # Peak window
    for _ in range(5):
        bars.append(
            Bar(
                date=datetime(2025, 1, 1, tzinfo=timezone.utc),
                open=high,
                high=high,
                low=high - 0.1,
                close=high - 0.05,
                volume=8_000_000,
            )
        )
    # Dip window
    for _ in range(5):
        bars.append(
            Bar(
                date=datetime(2025, 1, 1, tzinfo=timezone.utc),
                open=close + 0.2,
                high=close + 0.3,
                low=close - 0.1,
                close=close,
                volume=9_000_000,
            )
        )
    return bars


def test_active_params_high_dip_rejects_setup_that_passes_env(monkeypatch):
    """Env floor is 12%; learn-loop config at 20% must reject a 15% dip."""
    monkeypatch.setattr(
        "app.services.hv_dip.engine.settings.hv_dip_min_dip_pct", 12.0
    )
    # Make quality/ATR filters permissive so only the dip floor decides.
    monkeypatch.setattr(
        "app.services.hv_dip.engine.quality_tier", lambda *a, **k: "large"
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.atr_pct", lambda *a, **k: 5.0
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.volume_vs_sma", lambda *a, **k: 1.5
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.weekly_range_pct", lambda *a, **k: 8.0
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.recovery_rate", lambda *a, **k: 0.8
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.round_trips", lambda *a, **k: 4
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.is_fresh_high", lambda *a, **k: False
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.trend_context_allows_long",
        lambda *a, **k: (True, None),
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.higher_lows_recent", lambda *a, **k: True
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.derive_weekly", lambda bars: bars
    )

    bars = _dip_bars(15.0)
    # Without override → env 12% accepts.
    accepted = build_hv_dip_setup("TEST", bars, min_dip_pct=12.0)
    assert accepted is not None
    # Learn-loop override at 20% rejects the same bars.
    rejected = build_hv_dip_setup("TEST", bars, min_dip_pct=20.0)
    assert rejected is None
