"""Forecast ledger: recording, resolution, idempotency and summary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import pytest

from app.domain.models import (
    DayTradeSide,
    DayTradeSignal,
    DayTradeSignalStatus,
    ForecastLedger,
    Position,
    PositionStatus,
    StrategyKind,
)
from app.services.learn.ledger import (
    brier_of,
    due_forecasts,
    forward_return,
    ledger_summary,
    record_forecast,
    record_forecast_once,
    resolve_forecast,
    resolve_pending,
    resolved_pairs,
)

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


@dataclass
class FakeBar:
    date: datetime
    close: float


def _bars(closes: list[float], start: datetime = NOW) -> list[FakeBar]:
    """One bar per day starting the day before the anchor."""
    return [
        FakeBar(date=start + timedelta(days=i - 1), close=c)
        for i, c in enumerate(closes)
    ]


def test_record_forecast_sets_resolve_after_beyond_the_horizon(db_session):
    row = record_forecast(
        db_session,
        source="hv_dip",
        kind="entry",
        ticker="amd",
        p_pred=0.62,
        horizon_days=5,
        now=NOW,
    )
    db_session.flush()

    assert row.ticker == "AMD"  # normalised
    assert row.p_pred == 0.62
    assert row.resolved_at is None
    # Calendar slack so weekends do not resolve a 5-session forecast early.
    assert row.resolve_after > NOW + timedelta(days=5)


def test_record_forecast_clamps_probability(db_session):
    high = record_forecast(
        db_session, source="studies", kind="p_higher", ticker="X", p_pred=1.7, now=NOW
    )
    low = record_forecast(
        db_session, source="studies", kind="p_higher", ticker="X", p_pred=-0.3, now=NOW
    )
    db_session.flush()
    assert high.p_pred == 1.0
    assert low.p_pred == 0.0


def test_record_forecast_rejects_unknown_source(db_session):
    with pytest.raises(ValueError):
        record_forecast(
            db_session, source="astrology", kind="vibes", ticker="X", p_pred=0.5
        )


def test_brier_of_matches_definition():
    assert brier_of(1.0, True) == 0.0
    assert brier_of(0.0, True) == 1.0
    assert brier_of(0.5, False) == 0.25


def test_resolve_forecast_scores_and_is_idempotent(db_session):
    row = record_forecast(
        db_session, source="news", kind="bullish", ticker="AMD", p_pred=0.8, now=NOW
    )
    db_session.flush()

    first = resolve_forecast(db_session, row, outcome=False, outcome_value=-0.02, now=NOW)
    assert first == pytest.approx(0.64)
    assert row.outcome is False
    assert row.resolved_at is not None

    # A second pass must not re-score or flip the recorded outcome.
    again = resolve_forecast(db_session, row, outcome=True, now=NOW)
    assert again == pytest.approx(0.64)
    assert row.outcome is False


def test_due_forecasts_only_returns_matured_and_unresolved(db_session):
    ripe = record_forecast(
        db_session, source="hv_dip", kind="entry", ticker="A", p_pred=0.6,
        horizon_days=1, now=NOW - timedelta(days=10),
    )
    record_forecast(
        db_session, source="hv_dip", kind="entry", ticker="B", p_pred=0.6,
        horizon_days=14, now=NOW,
    )
    done = record_forecast(
        db_session, source="hv_dip", kind="entry", ticker="C", p_pred=0.6,
        horizon_days=1, now=NOW - timedelta(days=10),
    )
    resolve_forecast(db_session, done, outcome=True, now=NOW)
    db_session.flush()

    due = due_forecasts(db_session, now=NOW)
    assert [r.id for r in due] == [ripe.id]


def test_forward_return_computes_close_to_close():
    # Bars run [anchor-1d, anchor, anchor+1d, anchor+2d]; the base is the close
    # on the anchor day, so the 100.0 bar before it is deliberately ignored.
    bars = _bars([100.0, 110.0, 121.0, 133.1])
    assert forward_return(bars, NOW, 1) == pytest.approx(0.10)
    assert forward_return(bars, NOW, 2) == pytest.approx(0.21)


def test_forward_return_is_none_when_history_is_short():
    """A forecast must stay pending rather than be graded on a bar that never came."""
    assert forward_return(_bars([100.0, 110.0]), NOW, 5) is None
    assert forward_return([], NOW, 1) is None


def test_resolve_pending_grades_direction_up(db_session):
    record_forecast(
        db_session, source="hv_dip", kind="entry", ticker="AMD", p_pred=0.7,
        horizon_days=1, now=NOW - timedelta(days=10),
    )
    db_session.flush()

    stats = resolve_pending(
        db_session,
        now=NOW,
        bars_for=lambda t: _bars([90.0, 100.0, 105.0], start=NOW - timedelta(days=10)),
    )
    assert stats["resolved"] == 1

    row = db_session.query(ForecastLedger).one()
    assert row.outcome is True
    assert row.outcome_value == pytest.approx(0.05)
    assert row.brier == pytest.approx(0.09)


def test_resolve_pending_honours_a_down_forecast(db_session):
    record_forecast(
        db_session, source="news", kind="bearish", ticker="AMD", p_pred=0.6,
        horizon_days=1, features={"direction": "down"}, now=NOW - timedelta(days=10),
    )
    db_session.flush()

    resolve_pending(
        db_session,
        now=NOW,
        bars_for=lambda t: _bars([110.0, 100.0, 95.0], start=NOW - timedelta(days=10)),
    )
    row = db_session.query(ForecastLedger).one()
    assert row.outcome is True  # price fell, as predicted


def test_resolve_pending_skips_when_bars_are_missing(db_session):
    record_forecast(
        db_session, source="hv_dip", kind="entry", ticker="GHOST", p_pred=0.7,
        horizon_days=1, now=NOW - timedelta(days=10),
    )
    db_session.flush()

    stats = resolve_pending(db_session, now=NOW, bars_for=lambda t: [])
    assert stats["resolved"] == 0
    assert stats["skipped"] == 1
    assert db_session.query(ForecastLedger).one().resolved_at is None


def test_long_unresolvable_forecasts_are_abandoned(db_session):
    """A delisted or unquotable symbol must not be rescanned forever."""
    record_forecast(
        db_session, source="hv_dip", kind="entry", ticker="DELISTED", p_pred=0.7,
        horizon_days=1, now=NOW - timedelta(days=120),
    )
    db_session.flush()

    stats = resolve_pending(db_session, now=NOW, bars_for=lambda t: [])
    assert stats["abandoned"] == 1
    assert stats["skipped"] == 0

    row = db_session.query(ForecastLedger).one()
    assert row.resolved_at is not None
    assert row.outcome is None
    assert row.features["abandoned"] == "unresolvable_no_bars"
    # Gone from the pending queue for good.
    assert due_forecasts(db_session, now=NOW) == []


def test_record_forecast_once_dedups_by_ref(db_session):
    kwargs = dict(
        kind="deep_dip", ticker="AMD", p_pred=0.55, horizon_days=10, now=NOW
    )
    first = record_forecast_once(
        db_session, ref_id="q1:AMD:2026-09-01", source="studies", **kwargs
    )
    db_session.flush()
    second = record_forecast_once(
        db_session, ref_id="q1:AMD:2026-09-01", source="studies", **kwargs
    )

    assert first is not None
    assert second is None
    assert db_session.query(ForecastLedger).count() == 1


def test_day_trade_resolves_from_the_observed_exit(db_session):
    """The simulated exit already ran; the forecast must use it, not a daily drift."""
    sig = DayTradeSignal(
        account_id="7fa92732-d890-41ba-ac47-13e4e5b3e67f",
        session_date=date(2026, 8, 22),
        ticker="AMD",
        rule_id="vwap_reclaim",
        side=DayTradeSide.long,
        entry_price=100.0,
        stop_price=99.0,
        target_price=102.0,
        status=DayTradeSignalStatus.closed,
        simulated_pnl_usd=2.0,
        metrics={},
    )
    db_session.add(sig)
    db_session.flush()

    record_forecast(
        db_session, source="day_trade", kind="vwap_reclaim", ticker="AMD",
        p_pred=0.4, horizon_days=1, ref_id=str(sig.id), now=NOW - timedelta(days=10),
    )
    db_session.flush()

    # Bars deliberately point the other way: if the resolver used them instead of
    # the observed exit, the outcome would flip.
    stats = resolve_pending(
        db_session, now=NOW, bars_for=lambda t: _bars([110.0, 100.0, 90.0])
    )
    assert stats["resolved"] == 1
    row = db_session.query(ForecastLedger).one()
    assert row.outcome is True
    assert row.outcome_value == pytest.approx(2.0)


def test_day_trade_forecast_is_abandoned_when_the_signal_expired(db_session):
    sig = DayTradeSignal(
        account_id="7fa92732-d890-41ba-ac47-13e4e5b3e67f",
        session_date=date(2026, 8, 22),
        ticker="AMD",
        rule_id="vwap_reclaim",
        side=DayTradeSide.long,
        entry_price=100.0,
        stop_price=99.0,
        target_price=102.0,
        status=DayTradeSignalStatus.expired,
        metrics={},
    )
    db_session.add(sig)
    db_session.flush()

    record_forecast(
        db_session, source="day_trade", kind="vwap_reclaim", ticker="AMD",
        p_pred=0.4, horizon_days=1, ref_id=str(sig.id), now=NOW - timedelta(days=10),
    )
    db_session.flush()

    stats = resolve_pending(db_session, now=NOW, bars_for=lambda t: [])
    assert stats["abandoned"] == 1

    row = db_session.query(ForecastLedger).one()
    assert row.resolved_at is not None  # no longer rescanned
    assert row.outcome is None  # but never counted as a win or a loss
    assert row.brier is None
    assert row.features["abandoned"] == "signal_without_exit"

    # And it stays out of every score.
    assert resolved_pairs(db_session, source="day_trade") == []
    assert ledger_summary(db_session)["day_trade"]["brier"] is None


def test_resolved_pairs_and_summary(db_session):
    a = record_forecast(
        db_session, source="news", kind="bullish", ticker="A", p_pred=0.9, now=NOW
    )
    b = record_forecast(
        db_session, source="news", kind="bullish", ticker="B", p_pred=0.8, now=NOW
    )
    record_forecast(
        db_session, source="hv_dip", kind="entry", ticker="C", p_pred=0.5, now=NOW
    )
    resolve_forecast(db_session, a, outcome=False, now=NOW)
    resolve_forecast(db_session, b, outcome=True, now=NOW)
    db_session.flush()

    pairs = resolved_pairs(db_session, source="news")
    assert sorted(pairs) == [(0.8, True), (0.9, False)]

    summary = ledger_summary(db_session)
    assert summary["news"]["resolved"] == 2
    assert summary["news"]["hit_rate"] == 0.5
    assert summary["news"]["brier"] == pytest.approx((0.81 + 0.04) / 2, abs=1e-4)
    # Recorded but not yet graded: counted, without a fabricated score.
    assert summary["hv_dip"]["resolved"] == 0
    assert summary["hv_dip"]["brier"] is None


def test_record_forecast_accepts_mega_rotation_and_judgment(db_session):
    mega = record_forecast(
        db_session, source="mega_rotation", kind="entry", ticker="NVDA", p_pred=0.7, now=NOW
    )
    judged = record_forecast(
        db_session, source="judgment", kind="courage", ticker="NVDA", p_pred=0.7, now=NOW
    )
    db_session.flush()
    assert mega.source == "mega_rotation"
    assert judged.source == "judgment"


def test_resolve_pending_uses_closed_position_pnl(db_session):
    from app.domain.models import Position, PositionStatus

    pos = Position(
        id="pos-nvda",
        account_id="acc1",
        order_id="ord-nvda",
        suggestion_id="sug-nvda",
        ticker="NVDA",
        strategy_kind=StrategyKind.mega_rotation,
        quantity=1.0,
        entry_price=100.0,
        status=PositionStatus.closed,
        realized_pnl_brl=12.0,
        opened_at=NOW,
        closed_at=NOW,
    )
    db_session.add(pos)
    row = record_forecast(
        db_session,
        source="judgment",
        kind="courage",
        ticker="NVDA",
        p_pred=0.7,
        horizon_days=1,
        ref_id="pos-nvda",
        now=NOW - timedelta(days=10),
    )
    db_session.flush()

    stats = resolve_pending(db_session, now=NOW, bars_for=lambda t: [])
    assert stats["resolved"] == 1
    assert row.outcome is True
    assert row.outcome_value == pytest.approx(12.0)


def test_calibration_module_does_not_use_isotonic():
    import inspect

    from app.services.learn import calibration

    src = inspect.getsource(calibration)
    assert "IsotonicRegression" not in src
    assert "method='isotonic'" not in src
    assert "method='temperature'" not in src
    assert "CalibratedClassifierCV" not in src
    assert "fit_platt" in src


def test_ledger_summary_always_includes_mega_rotation_and_judgment(db_session):
    summary = ledger_summary(db_session)
    assert "mega_rotation" in summary
    assert "judgment" in summary
    assert summary["mega_rotation"]["n"] == 0
    assert summary["judgment"]["resolved"] == 0
