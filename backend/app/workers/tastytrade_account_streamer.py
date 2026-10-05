"""Long-running tastytrade Account Streamer worker (OAuth, not DXLink)."""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.config import get_settings
from app.services.tastytrade_account_streamer import AccountStreamer
from app.services.tastytrade_client import TastytradeClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("fiidesk.tastytrade.account_streamer.worker")


def main() -> None:
    settings = get_settings()
    if not settings.tastytrade_account_streamer_enabled:
        logger.info("TASTYTRADE_ACCOUNT_STREAMER_ENABLED=false — exiting")
        return
    client = TastytradeClient(live=False)
    if not client.configured():
        logger.info("tastytrade sandbox not configured — exiting")
        return

    while True:
        try:
            logger.info("starting account streamer (sandbox=%s)", settings.tastytrade_sandbox)
            asyncio.run(AccountStreamer(client=client).run())
        except KeyboardInterrupt:
            logger.info("Account streamer stopped")
            return
        except Exception:
            logger.exception("Account streamer loop failed")
        time.sleep(10)


if __name__ == "__main__":
    main()
