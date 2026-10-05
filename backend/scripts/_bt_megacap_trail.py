"""Backtest do SISTEMA REAL do usuário: comprar na baixa + trailing stop.

Conceito (diferente do teste anterior): NÃO vende com alvo fixo de +X%.
Compra após uma queda (buy the dip) e SEGURA enquanto valoriza; vende quando o
preço começa a cair de novo — um giveback (stop móvel) abaixo do pico desde a
entrada. "Tirar o máximo da valorização e evitar as quedas."

Mecânica (sem lookahead, closes diários):
  - flat -> long: close[i] <= high(close[i-lookback:i]) * (1 - dip%)
  - long -> flat: close[i] <= peak_desde_entrada * (1 - giveback%)
  - entrada/saída ao close do dia; peak atualizado a cada dia long.

Compara contra buy-and-hold das mesmas gigantes e do QQQ.

Run from backend/:
    py scripts/_bt_megacap_trail.py --days 730
"""
from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.market_data import MarketDataClient

MEGA = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"]


def close_series(bars: list) -> list[float]:
    return [float(b.close) for b in bars]


def buy_dip_trailing(
    closes: list[float], *, dip_pct: float, giveback_pct: float, lookback: int
) -> tuple[float, int, list[float]]:
    """Compounded return of buy-dip + trailing-stop. Returns (multiple, trades, equity_curve)."""
    n = len(closes)
    equity_curve: list[float] = []
    if n < lookback + 2:
        return 1.0, 0, [1.0]
    equity = 1.0
    entry: float | None = None
    peak: float = 0.0
    trades = 0
    for i in range(lookback, n):
        c = closes[i]
        if entry is None:
            high = max(closes[i - lookback : i])
            if high > 0 and c <= high * (1.0 - dip_pct / 100.0):
                entry = c
                peak = c
                trades += 1
        else:
            peak = max(peak, c)
            if c <= peak * (1.0 - giveback_pct / 100.0):
                equity *= c / entry
                entry = None
        equity_curve.append(equity * (closes[i] / entry) if entry is not None else equity)
    if entry is not None:
        equity *= closes[-1] / entry
        entry = None
    return equity, trades, equity_curve


def buy_hold(closes: list[float]) -> float:
    return closes[-1] / closes[0] if closes and closes[0] else 1.0


def max_drawdown(curve: list[float]) -> float:
    peak = 0.0
    dd = 0.0
    for v in curve:
        peak = max(peak, v)
        dd = max(dd, peak - v)
    return dd / peak if peak else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=730)
    ap.add_argument("--tickers", nargs="*", default=[])
    args = ap.parse_args()

    tickers = [t.upper() for t in (args.tickers or MEGA)]
    client = MarketDataClient()
    print(f"Fetching {args.days}d bars for {tickers + ['QQQ']} ...")
    bars_map = client.fetch_daily_bars_many(tickers + ["QQQ"], days=args.days)

    bh = {t: buy_hold(close_series(bars_map.get(t) or [])) for t in tickers}
    qqq_c = close_series(bars_map.get("QQQ") or [])
    qqq_bh = buy_hold(qqq_c) if qqq_c else 1.0
    bh_avg = statistics.fmean(bh.values())

    print("\nBuy-and-hold (período):")
    for t in tickers:
        print(f"  {t}: {(bh[t]-1)*100:+.1f}%")
    print(f"  QQQ: {(qqq_bh-1)*100:+.1f}%")
    print(f"  equal-weight gigantes: {(bh_avg-1)*100:+.1f}%")

    grid = [
        (dip, gb, lb)
        for dip in (3.0, 5.0, 8.0, 10.0)
        for gb in (2.0, 3.0, 5.0, 8.0, 10.0)
        for lb in (20, 60)
    ]

    print("\n=== BUY DIP + TRAILING STOP (sai quando começa a cair) ===")
    print(f"{'dip%':>5} {'givebk%':>7} {'lookbk':>6} {'ret%':>9} {'vs BH gig':>10} {'vs QQQ':>9} {'#>=BH':>6} {'maxDD':>7}")
    results = []
    for dip, gb, lb in grid:
        rets = []
        beat_bh = 0
        curves_merged: list[float] = []
        for t in tickers:
            c = close_series(bars_map.get(t) or [])
            if not c:
                rets.append(1.0)
                continue
            r, _tr, curve = buy_dip_trailing(c, dip_pct=dip, giveback_pct=gb, lookback=lb)
            rets.append(r)
            curves_merged.extend(curve)
            if r >= bh[t]:
                beat_bh += 1
        avg = statistics.fmean(rets)
        dd = max_drawdown(curves_merged)
        results.append((avg, dip, gb, lb, beat_bh, dd))
        print(
            f"{dip:>5.1f} {gb:>7.1f} {lb:>6d} {(avg-1)*100:>+9.1f} "
            f"{(avg - bh_avg)*100:>+10.1f} {(avg - qqq_bh)*100:>+9.1f} "
            f"{beat_bh:>6d}/{len(tickers)} {dd*100:>6.1f}%"
        )

    if results:
        results.sort(reverse=True)
        best = results[0]
        print("\nMelhor config:")
        print(
            f"  dip={best[1]}% giveback={best[2]}% lookback={best[3]} "
            f"ret={(best[0]-1)*100:+.1f}% maxDD={best[5]*100:.1f}% "
            f"(bate BH gig em {best[4]}/{len(tickers)} tickers)"
        )
        print(f"  BH gigantes: {(bh_avg-1)*100:+.1f}% | QQQ: {(qqq_bh-1)*100:+.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
