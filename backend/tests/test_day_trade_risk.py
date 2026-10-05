"""Day trade risk gates: session scoping and the stale-open sweep.

Regression cover for the bug that stalled signal generation from 09/set: open
signals from past sessions were never resolved (``update_open_signals`` only
revisits the current session and ticker) yet still counted towards the
concurrency limit, so every account sat permanently at the cap.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.domain.models import DayTradeSide, DayTradeSignal, DayTradeSignalStatus
from app.services.day_trade.analytics import closed_signals
from app.services.day_trade.risk import (
    concurrent_exceeded,
    expire_stale_signals,
    open_signal_count,
)

TODAY = date(2026, 9, 12)
PAST = date(2026, 9, 9)
ACCOUNT = "7fa92732-d890-41ba-ac47-13e4e5b3e67f"


def _signal(session_date: date, *, status=DayTradeSignalStatus.open, account=ACCOUNT):
    return DayTradeSignal(
        account_id=account,
        session_date=session_date,
        ticker="AAPL",
        rule_id="vwap_reclaim",
        side=DayTradeSide.long,
        entry_price=100.0,
        stop_price=99.0,
        target_price=102.0,
        status=status,
        metrics={},
    )


@pytest.fixture
def limit_six(monkeypatch):
    class _S:
        day_trade_max_concurrent_signals = 6

    monkeypatch.setattr("app.services.day_trade.risk.get_settings", lambda: _S())


def test_open_signal_count_ignores_past_sessions(db_session):
    db_session.add_all([_signal(PAST) for _ in range(6)])
    db_session.add(_signal(TODAY))
    db_session.flush()

    assert open_signal_count(db_session, ACCOUNT, TODAY) == 1
    assert open_signal_count(db_session, ACCOUNT, PAST) == 6


def test_concurrent_not_exceeded_by_stale_opens(db_session, limit_six):
    """The exact production state: 6 stale opens, limit 6, nothing open today."""
    db_session.add_all([_signal(PAST) for _ in range(6)])
    db_session.flush()

    assert concurrent_exceeded(db_session, ACCOUNT, TODAY) is False


def test_concurrent_exceeded_within_session(db_session, limit_six):
    db_session.add_all([_signal(TODAY) for _ in range(6)])
    db_session.flush()

    assert concurrent_exceeded(db_session, ACCOUNT, TODAY) is True


def test_expire_stale_signals_only_touches_past_sessions(db_session):
    db_session.add_all([_signal(PAST) for _ in range(3)])
    db_session.add(_signal(TODAY))
    db_session.flush()

    assert expire_stale_signals(db_session, session_date=TODAY) == 3

    rows = db_session.query(DayTradeSignal).all()
    expired = [r for r in rows if r.status == DayTradeSignalStatus.expired]
    still_open = [r for r in rows if r.status == DayTradeSignalStatus.open]
    assert len(expired) == 3
    assert all(r.closed_at is not None for r in expired)
    assert [r.session_date for r in still_open] == [TODAY]


def test_expire_stale_signals_is_idempotent(db_session):
    db_session.add_all([_signal(PAST) for _ in range(2)])
    db_session.flush()

    assert expire_stale_signals(db_session, session_date=TODAY) == 2
    assert expire_stale_signals(db_session, session_date=TODAY) == 0


def test_expired_signals_never_reach_analytics(db_session):
    """Expired signals have no observed exit, so they must not be counted as trades."""
    db_session.add_all([_signal(PAST) for _ in range(4)])
    closed = _signal(PAST, status=DayTradeSignalStatus.closed)
    closed.simulated_pnl_usd = 1.5
    db_session.add(closed)
    db_session.flush()

    expire_stale_signals(db_session, session_date=TODAY)

    rows = closed_signals(db_session, ACCOUNT)
    assert len(rows) == 1
    assert rows[0].simulated_pnl_usd == 1.5
