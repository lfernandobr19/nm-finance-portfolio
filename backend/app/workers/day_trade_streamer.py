"""Day trade DXLink streamer worker (US session only)."""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.config import get_settings
from app.db import SessionLocal
from app.services.day_trade.cache import DayTradeBarCache
from app.services.day_trade.observer import run_observer_for_us_accounts
from app.services.day_trade.store import upsert_bars
from app.services.market_hours import us_market_session, us_session_open
from app.services.tastytrade_market_data import DXLinkCandleStreamer, parse_watchlist

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("fiidesk.day_trade.streamer")


async def _run_stream_loop() -> None:
    settings = get_settings()
    cache = DayTradeBarCache()
    symbols = parse_watchlist()

    async def on_bar(ticker: str, bar) -> None:
        bars = cache.append_bar(ticker, bar)
        db = SessionLocal()
        try:
            upsert_bars(db, ticker, [bar])
            created = run_observer_for_us_accounts(db, ticker=ticker, bars=bars)
            db.commit()
            if created:
                logger.info("Observer created %d signals for %s", created, ticker)
        except Exception:
            db.rollback()
            logger.exception("Observer failed for %s", ticker)
        finally:
            db.close()

    streamer = DXLinkCandleStreamer(
        symbols=symbols,
        interval=settings.day_trade_candle_period,
        on_bar=on_bar,
    )
    logger.info("DXLink streaming %s", ",".join(symbols))
    await streamer.run()


def main() -> None:
    settings = get_settings()
    if not settings.day_trade_enabled:
        logger.info("DAY_TRADE_ENABLED=false — exiting")
        return
    if not settings.day_trade_streamer_enabled:
        logger.info("DAY_TRADE_STREAMER_ENABLED=false — exiting")
        return

    while True:
        session = us_market_session()
        if not us_session_open():
            logger.info("US market closed (%s) — sleeping 60s", session.status_label)
            time.sleep(60)
            continue
        try:
            asyncio.run(_run_stream_loop())
        except KeyboardInterrupt:
            logger.info("Streamer stopped")
            return
        except Exception:
            logger.exception("Streamer loop failed")
        if not us_session_open():
            logger.info("US session ended — waiting for next open")
        time.sleep(10)


if __name__ == "__main__":
    main()
