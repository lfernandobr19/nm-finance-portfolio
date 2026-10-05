"""Durable intraday bar persistence (Postgres) for the learn loop.

Unlike `cache.py` (rolling 120-bar window for live evaluation), this store keeps
every valid bar per ticker/session so the optimizer can replay history.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.domain.models import DayTradeBar
from app.services.day_trade.bars import IntradayBar
from app.services.market_hours import us_session_date

logger = logging.getLogger("fiidesk.day_trade.store")


def _valid_bar(bar: IntradayBar) -> bool:
    import math

    vals = (bar.open, bar.high, bar.low, bar.close, bar.volume)
    return all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in vals)


def upsert_bars(db: Session, ticker: str, bars: list[IntradayBar]) -> int:
    """Insert/update bars for a ticker; returns number of rows written."""
    ticker = ticker.upper()
    rows = []
    for bar in bars:
        if not _valid_bar(bar):
            continue
        rows.append(
            {
                "ticker": ticker,
                "ts": bar.ts,
                "session_date": us_session_date(bar.ts),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            }
        )
    if not rows:
        return 0
    stmt = pg_insert(DayTradeBar).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["ticker", "ts"],
        set_={
            "session_date": stmt.excluded.session_date,
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "volume": stmt.excluded.volume,
        },
    )
    db.execute(stmt)
    return len(rows)


def get_bars(
    db: Session,
    ticker: str,
    *,
    session_date: date | None = None,
    limit: int | None = None,
) -> list[IntradayBar]:
    ticker = ticker.upper()
    q = select(DayTradeBar).where(DayTradeBar.ticker == ticker)
    if session_date is not None:
        q = q.where(DayTradeBar.session_date == session_date)
    q = q.order_by(DayTradeBar.ts.asc())
    if limit is not None:
        q = q.limit(limit)
    rows = db.execute(q).scalars().all()
    return [
        IntradayBar(
            ts=row.ts,
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume),
        )
        for row in rows
    ]


def bar_count(db: Session) -> int:
    from sqlalchemy import func

    return int(db.execute(select(func.count(DayTradeBar.id))).scalar_one() or 0)


def _bar_ts(bar: IntradayBar) -> datetime:
    return bar.ts
