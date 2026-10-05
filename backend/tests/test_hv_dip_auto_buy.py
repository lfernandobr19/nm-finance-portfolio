"""Tests for hv_dip auto-buy gate (deep dip OR news, dip-scaled, daily cash cap)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.models import AccountCurrency, ExecutionMode, InvestmentAccount, SuggestionStatus
from app.services.hv_dip.engine import run_hv_dip_cycle


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
    )
    defaults.update(kw)
    return InvestmentAccount(**defaults)


def _candidate(ticker: str, dip_pct: float, catalyst=False) -> dict:
    scored = MagicMock(letter="B", numeric_score=80, r_multiple=2.0, reasons=[])
    return {
        "ticker": ticker,
        "entry": 5.0,
        "scored": scored,
        "stop": 4.5,
        "target": 5.5,
        "setup_low": 4.4,
        "dip_pct": dip_pct,
        "review_required": False,
        "review_reason": None,
        "rank": 50.0,
        "atr_pct": 4.0,
        "volume_ratio": 1.2,
        "catalyst": {"id": "n1"} if catalyst else None,
        "risky_recovery": False,
    }


def _run(db, monkeypatch, candidates, *, deployed_today=0.0, news=None):
    monkeypatch.setattr("app.services.hv_dip.engine.settings.hv_dip_enabled", True)
    monkeypatch.setattr("app.services.hv_dip.engine.settings.hv_dip_auto_buy_enabled", True)
    monkeypatch.setattr("app.services.hv_dip.engine.settings.hv_dip_auto_buy_daily_cash_pct", 50.0)
    monkeypatch.setattr("app.services.hv_dip.engine.settings.hv_dip_qt_risk_pct", 1.0)
    monkeypatch.setattr(
        "app.services.hv_dip.engine.active_bullish_events", lambda db, ticker: []
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.active_recovery_events", lambda db, ticker: []
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.deployed_on_ticker_usd",
        lambda db, account_id, ticker: 0.0,
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
        "app.services.hv_dip.engine._auto_deployed_today_usd",
        lambda db, account_id: deployed_today,
    )
    monkeypatch.setattr(
        "app.services.hv_dip.engine.create_order_from_suggestion",
        lambda db, suggestion, acted_by_user_id=None: MagicMock(),
    )
    monkeypatch.setattr(
        "app.services.desk_judgment.load_news",
        lambda db, ticker, days=7: list(news or []),
    )
    monkeypatch.setattr(
        "app.services.desk_judgment.load_memories",
        lambda ticker: [],
    )
    from app.services.desk_gate import GateVerdict

    monkeypatch.setattr(
        "app.services.desk_gate.apply_intent",
        lambda db, intent, **k: GateVerdict(
            allow=False, queued=True, reason="queued", enforce=True
        ),
    )
    monkeypatch.setattr(
        "app.services.market_data.MarketDataClient.fetch_daily_bars_many",
        lambda self, tickers: {t: [] for t in tickers},
    )
    monkeypatch.setattr(
        "app.services.market_data.MarketDataClient.fetch_last_prices",
        lambda self, tickers: {t: 0.0 for t in tickers},
    )
    with patch("app.services.hv_dip.engine.analyze_ticker", side_effect=candidates):
        with patch("app.services.hv_dip.engine.hv_dip_tickers", return_value=["AMD"]):
            with patch("app.services.hv_dip.engine._pending_hv", return_value=False):
                with patch("app.services.hv_dip.engine._open_position", return_value=None):
                    with patch("app.services.hv_dip.engine.notify_suggestion"):
                        created = run_hv_dip_cycle(db)
    return created


def _db() -> MagicMock:
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [_account()]
    db.add = MagicMock()
    db.flush = MagicMock()
    db.commit = MagicMock()
    return db


def test_deep_dip_triggers_auto_buy(monkeypatch):
    """A dip at/above the threshold auto-buys without needing a news catalyst."""
    created = _run(
        _db(),
        monkeypatch,
        [_candidate("AMD", dip_pct=25.0)],
        deployed_today=0.0,
    )
    assert len(created) == 1
    assert created[0].status == SuggestionStatus.auto_approved


def test_shallow_dip_without_news_stays_pending(monkeypatch):
    """A shallow dip with no catalyst remains pending for manual approval."""
    created = _run(
        _db(),
        monkeypatch,
        [_candidate("AMD", dip_pct=14.0)],
        deployed_today=0.0,
    )
    assert len(created) == 1
    assert created[0].status == SuggestionStatus.pending


def test_shallow_dip_with_news_triggers_auto_buy(monkeypatch):
    """A news catalyst alone (shallow dip) still auto-buys."""
    created = _run(
        _db(),
        monkeypatch,
        [_candidate("AMD", dip_pct=14.0, catalyst=True)],
        deployed_today=0.0,
    )
    assert len(created) == 1
    assert created[0].status == SuggestionStatus.auto_approved


def test_live_account_never_auto_buys(monkeypatch):
    """Live without hv_dip_live_auto_buy records a shadow and creates no suggestion."""
    monkeypatch.setattr("app.services.hv_dip.engine.settings.hv_dip_live_auto_buy", False)
    monkeypatch.setattr("app.services.hv_dip.engine.settings.hv_dip_live_shadow", True)
    db = _db()
    db.query.return_value.filter.return_value.all.return_value = [
        _account(execution_mode=ExecutionMode.live)
    ]
    created = _run(
        db,
        monkeypatch,
        [_candidate("AMD", dip_pct=25.0)],
        deployed_today=0.0,
    )
    assert created == []


def test_live_auto_buy_flag_creates_a_suggestion(monkeypatch):
    """When hv_dip_live_auto_buy is on, live uses the paper path with a smaller size."""
    monkeypatch.setattr("app.services.hv_dip.engine.settings.hv_dip_live_auto_buy", True)
    monkeypatch.setattr("app.services.hv_dip.engine.settings.hv_dip_live_size_mult", 0.5)
    db = _db()
    db.query.return_value.filter.return_value.all.return_value = [
        _account(execution_mode=ExecutionMode.live)
    ]
    created = _run(
        db,
        monkeypatch,
        [_candidate("AMD", dip_pct=25.0)],
        deployed_today=0.0,
    )
    assert len(created) == 1
    assert created[0].status == SuggestionStatus.auto_approved
    assert created[0].proposed_amount_brl < 25.0 * 5  # size_mult shrinks the ticket


def test_skip_reason_fresh_high_lifted_without_scandal(monkeypatch):
    """A stale fresh_high lock is a prior — judgment buys when the tape is clean."""
    row = _candidate("AMD", dip_pct=25.0)
    row["skip_reason"] = "fresh_high"
    created = _run(_db(), monkeypatch, [row], deployed_today=0.0)
    assert len(created) == 1


def test_skip_reason_scandal_still_observes(monkeypatch):
    """A 25% dump with a bankruptcy headline is observed, not bought."""
    from types import SimpleNamespace

    row = _candidate("AMD", dip_pct=25.0)
    row["skip_reason"] = "fresh_high"
    created = _run(
        _db(),
        monkeypatch,
        [row],
        deployed_today=0.0,
        news=[
            SimpleNamespace(
                ticker="AMD",
                title="AMD bankruptcy filing after accounting scandal",
                event_type="litigation",
                sentiment="bearish",
                confidence=0.9,
            )
        ],
    )
    assert created == []


def test_study_guard_suppresses_the_setup(monkeypatch):
    """Hard mode (blocked=True): a refuted pattern is skipped — no auto-buy."""
    monkeypatch.setattr(
        "app.services.hv_dip.engine.hv_dip_force_review",
        lambda: (True, "P(alvo antes do stop) fraca — desk não opera"),
    )
    created = _run(
        _db(),
        monkeypatch,
        [_candidate("AMD", dip_pct=25.0)],
        deployed_today=0.0,
    )
    assert created == []


def test_study_guard_advisory_annotates_instead_of_suppressing(monkeypatch):
    """Advisory (default): a refuted pattern is a note on the trade, not a lock."""
    monkeypatch.setattr(
        "app.services.hv_dip.engine.hv_dip_force_review",
        lambda: (False, "P(alvo antes do stop) fraca — desk decide"),
    )
    created = _run(
        _db(),
        monkeypatch,
        [_candidate("AMD", dip_pct=25.0)],
        deployed_today=0.0,
    )
    assert len(created) == 1
    assert created[0].status == SuggestionStatus.auto_approved
    assert created[0].metrics.get("study_note") == "P(alvo antes do stop) fraca — desk decide"


def test_daily_cash_cap_blocks_auto_buy(monkeypatch):
    """When today's auto-deploy already meets the cash cap, it falls back to pending."""
    created = _run(
        _db(),
        monkeypatch,
        [_candidate("AMD", dip_pct=25.0)],
        deployed_today=50.0,  # cash 100 × 50% cap already consumed
    )
    assert len(created) == 1
    assert created[0].status == SuggestionStatus.pending
