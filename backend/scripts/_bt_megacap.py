"""Backtest do SISTEMA do usuário: buy low / sell high em MEGA-CAPS líquidas.

Hipótese do usuário: comprar na queda e vender na alta de gigantes (Tesla,
Nvidia, Apple, Microsoft, Amazon, Google, Meta) — curto prazo, "negando as
baixas" — gera lucro consistente.

Este script isola a variável que os backtests anteriores NÃO testaram: o
UNIVERSO (gigantes líquidas) em vez das especulativas (LCID/RIOT/U).

Regra mecânica (proxy da discrição do usuário):
  - lookback high: máxima dos últimos N pregões
  - BUY  quando flat e close caiu >= dip% daquela máxima (compra na baixa)
  - SELL quando long e close subiu >= gain% do entry (vende na alta)
  - sem stop; sempre sai com lucro ou segura (espelha "nunca perdi dinheiro")

Compara contra:
  1. buy-and-hold equal-weight das MESMAS gigantes
  2. buy-and-hold do QQQ

Run from backend/:
    py scripts/_bt_megacap.py --days 730
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


def buy_low_sell_high(closes: list[float], *, dip_pct: float, gain_pct: float, lookback: int) -> float:
    """Compounded return of the dip-buy / gain-sell rule on one ticker.

    State machine: flat -> long -> flat. Buys at close after a dip; sells at
    close after a gain. Compounded, no leverage. Returns cumulative multiple
    (1.0 = no change).
    """
    if len(closes) < lookback + 2:
        return 1.0
    equity = 1.0
    entry: float | None = None
    for i in range(lookback, len(closes)):
        high = max(closes[i - lookback : i])
        c = closes[i]
        if entry is None:
            if high > 0 and c <= high * (1.0 - dip_pct / 100.0):
                entry = c
        else:
            if c >= entry * (1.0 + gain_pct / 100.0):
                equity *= c / entry
                entry = None
    # still long at end: mark to market at last close
    if entry is not None:
        equity *= closes[-1] / entry
    return equity


def buy_hold(closes: list[float]) -> float:
    return closes[-1] / closes[0] if closes and closes[0] else 1.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=730)
    ap.add_argument("--tickers", nargs="*", default=[])
    args = ap.parse_args()

    tickers = [t.upper() for t in (args.tickers or MEGA)]
    client = MarketDataClient()
    print(f"Fetching {args.days}d bars for {tickers + ['QQQ']} ...")
    bars_map = client.fetch_daily_bars_many(tickers + ["QQQ"], days=args.days)

    # Buy-and-hold baselines
    bh = {}
    for t in tickers:
        c = close_series(bars_map.get(t) or [])
        bh[t] = buy_hold(c) if c else 1.0
    qqq_c = close_series(bars_map.get("QQQ") or [])
    qqq_bh = buy_hold(qqq_c) if qqq_c else 1.0

    print("\nBuy-and-hold (período):")
    for t in tickers:
        print(f"  {t}: {(bh[t]-1)*100:+.1f}%")
    print(f"  QQQ: {(qqq_bh-1)*100:+.1f}%")
    print(f"  equal-weight gigantes: {(statistics.fmean(bh.values())-1)*100:+.1f}%")

    grid = [
        (dip, gain, lookback)
        for dip in (3.0, 5.0, 8.0, 10.0)
        for gain in (2.0, 3.0, 5.0, 8.0)
        for lookback in (20, 60)
    ]

    print("\n=== BUY LOW / SELL HIGH (varredura) ===")
    print(f"{'dip%':>5} {'gain%':>6} {'lookbk':>6} {'ret%':>9} {'vs BH gig':>10} {'vs QQQ':>9} {'#>=BH':>6}")
    results = []
    for dip, gain, lb in grid:
        rets = []
        beat_bh = 0
        for t in tickers:
            c = close_series(bars_map.get(t) or [])
            if not c:
                rets.append(1.0)
                continue
            r = buy_low_sell_high(c, dip_pct=dip, gain_pct=gain, lookback=lb)
            rets.append(r)
            if r >= bh[t]:
                beat_bh += 1
        avg = statistics.fmean(rets)
        results.append((avg, dip, gain, lb, beat_bh))
        print(
            f"{dip:>5.1f} {gain:>6.1f} {lb:>6d} {(avg-1)*100:>+9.1f} "
            f"{(avg - statistics.fmean(bh.values()))*100:>+10.1f} "
            f"{(avg - qqq_bh)*100:>+9.1f} {beat_bh:>6d}/{len(tickers)}"
        )

    if results:
        results.sort(reverse=True)
        best = results[0]
        print("\nMelhor config:")
        print(
            f"  dip={best[1]}% gain={best[2]}% lookback={best[3]} "
            f"ret={(best[0]-1)*100:+.1f}% (bate BH gig em {best[4]}/{len(tickers)} tickers)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
