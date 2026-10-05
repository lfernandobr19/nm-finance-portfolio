"""Validate hv_dip universe tickers against Yahoo/Alpaca OHLC fetch."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.market_data import MarketDataClient
from app.services.hv_dip.universe import hv_dip_tickers


def main() -> None:
    client = MarketDataClient()
    ok: list[str] = []
    bad: list[str] = []
    for ticker in hv_dip_tickers():
        bars = client.fetch_daily_bars(ticker, force=True)
        if len(bars) >= 40:
            ok.append(ticker)
            print(f"OK  {ticker:6} bars={len(bars)} close={bars[-1].close:.2f}")
        else:
            bad.append(ticker)
            print(f"BAD {ticker:6} bars={len(bars)}")
    print(f"\n{len(ok)} ok, {len(bad)} failed")
    if bad:
        sys.exit(1)


if __name__ == "__main__":
    main()
