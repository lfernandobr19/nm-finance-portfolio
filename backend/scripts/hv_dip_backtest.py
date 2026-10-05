"""Offline walk-forward backtest for NM High-Vol Dip (Yahoo/Alpaca OHLC)."""

from __future__ import annotations

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.services.market_data import MarketDataClient
from app.services.brapi_client import Bar
from app.services.hv_dip.indicators import (
    atr_pct,
    dip_pct_from_high,
    is_52w_low,
    recent_high,
    recent_low,
    volume_vs_sma,
    weekly_range_pct,
)
from app.services.hv_dip.score import HvDipSignals, score_hv_dip
from app.services.hv_dip.universe import hv_dip_tickers

settings = get_settings()


def _analyze_slice(bars: list[Bar], ticker: str) -> dict | None:
    lookback = int(settings.hv_dip_lookback or 10)
    dip_need = float(settings.hv_dip_dip_pct or 8.0)
    hard_y = float(settings.hv_dip_hard_stop_pct or 12.0)

    if len(bars) < max(40, lookback + 5):
        return None

    dip = dip_pct_from_high(bars, lookback)
    if dip is None or dip < 6.0:
        return None

    hi = recent_high(bars, lookback)
    setup_low = recent_low(bars, lookback)
    if hi is None or setup_low is None:
        return None

    entry = round(float(bars[-1].close), 2)
    if entry < setup_low * 0.995 and not is_52w_low(bars):
        return None

    stop_struct = round(setup_low * 0.995, 2)
    stop_hard = round(entry * (1.0 - hard_y / 100.0), 2)
    stop = round(min(stop_struct, stop_hard), 2)
    if stop >= entry:
        stop = round(entry * (1.0 - hard_y / 100.0), 2)
    risk = entry - stop
    target = round(entry + 2.0 * risk, 2)

    atrp = atr_pct(bars, 14)
    volr = volume_vs_sma(bars, 20)
    wr = weekly_range_pct(bars)
    review = is_52w_low(bars)

    if wr is not None and wr < 3.0 and (atrp or 0) < 2.0:
        return None

    scored = score_hv_dip(
        HvDipSignals(
            dip_pct=dip,
            atr_pct=atrp,
            volume_ratio=volr,
            entry=entry,
            stop=stop,
            target=target,
            review_required=review,
            review_reason=None,
        )
    )
    if not scored:
        return None
    if dip < dip_need and scored.letter != "C":
        pass

    return {
        "ticker": ticker,
        "date": bars[-1].date,
        "letter": scored.letter,
        "entry": entry,
        "stop": stop,
        "target": target,
        "dip_pct": round(dip, 2),
    }


def _walk_outcome(bars: list[Bar], start_idx: int, entry: float, stop: float, target: float) -> tuple[str, int]:
    for j in range(start_idx + 1, len(bars)):
        b = bars[j]
        if b.low <= stop:
            return "stop", j - start_idx
        if b.high >= target:
            return "target", j - start_idx
    return "open", len(bars) - 1 - start_idx


def backtest_ticker(client: MarketDataClient, ticker: str) -> list[dict]:
    bars = client.fetch_daily_bars(ticker, force=True, days=400)
    if len(bars) < 80:
        return []

    trades: list[dict] = []
    i = 60
    while i < len(bars) - 1:
        slice_bars = bars[: i + 1]
        sig = _analyze_slice(slice_bars, ticker)
        if not sig:
            i += 1
            continue
        outcome, hold = _walk_outcome(bars, i, sig["entry"], sig["stop"], sig["target"])
        risk = sig["entry"] - sig["stop"]
        r_mult = 0.0
        if risk > 0:
            if outcome == "target":
                r_mult = (sig["target"] - sig["entry"]) / risk
            elif outcome == "stop":
                r_mult = (sig["stop"] - sig["entry"]) / risk
        trades.append(
            {
                **sig,
                "date": str(sig["date"].date() if hasattr(sig["date"], "date") else sig["date"]),
                "outcome": outcome,
                "hold_days": hold,
                "r_multiple": round(r_mult, 2),
            }
        )
        i += max(hold, 5)
    return trades


def main() -> None:
    client = MarketDataClient()
    out_path = Path("hv_dip_backtest.csv")
    all_trades: list[dict] = []

    for ticker in hv_dip_tickers():
        try:
            trades = backtest_ticker(client, ticker)
            all_trades.extend(trades)
            for t in trades:
                print(
                    f"{t['ticker']:6} {t['date']} {t['letter']} "
                    f"dip={t['dip_pct']:.1f}% → {t['outcome']} "
                    f"hold={t['hold_days']}d R={t['r_multiple']:.2f}"
                )
        except Exception as exc:
            print(f"{ticker}: ERROR {exc}", file=sys.stderr)

    if not all_trades:
        print("No historical setups found")
        sys.exit(1)

    fields = [
        "ticker",
        "date",
        "letter",
        "entry",
        "stop",
        "target",
        "dip_pct",
        "outcome",
        "hold_days",
        "r_multiple",
    ]
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(all_trades)

    n = len(all_trades)
    targets = sum(1 for r in all_trades if r["outcome"] == "target")
    stops = sum(1 for r in all_trades if r["outcome"] == "stop")
    avg_hold = sum(int(r["hold_days"]) for r in all_trades) / n
    avg_r = sum(float(r["r_multiple"]) for r in all_trades) / n
    print(
        f"\nWrote {out_path} — setups={n} target={targets} ({100*targets/n:.0f}%) "
        f"stop={stops} ({100*stops/n:.0f}%) avg_hold={avg_hold:.0f}d avg_R={avg_r:.2f}"
    )
    print(f"Generated {datetime.now(timezone.utc).isoformat()}")


if __name__ == "__main__":
    main()
