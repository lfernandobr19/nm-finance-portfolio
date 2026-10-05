"""Offline anti-look-ahead backtest for the hv_dip news catalyst.

Replays classified NewsEvent rows and simulates entering on the *next* daily bar
(no look-ahead) with a fixed stop/2R target, then compares:
  - bullish whitelisted events (catalyst signal)
  - all events (baseline)
to measure whether the news classifier adds edge.

Usage (from backend/):
    PYTHONPATH=. python scripts/hv_dip_news_backtest.py --tickers AMZN,NVDA,AMD,TSLA
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.domain.models import NewsEvent
from app.services.market_data import MarketDataClient

settings = get_settings()

STOP_PCT = 12.0
MAX_HOLD_DAYS = 14


def _whitelist() -> set[str]:
    return {t.strip().lower() for t in settings.news_event_whitelist.split(",") if t.strip()}


def simulate(bars, entry_idx: int) -> dict:
    """Walk forward from entry_idx; returns (win, r_multiple, days_held)."""
    if entry_idx < 0 or entry_idx >= len(bars):
        return {"win": False, "r": 0.0, "days": 0}
    entry = float(bars[entry_idx].open)
    if entry <= 0:
        return {"win": False, "r": 0.0, "days": 0}
    stop = entry * (1.0 - STOP_PCT / 100.0)
    risk = entry - stop
    target = entry + 2.0 * risk
    for i in range(entry_idx, min(entry_idx + MAX_HOLD_DAYS, len(bars))):
        b = bars[i]
        if float(b.low) <= stop:
            return {"win": False, "r": -1.0, "days": i - entry_idx}
        if float(b.high) >= target:
            return {"win": True, "r": 2.0, "days": i - entry_idx}
    last_close = float(bars[min(entry_idx + MAX_HOLD_DAYS, len(bars)) - 1].close)
    r = (last_close - entry) / risk if risk else 0.0
    return {"win": r > 0, "r": round(r, 2), "days": MAX_HOLD_DAYS}


def run(db, tickers: list[str]) -> dict:
    client = MarketDataClient()
    whitelist = _whitelist()
    events = db.query(NewsEvent).filter(NewsEvent.processed_at.is_not(None)).all()

    rows = {"catalyst": [], "baseline": []}
    for ev in events:
        ticker = (ev.ticker or "").upper()
        if not ticker or (tickers and ticker not in tickers):
            continue
        bars = client.fetch_daily_bars(ticker)
        if not bars or ev.published_at is None:
            continue
        # First bar strictly AFTER the news timestamp (anti-look-ahead).
        entry_idx = next((i for i, b in enumerate(bars) if b.date > ev.published_at), None)
        if entry_idx is None:
            continue
        result = simulate(bars, entry_idx)
        result["ticker"] = ticker
        result["event_type"] = ev.event_type
        result["sentiment"] = ev.sentiment

        is_catalyst = (
            ev.sentiment == "bullish"
            and (ev.event_type or "") in whitelist
            and (ev.confidence or 0) >= float(settings.news_confidence_min)
        )
        rows["catalyst" if is_catalyst else "baseline"].append(result)

    return rows


def _report(label: str, results: list[dict]) -> None:
    if not results:
        print(f"[{label}] 0 trades")
        return
    n = len(results)
    wins = sum(1 for r in results if r["win"])
    avg_r = sum(r["r"] for r in results) / n
    print(
        f"[{label}] n={n} win_rate={wins / n:.1%} "
        f"avg_R={avg_r:+.2f} expectancy={avg_r:+.2f}R"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", default="", help="comma-separated filter (empty = all)")
    args = parser.parse_args()

    tickers = {t.strip().upper() for t in args.tickers.split(",") if t.strip()}

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        rows = run(db, tickers)
    finally:
        db.close()

    _report("catalyst (bullish whitelisted)", rows["catalyst"])
    _report("baseline (all classified)", rows["baseline"])
    print("Anti-look-ahead: entrada na barra seguinte ao evento. STOP 12% / 2R / 14d.")


if __name__ == "__main__":
    main()
