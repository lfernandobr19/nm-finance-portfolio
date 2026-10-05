"""Backtest the Quick Target swing (new entry + new exit) on historical daily bars.

Uses the same production entry (`build_hv_dip_setup`) and the Quick Target exit
rules (hard stop -> hard target -> time-stop), walking history bar-by-bar without
lookahead:

- Entry signal evaluated on bars[0..i]; position opened at bars[i].close.
- Intraday stop/target honoured with the next bars' low/high (OCO semantics).
- Otherwise the time-stop deadline (max_hold_days business days) closes at market.

This is the *signal quality* backtest: every valid signal is taken with a fixed
notional, so it ranks configs by edge per trade, not by capital allocation. Use
`_bt_portfolio.py` for the finite-capital / equal-risk equity curve vs QQQ.

Run from backend/:
    .venv/bin/python scripts/backtest_quick_target.py --tickers LCID RIOT AFRM UPST --days 500
    .venv/bin/python scripts/backtest_quick_target.py --all --days 500 --out report.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.market_data import MarketDataClient
from app.services.hv_dip.engine import build_hv_dip_setup
from app.services.hv_dip.exit_engine import compute_must_review_by
from app.services.hv_dip.universe import hv_dip_tickers


def _day(bar) -> datetime:
    """UTC midnight of a bar's date (aligns calendar and time-stop deadlines)."""
    d = getattr(bar, "date", None)
    if isinstance(d, datetime):
        dt = d
    elif d is not None:
        dt = datetime(d.year, d.month, d.day)
    else:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def run_ticker(
    ticker: str,
    bars: list,
    *,
    position_size: float,
    allow_review: bool,
    min_dip_pct: float | None,
) -> list[dict]:
    trades: list[dict] = []
    if len(bars) < 70:
        return trades

    open_trade: dict | None = None
    for i in range(70, len(bars) - 1):
        window = bars[: i + 1]
        if open_trade is None:
            setup = build_hv_dip_setup(ticker, window, min_dip_pct=min_dip_pct)
            if not setup:
                continue
            if setup.get("review_required") and not allow_review:
                continue
            opened_at = _day(bars[i])
            open_trade = {
                "entry": float(setup["entry"]),
                "stop": float(setup["stop"]),
                "target": float(setup["target"]),
                "dip_pct": float(setup["dip_pct"]),
                "entry_i": i,
                "opened_at": opened_at,
                "must_review_by": compute_must_review_by(opened_at),
            }
            continue

        b = bars[i]
        low = float(b.low)
        high = float(b.high)
        close = float(b.close)
        exit_px: float | None = None
        reason = "time_stop"

        # OCO semantics: stop and target rest at the broker and fill intraday.
        if low <= open_trade["stop"]:
            exit_px = open_trade["stop"]
            reason = "stop"
        elif high >= open_trade["target"]:
            exit_px = open_trade["target"]
            reason = "target"
        elif _day(b) >= open_trade["must_review_by"]:
            exit_px = close
            reason = "time_stop"

        if exit_px is not None:
            pnl_pct = (exit_px - open_trade["entry"]) / open_trade["entry"] * 100.0
            trades.append(
                {
                    "ticker": ticker,
                    "entry": round(open_trade["entry"], 2),
                    "exit": round(exit_px, 2),
                    "reason": reason,
                    "pnl_pct": round(pnl_pct, 2),
                    "pnl_usd": round(pnl_pct / 100.0 * position_size, 2),
                    "dip_pct": open_trade["dip_pct"],
                    "hold_days": i - open_trade["entry_i"],
                    "opened_date": open_trade["opened_at"].date().isoformat(),
                }
            )
            open_trade = None

    # Mark-to-market any still-open trade at the last close.
    if open_trade is not None:
        mark = float(bars[-1].close)
        pnl_pct = (mark - open_trade["entry"]) / open_trade["entry"] * 100.0
        trades.append(
            {
                "ticker": ticker,
                "entry": round(open_trade["entry"], 2),
                "exit": round(mark, 2),
                "reason": "open",
                "pnl_pct": round(pnl_pct, 2),
                "pnl_usd": round(pnl_pct / 100.0 * position_size, 2),
                "dip_pct": open_trade["dip_pct"],
                "hold_days": len(bars) - 1 - open_trade["entry_i"],
                "opened_date": open_trade["opened_at"].date().isoformat(),
            }
        )
    return trades


def _stats(trades: list[dict]) -> dict:
    if not trades:
        return {"trades": 0}
    pcts = [t["pnl_pct"] for t in trades]
    pnls = [t["pnl_usd"] for t in trades]
    wins = [p for p in pcts if p > 0]
    losses = [p for p in pcts if p < 0]
    gross_win = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))

    eq = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)

    by_reason: dict[str, list[float]] = {}
    for t in trades:
        by_reason.setdefault(t["reason"], []).append(t["pnl_pct"])

    return {
        "trades": len(trades),
        "win_rate_pct": round(len(wins) / len(pcts) * 100.0, 1),
        "avg_return_pct": round(statistics.fmean(pcts), 2),
        "median_return_pct": round(statistics.median(pcts), 2),
        "total_pnl_usd": round(sum(pnls), 2),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
        "max_drawdown_usd": round(max_dd, 2),
        "avg_hold_days": round(statistics.fmean([t["hold_days"] for t in trades]), 1),
        "avg_dip_pct": round(statistics.fmean([t["dip_pct"] for t in trades]), 2),
        "by_reason": {
            k: {"n": len(v), "avg_return_pct": round(statistics.fmean(v), 2)}
            for k, v in by_reason.items()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", nargs="*", default=[])
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--days", type=int, default=500)
    parser.add_argument("--size", type=float, default=100.0, help="notional per trade (USD)")
    parser.add_argument("--min-dip", type=float, default=None, help="override min dip percent")
    parser.add_argument("--allow-review", action="store_true")
    parser.add_argument("--out", default=None, help="optional JSON output path")
    args = parser.parse_args()

    tickers = [t.upper() for t in args.tickers]
    if args.all or not tickers:
        tickers = hv_dip_tickers()

    client = MarketDataClient()
    print(f"Fetching {args.days}d bars for {len(tickers)} tickers ...")
    bars_map = client.fetch_daily_bars_many(tickers, days=args.days)

    all_trades: list[dict] = []
    per_ticker: dict[str, dict] = {}
    for t in tickers:
        bars = bars_map.get(t) or []
        trades = run_ticker(
            t,
            bars,
            position_size=args.size,
            allow_review=args.allow_review,
            min_dip_pct=args.min_dip,
        )
        all_trades.extend(trades)
        per_ticker[t] = _stats(trades)
        if trades:
            print(f"  {t}: {_stats(trades)}")

    print("\n=== AGGREGATE ===")
    print(json.dumps(_stats(all_trades), indent=2))

    if args.out:
        report = {
            "config": {
                "days": args.days,
                "size": args.size,
                "allow_review": args.allow_review,
                "min_dip_pct": args.min_dip,
            },
            "aggregate": _stats(all_trades),
            "per_ticker": per_ticker,
            "trades": all_trades,
        }
        Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nReport saved to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
