"""Intraday risk controls for day trade signals (paper).

Enforces: allowed time-of-day window (skip open spike + lunch), max concurrent
open signals within the session, and a daily realized-R loss limit. These are
applied at signal generation time (not a post-hoc filter) to reduce low-quality
/ overcrowded setups.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.models import DayTradeSignal, DayTradeSignalStatus
from app.services.day_trade.analytics import _r_multiple
from app.services.market_hours import now_us_eastern

logger = logging.getLogger("fiidesk.day_trade.risk")

_LUNCH_START = time(12, 0)
_LUNCH_END = time(13, 0)


def is_time_window_ok(bar_ts) -> bool:
    settings = get_settings()
    et = now_us_eastern(bar_ts)
    if et.weekday() >= 5:
        return False
    minutes = et.hour * 60 + et.minute
    min_m = int(settings.day_trade_session_min_minutes or 0)
    max_m = int(settings.day_trade_session_max_minutes or 390)
    # Relative to 09:30 ET open (570 min).
    open_min = 9 * 60 + 30
    rel = minutes - open_min
    if rel < min_m:
        return False
    if rel > max_m:
        return False
    if settings.day_trade_lunch_skip and _LUNCH_START <= et.time() < _LUNCH_END:
        return False
    return True


def open_signal_count(db: Session, account_id: str, session_date: date) -> int:
    from sqlalchemy import func

    return int(
        db.execute(
            select(func.count(DayTradeSignal.id)).where(
                DayTradeSignal.account_id == account_id,
                DayTradeSignal.session_date == session_date,
                DayTradeSignal.status == DayTradeSignalStatus.open,
            )
        ).scalar_one()
        or 0
    )


def expire_stale_signals(db: Session, *, session_date: date) -> int:
    """Expire open signals left behind by earlier sessions.

    A day trade signal cannot outlive the session that created it, but
    ``update_open_signals`` only revisits rows matching the current session and
    ticker. Without this sweep, anything left open by a previous session stays
    open forever and permanently saturates ``concurrent_exceeded``.

    Uses ``expired`` rather than ``closed`` on purpose: these signals have no
    observed exit, so a NULL ``simulated_pnl_usd`` must not reach the analytics
    and learning paths, which select on ``closed``.
    """
    updated = (
        db.query(DayTradeSignal)
        .filter(
            DayTradeSignal.session_date < session_date,
            DayTradeSignal.status == DayTradeSignalStatus.open,
        )
        .update(
            {
                DayTradeSignal.status: DayTradeSignalStatus.expired,
                DayTradeSignal.closed_at: datetime.now(timezone.utc),
            },
            synchronize_session=False,
        )
    )
    count = int(updated or 0)
    if count:
        logger.info("Expired %d stale day trade signals before %s", count, session_date)
    return count


def daily_realized_r(db: Session, account_id: str, session_date: date) -> float:
    rows = db.execute(
        select(DayTradeSignal).where(
            DayTradeSignal.account_id == account_id,
            DayTradeSignal.session_date == session_date,
            DayTradeSignal.status == DayTradeSignalStatus.closed,
        )
    ).scalars().all()
    total = 0.0
    for s in rows:
        r = _r_multiple(s)
        if r is not None and r < 0:
            total += abs(r)
    return total


def concurrent_exceeded(db: Session, account_id: str, session_date: date) -> bool:
    settings = get_settings()
    limit = int(settings.day_trade_max_concurrent_signals or 6)
    return open_signal_count(db, account_id, session_date) >= limit


def daily_loss_exceeded(db: Session, account_id: str, session_date: date) -> bool:
    settings = get_settings()
    limit = float(settings.day_trade_daily_loss_limit_r or 5.0)
    return daily_realized_r(db, account_id, session_date) >= limit


__all__ = [
    "is_time_window_ok",
    "open_signal_count",
    "expire_stale_signals",
    "daily_realized_r",
    "concurrent_exceeded",
    "daily_loss_exceeded",
]
