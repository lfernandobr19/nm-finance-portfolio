"""Backfill historical intraday bars (DXLink/tastytrade) into the durable store."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.market_data import MarketDataClient
from app.services.day_trade.store import upsert_bars
from app.services.tastytrade_market_data import parse_watchlist

logger = logging.getLogger("fiidesk.day_trade.backfill")

_TIMEFRAME_MAP = {"5m": "5Min", "15m": "15Min", "1m": "1Min", "1h": "1Hour"}


def backfill_watchlist(db: Session) -> dict[str, int]:
    settings = get_settings()
    client = MarketDataClient()
    symbols = parse_watchlist()
    timeframe = _TIMEFRAME_MAP.get(settings.day_trade_candle_period, "5Min")
    stats = {"tickers": 0, "bars": 0}
    for sym in symbols:
        try:
            bars = client.fetch_intraday_bars(
                sym,
                timeframe=timeframe,
                days=int(settings.day_trade_backfill_days or 5),
            )
            if bars:
                n = upsert_bars(db, sym, bars)
                stats["bars"] += n
                stats["tickers"] += 1
                logger.info("day_trade backfill %s: %d bars", sym, n)
        except Exception:
            logger.exception("day_trade backfill failed for %s", sym)
    db.commit()
    return stats


__all__ = ["backfill_watchlist"]
