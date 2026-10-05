"""Walk-forward do sistema rotacional (teste fora da amostra).

Divide a série ao meio:
  - IN-SAMPLE (1a metade): varre as configs, escolhe a melhor.
  - OUT-OF-SAMPLE (2a metade): aplica SÓ a melhor config escolhida.

Se a melhor config do in-sample continuar batendo buy-and-hold no out-of-sample
sem ter visto esses dados, o edge é menos provável de ser overfitting.

Run from backend/:
    py scripts/_bt_megacap_wf.py --days 730
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
) -> tuple[float, int]:
    tickers = list(series.keys())
    n = min(len(c) for c in series.values())
    if n < lookback + 2:
        return 1.0, 0

    equity = 1.0
    entry: float | None = None
    held: str | None = None
    peak: float = 0.0
    trades = 0

    for i in range(lookback, n):
        if held is not None:
            c = series[held][i]
            peak = max(peak, c)
            if c <= peak * (1.0 - giveback_pct / 100.0):
                equity *= c / entry
                entry = None
                held = None
                peak = 0.0

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
                    continue
                if dip > best_dip:
                    best_dip = dip
                    best = t
            if best is not None:
                entry = series[best][i]
                held = best
                peak = entry
                trades += 1

    if held is not None:
        equity *= series[held][n - 1] / entry
    return equity, trades


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=730)
    args = ap.parse_args()

    client = MarketDataClient()
    tickers = MEGA
    bars_map = client.fetch_daily_bars_many(tickers + ["QQQ"], days=args.days)
    series = {t: close_series(bars_map.get(t) or []) for t in tickers}
    series = {t: c for t, c in series.items() if len(c) >= 240}
    tickers = list(series.keys())

    qqq_c = close_series(bars_map.get("QQQ") or [])
    n = min(len(c) for c in series.values())
    half = n // 2

    def slice_half(a: int, b: int) -> dict[str, list[float]]:
        # give each half enough warmup by starting earlier but evaluating on [a:b]
        return {t: c[a:b] for t, c in series.items()}

    ins = slice_half(0, half)
    oos = slice_half(half, n)

    grid = [
        (dip, gb, lb, cf)
        for dip in (3.0, 5.0, 8.0)
        for gb in (2.0, 3.0, 5.0, 8.0)
        for lb in (20, 60)
        for cf in (False, True)
    ]

    # 1) pick best config in-sample
    best = None
    best_ret = -1e9
    for cfg in grid:
        r, _ = rotation_backtest(ins, dip_pct=cfg[0], giveback_pct=cfg[1], lookback=cfg[2], confirm=cfg[3])
        if r > best_ret:
            best_ret = r
            best = cfg

    # 2) apply to out-of-sample
    oos_ret, oos_trades = rotation_backtest(
        oos, dip_pct=best[0], giveback_pct=best[1], lookback=best[2], confirm=best[3]
    )

    # buy-and-hold baselines on the SAME halves
    bh_ins = statistics.fmean(buy_hold(c[:half]) for c in series.values())
    bh_oos = statistics.fmean(buy_hold(c[half:]) for c in series.values())
    qqq_oos = buy_hold(qqq_c[half:]) if len(qqq_c) > half else 1.0

    print(f"Universo: {tickers}")
    print(f"\nIN-SAMPLE (1a metade, ~{half} dias):")
    print(f"  melhor config: dip={best[0]}% giveback={best[1]}% lookback={best[2]} confirm={best[3]}")
    print(f"  retorno in-sample: {(best_ret-1)*100:+.1f}%")
    print(f"  buy-and-hold gigantes: {(bh_ins-1)*100:+.1f}%")

    print(f"\nOUT-OF-SAMPLE (2a metade, ~{n-half} dias) — modelo NUNCA viu estes dados:")
    print(f"  retorno do sistema: {(oos_ret-1)*100:+.1f}%  ({oos_trades} trades)")
    print(f"  buy-and-hold gigantes: {(bh_oos-1)*100:+.1f}%")
    print(f"  QQQ: {(qqq_oos-1)*100:+.1f}%")
    print(f"  DIFERENÇA vs BH gigantes: {(oos_ret-bh_oos)*100:+.1f} pts")
    print(f"  DIFERENÇA vs QQQ: {(oos_ret-qqq_oos)*100:+.1f} pts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
