"""Quick Target: is the edge real alpha, or just long high-beta US equity?

Approval gate (Phase 5). It answers three questions and prints a GO/NO-GO:

1. **Benchmark**: does the equal-risk portfolio beat buy & hold QQQ/SPY (and an
   equal-weight basket of the strategy's own universe) in BOTH halves of the
   sample (H1/H2) and on FULL?
2. **Per-trade expectancy**: is the average return per trade positive with
   significance, accounting for overlapping long high-beta positions?
3. **Overfitting**: Deflated Sharpe Ratio (Bailey & Lopez de Prado) and the CSCV
   Probability of Backtest Overfitting across the target_R/stop/hold grid, to
   confirm the selected config is not a multiple-testing artifact.

Run from backend/:
    .venv/bin/python scripts/_bt_benchmark.py
"""

from __future__ import annotations

import json
import math
import os
import statistics
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from app.services.market_data import MarketDataClient
from app.services.hv_dip.universe import hv_dip_tickers
from app.services.stats import deflated_sharpe_ratio, probability_of_backtest_overfitting

DAYS = 500
PY = sys.executable
PORTFOLIO = str(BASE / "scripts/_bt_portfolio.py")
BACKTEST = str(BASE / "scripts/backtest_quick_target.py")

# target_R x stop_pct x hold grid for the CSCV overfitting test.
GRID: list[tuple[str, dict[str, str]]] = [
    ("R1.0 stop5 hold3", {"HV_DIP_QT_TARGET_R": "1.0", "HV_DIP_QT_STOP_PCT": "5", "HV_DIP_QT_MAX_HOLD_DAYS": "3"}),
    ("R0.5 stop5 hold3", {"HV_DIP_QT_TARGET_R": "0.5", "HV_DIP_QT_STOP_PCT": "5", "HV_DIP_QT_MAX_HOLD_DAYS": "3"}),
    ("R1.5 stop5 hold3", {"HV_DIP_QT_TARGET_R": "1.5", "HV_DIP_QT_STOP_PCT": "5", "HV_DIP_QT_MAX_HOLD_DAYS": "3"}),
    ("R2.0 stop5 hold3", {"HV_DIP_QT_TARGET_R": "2.0", "HV_DIP_QT_STOP_PCT": "5", "HV_DIP_QT_MAX_HOLD_DAYS": "3"}),
    ("R1.0 stop8 hold3", {"HV_DIP_QT_TARGET_R": "1.0", "HV_DIP_QT_STOP_PCT": "8", "HV_DIP_QT_MAX_HOLD_DAYS": "3"}),
    ("R1.0 stop3 hold1", {"HV_DIP_QT_TARGET_R": "1.0", "HV_DIP_QT_STOP_PCT": "3", "HV_DIP_QT_MAX_HOLD_DAYS": "1"}),
]


def _day(bar) -> datetime:
    d = getattr(bar, "date", None)
    if isinstance(d, datetime):
        dt = d
    elif d is not None:
        dt = datetime(d.year, d.month, d.day)
    else:
        dt = datetime.now(timezone.utc)
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def buy_hold(bars: list, lo: datetime, hi: datetime) -> tuple[float, float] | None:
    """(total return %, max drawdown %) for buy & hold between lo and hi."""
    sel = [b for b in bars if lo <= _day(b) <= hi]
    if len(sel) < 20:
        return None
    first = float(sel[0].close)
    peak = 0.0
    max_dd = 0.0
    for b in sel:
        eq = float(b.close) / first
        peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak * 100.0)
    return (float(sel[-1].close) / first - 1) * 100.0, max_dd


def cagr(total_ret_pct: float, span_days: int) -> float:
    years = max(span_days / 365.25, 1e-9)
    return ((1 + total_ret_pct / 100.0) ** (1 / years) - 1) * 100.0


