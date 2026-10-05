"""Expectancy gate: n≥10 and sum R ≤ 0 cuts the rule. Lab-wide, not per account."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.domain.models import DayTradeSide, DayTradeSignal, DayTradeSignalStatus
from app.services.day_trade.bars import IntradayBar
from app.services.day_trade.gating import compute_gates, rule_is_gated
from app.services.day_trade.regime import RegimeState

ACCOUNT = "7fa92732-d890-41ba-ac47-13e4e5b3e67f"
OTHER = "84a85f23-660a-44c2-998f-3aa77f220cc1"
SESSION = date(2026, 9, 12)


def _closed(
    *,
    account: str = ACCOUNT,
    rule: str = "vwap_reclaim",
    ticker: str = "AAPL",
    pnl: float = -0.05,
    entry: float = 100.0,
    stop: float = 99.0,
) -> DayTradeSignal:
    return DayTradeSignal(
        account_id=account,
        session_date=SESSION,
        ticker=ticker,
        rule_id=rule,
        side=DayTradeSide.long,
        entry_price=entry,
        stop_price=stop,
        target_price=102.0,
        status=DayTradeSignalStatus.closed,
        simulated_pnl_usd=pnl,
        metrics={},
    )


def test_ten_vwap_negative_r_is_gated(db_session):
    db_session.add_all([_closed() for _ in range(10)])
    db_session.flush()

    gates = compute_gates(db_session, ACCOUNT)
    assert rule_is_gated(gates, "vwap_reclaim") is True
    assert "vwap_reclaim" in gates["rules"]


def test_nine_vwap_is_not_gated(db_session):
    db_session.add_all([_closed() for _ in range(9)])
    db_session.flush()

    gates = compute_gates(db_session, ACCOUNT)
    assert rule_is_gated(gates, "vwap_reclaim") is False


def test_split_across_accounts_still_gates(db_session):
    """Observer writes the same bars on every USD account; n must not fragment."""
    db_session.add_all([_closed(account=ACCOUNT) for _ in range(4)])
    db_session.add_all([_closed(account=OTHER, ticker="MSFT") for _ in range(6)])
    db_session.flush()

    gates = compute_gates(db_session, ACCOUNT)
    assert rule_is_gated(gates, "vwap_reclaim") is True


def test_positive_sum_r_does_not_gate(db_session):
    db_session.add_all(
        [_closed(pnl=0.10) for _ in range(8)] + [_closed(pnl=-0.05) for _ in range(2)]
    )
    db_session.flush()

    gates = compute_gates(db_session, ACCOUNT)
    assert rule_is_gated(gates, "vwap_reclaim") is False


_BASE = datetime(2026, 1, 15, 14, 30, tzinfo=timezone.utc)


def _vwap_bars() -> list[IntradayBar]:
    rows = [
        (0, 100.0, 101.0, 99.0, 99.5, 1000),
        (1, 99.5, 100.0, 98.5, 99.0, 1000),
        (2, 99.0, 100.5, 98.8, 100.2, 1500),
    ]
    return [
        IntradayBar(
            ts=_BASE + timedelta(minutes=m * 5),
            open=o,
            high=h,
            low=lo,
            close=c,
            volume=v,
        )
        for m, o, h, lo, c, v in rows
    ]


@pytest.fixture
def observer_live_gates(monkeypatch):
    """Keep compute_gates real; neutralize the other observer skips."""
    import app.services.day_trade.observer as obs

    monkeypatch.setattr(obs, "is_time_window_ok", lambda _ts: True)
    monkeypatch.setattr(obs, "concurrent_exceeded", lambda *a, **k: False)
    monkeypatch.setattr(obs, "daily_loss_exceeded", lambda *a, **k: False)
    monkeypatch.setattr(obs, "update_open_signals", lambda *a, **k: 0)
    monkeypatch.setattr(obs, "classify_regime", lambda *_a, **_k: RegimeState("trend", 1.0))
    monkeypatch.setattr(obs, "record_forecast", lambda *a, **k: None)
    return obs


def test_observer_skips_vwap_when_lab_sum_r_is_negative(observer_live_gates, db_session):
    db_session.add_all([_closed() for _ in range(10)])
    db_session.flush()

    created = observer_live_gates.run_observer_for_bar(
        db_session, account_id=ACCOUNT, ticker="AMD", bars=_vwap_bars()
    )
    assert all(s.rule_id != "vwap_reclaim" for s in created)
