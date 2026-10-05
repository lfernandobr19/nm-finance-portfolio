"""Backtest ROTACIONAL do sistema do usuário (o teste certo).

Conceito real (diferente dos testes anteriores por-ticker):
  UM ÚNICO CAIXA que gira entre os alvos. Quando flat, procura o ticker mais
  "em promoção" (maior queda da máxima recente) E que começou a virar para cima;
  compra. Segura enquanto valoriza; vende no trailing stop (quando começa a cair
  de novo) e IMEDIATAMENTE procura o próximo alvo. Pode recomprar o mesmo ticker
  quando ele der sinal de novo ("quando valorizar de novo, compro de novo").

Mecânica (sem lookahead, closes diários, caixa único normalizado em 1.0):
  - flat: candidatos = tickers com close <= high(lookback)*(1-dip%)
          e (se confirm) close[i] > close[i-1]  (virou para cima)
          escolhe o de MAIOR queda (mais descontado); compra ao close.
  - long: atualiza pico; vende ao close se close <= pico*(1-giveback%).
  - reentrada imediata no próximo dia/sinal, inclusive no mesmo ticker.

Compara contra buy-and-hold equal-weight das mesmas gigantes e QQQ.

Run from backend/:
    py scripts/_bt_megacap_rotate.py --days 730
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


def buy_hold(closes: list[float]) -> float:
    return closes[-1] / closes[0] if closes and closes[0] else 1.0


def rotation_backtest(
    series: dict[str, list[float]],
    *,
    dip_pct: float,
    giveback_pct: float,
    lookback: int,
    confirm: bool,
) -> tuple[float, int, list[float], float]:
    """Rotational single-cash backtest. Returns (multiple, trades, curve, time_in_market)."""
    tickers = list(series.keys())
    # align lengths (all series same length)
    n = min(len(c) for c in series.values())
    if n < lookback + 2:
        return 1.0, 0, [1.0], 0.0

    equity = 1.0
    entry: float | None = None
    held: str | None = None
    peak: float = 0.0
    trades = 0
    days_in = 0
    curve: list[float] = []

    for i in range(lookback, n):
        # First, if long, check trailing stop using today's close.
        if held is not None:
            c = series[held][i]
            peak = max(peak, c)
            if c <= peak * (1.0 - giveback_pct / 100.0):
                equity *= c / entry
                entry = None
                held = None
                peak = 0.0
            else:
                days_in += 1

        # Now, if flat, look for the next entry.
        if held is None:
            best = None
            best_dip = 0.0
            for t in tickers:
                c = series[t][i]
                high = max(series[t][i - lookback : i])
                if high <= 0:
                    continue
                dip = (high - c) / high * 100.0
                if dip < dip_pct:
                    continue
                if confirm and i >= 1 and c <= series[t][i - 1]:
                    continue  # still falling today; wait for the turn
                if dip > best_dip:
                    best_dip = dip
                    best = t
            if best is not None:
                entry = series[best][i]
                held = best
                peak = entry
                trades += 1
                days_in += 1

        # Mark to market: equity * current held value.
        curve.append(equity * (series[held][i] / entry) if held is not None else equity)

    if held is not None:
        equity *= series[held][n - 1] / entry
    return equity, trades, curve, days_in / n


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

    series = {t: close_series(bars_map.get(t) or []) for t in tickers}
    # Drop tickers with too little history (e.g. TSLA Yahoo fallback returning 1 bar).
    series = {t: c for t, c in series.items() if len(c) >= 120}
    tickers = list(series.keys())
    bh = {t: buy_hold(series[t]) for t in tickers}
    qqq_c = close_series(bars_map.get("QQQ") or [])
    qqq_bh = buy_hold(qqq_c) if qqq_c else 1.0
    bh_avg = statistics.fmean(bh.values())

    print("\nBuy-and-hold (período):")
    for t in tickers:
        print(f"  {t}: {(bh[t]-1)*100:+.1f}%")
    print(f"  QQQ: {(qqq_bh-1)*100:+.1f}%")
    print(f"  equal-weight gigantes: {(bh_avg-1)*100:+.1f}%")

    grid = [
        (dip, gb, lb, cf)
        for dip in (3.0, 5.0, 8.0)
        for gb in (2.0, 3.0, 5.0, 8.0)
        for lb in (20, 60)
        for cf in (False, True)
    ]

    print("\n=== ROTACIONAL: caixa único girando entre os alvos ===")
    print(
        f"{'dip%':>5} {'givebk%':>7} {'lookbk':>6} {'conf':>5} {'ret%':>9} "
        f"{'vs BH gig':>10} {'vs QQQ':>9} {'trades':>7} {'%inMkt':>7} {'maxDD':>7}"
    )
    results = []
    for dip, gb, lb, cf in grid:
        r, tr, curve, in_mkt = rotation_backtest(
            series, dip_pct=dip, giveback_pct=gb, lookback=lb, confirm=cf
        )
        dd = max_drawdown(curve)
        results.append((r, dip, gb, lb, cf, tr, in_mkt, dd))
        print(
            f"{dip:>5.1f} {gb:>7.1f} {lb:>6d} {str(cf):>5} {(r-1)*100:>+9.1f} "
            f"{(r - bh_avg)*100:>+10.1f} {(r - qqq_bh)*100:>+9.1f} "
            f"{tr:>7d} {in_mkt*100:>6.1f}% {dd*100:>6.1f}%"
        )

    if results:
        results.sort(reverse=True)
        best = results[0]
        print("\nMelhor config:")
        print(
            f"  dip={best[1]}% giveback={best[2]}% lookback={best[3]} confirm={best[4]} "
            f"ret={(best[0]-1)*100:+.1f}% trades={best[5]} in_mkt={best[6]*100:.0f}% "
            f"maxDD={best[7]*100:.1f}%"
        )
        print(f"  BH gigantes: {(bh_avg-1)*100:+.1f}% | QQQ: {(qqq_bh-1)*100:+.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
