"""Smoke test: tastytrade quote token + optional DXLink candle sample."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.tastytrade_client import TastytradeClient
from app.services.tastytrade_market_data import collect_candles, fetch_quote_token

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("day_trade_smoke")


def main() -> int:
    parser = argparse.ArgumentParser(description="Day trade DXLink smoke test")
    parser.add_argument("--symbol", default="SPY")
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--skip-stream", action="store_true")
    args = parser.parse_args()

    client = TastytradeClient()
    if not client.configured():
        logger.error("tastytrade not configured — set credentials in .env")
        return 1

    token = fetch_quote_token(client)
    logger.info("OK quote token (level=%s) url=%s", token.level, token.dxlink_url)

    if args.skip_stream:
        return 0

    candles = asyncio.run(
        collect_candles([args.symbol], timeout_seconds=args.timeout)
    )
    bars = candles.get(args.symbol.upper(), [])
    logger.info("Received %d bars for %s", len(bars), args.symbol.upper())
    if bars:
        last = bars[-1]
        logger.info(
            "Received %d bars for %s",
            len(bars),
            args.symbol.upper(),
        )
        invalid = sum(
            1
            for b in bars
            if any(
                v != v or v <= 0  # NaN check
                for v in (b.open, b.high, b.low, b.close)
            )
        )
        if invalid:
            logger.warning("%d bars with invalid OHLC for %s", invalid, args.symbol.upper())
        logger.info(
            "Last bar %s O=%.2f H=%.2f L=%.2f C=%.2f V=%.0f",
            last.ts.isoformat(),
            last.open,
            last.high,
            last.low,
            last.close,
            last.volume,
        )
    else:
        logger.warning("No candles in window (market may be closed) — token check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