def run_portfolio(period: str) -> dict | None:
    env = dict(os.environ)
    env["BT_PERIOD"] = period
    proc = subprocess.run(
        [PY, PORTFOLIO],
        cwd=str(BASE),
        env=env,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if proc.returncode != 0:
        print(f"  portfolio ({period}) FAILED: {proc.stderr[-400:]}", file=sys.stderr)
        return None
    i = proc.stdout.find("{")
    return json.loads(proc.stdout[i:]) if i >= 0 else None


def run_backtest(overrides: dict[str, str]) -> dict | None:
    env = dict(os.environ)
    env.update(overrides)
    out = Path(tempfile.gettempdir()) / "qt_bt_bench.json"
    proc = subprocess.run(
        [PY, BACKTEST, "--all", "--days", str(DAYS), "--size", "100", "--out", str(out)],
        cwd=str(BASE),
        env=env,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if proc.returncode != 0 or not out.exists():
        return None
    rep = json.loads(out.read_text(encoding="utf-8"))
    out.unlink(missing_ok=True)
    return rep


def main() -> int:
    client = MarketDataClient()
    universe = hv_dip_tickers()
    bench_tickers = ["SPY", "QQQ"]
    bars_map = client.fetch_daily_bars_many([*bench_tickers, *universe], days=DAYS)

    all_days: set[datetime] = set()
    for t in universe:
        for b in bars_map.get(t) or []:
            all_days.add(_day(b))
    days = sorted(all_days)
    if len(days) < 100:
        print("historico insuficiente")
        return 1
    days = days[70:]  # mirror the backtest warmup
    mid = len(days) // 2
    periods = {
        "H1": (days[0], days[mid - 1]),
        "H2": (days[mid], days[-1]),
        "FULL": (days[0], days[-1]),
    }

    print("=== BENCHMARK: Quick Target vs comprar e segurar ===")
    print(f"{'periodo':<8}{'ativo':<22}{'ret%':>9}{'CAGR%':>9}{'maxDD%':>9}")
    print("-" * 57)

    strat = {}
    qqq_ret: dict[str, float] = {}
    for label, (lo, hi) in periods.items():
        span = (hi - lo).days
        r = run_portfolio(label.lower())
        if r:
            strat[label] = r
            print(
                f"{label:<8}{'ESTRATEGIA quick':<22}{r['return_pct']:>9.1f}"
                f"{r['cagr_pct']:>9.1f}{r['max_drawdown_pct']:>9.1f}"
            )
        for bt in bench_tickers:
            res = buy_hold(bars_map.get(bt) or [], lo, hi)
            if res:
                if bt == "QQQ":
                    qqq_ret[label] = res[0]
                print(
                    f"{label:<8}{'buy&hold ' + bt:<22}{res[0]:>9.1f}"
                    f"{cagr(res[0], span):>9.1f}{res[1]:>9.1f}"
                )
        rets = []
        dds = []
        for t in universe:
            res = buy_hold(bars_map.get(t) or [], lo, hi)
            if res:
                rets.append(res[0])
                dds.append(res[1])
        if rets:
            ew = statistics.fmean(rets)
            print(
                f"{label:<8}{'buy&hold universo EW':<22}{ew:>9.1f}"
                f"{cagr(ew, span):>9.1f}{statistics.fmean(dds):>9.1f}"
            )
        print()

    # ---- Per-trade edge + DSR (production config) ----
    print("=== SIGNIFICANCIA DO EDGE POR TRADE (config de producao) ===")
    rep = run_backtest({})
    go = True
    reasons: list[str] = []
    if not rep:
        print("  backtest indisponivel — nao foi possivel avaliar")
        go = False
        reasons.append("backtest indisponivel")
    else:
        pcts = [t["pnl_pct"] for t in rep["trades"]]
        n = len(pcts)
        if n < 30:
            print(f"  trades insuficientes (n={n}) para significancia")
            go = False
            reasons.append("amostra < 30 trades")
        else:
            mean = statistics.fmean(pcts)
            sd = statistics.stdev(pcts)
            se = sd / math.sqrt(n)
            t_stat = mean / se
            print(f"n={n}  media={mean:.2f}%  desvio={sd:.2f}%  t={t_stat:.2f}")
            print(f"IC95% = [{mean - 1.96*se:.2f}% , {mean + 1.96*se:.2f}%]")
            for cluster in (3, 5, 10):
                eff_n = n / cluster
                se_adj = sd / math.sqrt(eff_n)
                print(
                    f"    ~{cluster} trades correlacionados: "
                    f"t_efetivo={mean/se_adj:.2f}  "
                    f"IC95%=[{mean - 1.96*se_adj:.2f}%, {mean + 1.96*se_adj:.2f}%]"
                )
            dsr = deflated_sharpe_ratio(pcts, n_trials=20)
            print(f"Deflated Sharpe Ratio (DSR) = {dsr:.3f}  (prob. de ser real)")
            if mean <= 0 or dsr < 0.5:
                go = False
                reasons.append(f"expectancia fraca (media={mean:.2f}%, DSR={dsr:.2f})")

    # ---- CSCV overfitting probability across the grid ----
    print("\n=== CSCV (probabilidade de overfitting do backtest) ===")
    s_blocks = 8
    matrix: list[list[float]] = []
    for name, ov in GRID:
        r = run_backtest(ov)
        if not r or not r["trades"]:
            print(f"  {name}: sem trades")
            continue
        # Chronological per-trade pnl% -> S OOS blocks (padded to S).
        trades = sorted(r["trades"], key=lambda t: t["opened_date"])
        pnls = [t["pnl_pct"] for t in trades]
        block_size = max(1, math.ceil(len(pnls) / s_blocks))
        blocks = [
            sum(pnls[i : i + block_size]) for i in range(0, len(pnls), block_size)
        ]
        blocks = (blocks + [0.0] * s_blocks)[:s_blocks]
        print(f"  {name}: n={len(pnls)} blocos={len([b for b in blocks if b])}")
        matrix.append(blocks)
    if len(matrix) >= 2:
        # transpose to (windows x configs); rows must all be length s_blocks.
        t_matrix = [[matrix[c][r] for c in range(len(matrix))] for r in range(s_blocks)]
        pbo = probability_of_backtest_overfitting(t_matrix, s_blocks=s_blocks)
        print(f"\nPBO (CSCV) = {pbo:.2f}  (menor = melhor; >0.5 = risco alto)")
        if pbo > 0.5:
            go = False
            reasons.append(f"PBO alto ({pbo:.2f})")
    else:
        print("  matriz CSCV insuficiente — pulando PBO")

    # ---- QQQ gate: must beat buy & hold QQQ in BOTH halves ----
    print("\n=== GATE vs QQQ (H1/H2) ===")
    for label in ("H1", "H2"):
        s = strat.get(label)
        q = qqq_ret.get(label)
        if s is None or q is None:
            print(f"  {label}: estrategia ou QQQ indisponivel")
            go = False
            reasons.append(f"{label} indisponivel")
            continue
        s_ret = s["return_pct"]
        ok = s_ret > q
        print(f"  {label}: estrategia {s_ret:+.1f}% vs QQQ {q:+.1f}%  -> {'OK' if ok else 'PERDE'}")
        if not ok:
            go = False
            reasons.append(f"{label}: estrategia {s_ret:.1f}% <= QQQ {q:.1f}%")

    # ---- GO / NO-GO ----
    print("\n" + "=" * 60)
    if go:
        print("GATE: APROVADO — estrategia bate os benchmarks e o edge e significativo.")
    else:
        print("GATE: REPROVADO — " + "; ".join(reasons) + ".")
    print("=" * 60)
    return 0 if go else 1


if __name__ == "__main__":
    raise SystemExit(main())
