"""Sweep the portfolio-level hv_dip backtest (finite capital + slots + slippage).

Ranks configs by what actually matters for a small real-money desk: CAGR on a
fixed starting capital and drawdown, not raw signal-count PnL.

Run from backend/:
    .venv/bin/python scripts/_bt_portfolio_sweep.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
PY = str(BASE / ".venv/bin/python")
SCRIPT = str(BASE / "scripts/_bt_portfolio.py")

RECO = {
    "HV_DIP_LATCH_PCT": "8",
    "HV_DIP_TARGET_MAX_PCT": "35",
    "HV_DIP_GIVEBACK_MAX": "0.40",
    "HV_DIP_GIVEBACK_MIN": "0.15",
}

CONFIGS: list[tuple[str, dict[str, str]]] = [
    ("ATUAL (controle)", {}),
    ("ATUAL sem slippage", {"BT_SLIPPAGE_PCT": "0"}),
    # isolar cada mudanca
    ("latch 8", {"HV_DIP_LATCH_PCT": "8"}),
    ("alvo max 35", {"HV_DIP_TARGET_MAX_PCT": "35"}),
    ("giveback 40/15", {"HV_DIP_GIVEBACK_MAX": "0.40", "HV_DIP_GIVEBACK_MIN": "0.15"}),
    # o multiplicador de alocacao por queda esta ajudando ou afogando o caixa?
    ("dip_alloc OFF", {"BT_DIP_ALLOC": "0"}),
    ("dip_alloc OFF + piso 10%", {"BT_DIP_ALLOC": "0", "BT_FLOOR_PCT": "10"}),
    ("piso caixa 10%", {"BT_FLOOR_PCT": "10"}),
    ("piso caixa 0%", {"BT_FLOOR_PCT": "0"}),
    # mais slots = mais diversificacao
    ("6 slots", {"BT_SLOTS": "6"}),
    ("8 slots", {"BT_SLOTS": "8"}),
    ("8 slots + dip_alloc OFF", {"BT_SLOTS": "8", "BT_DIP_ALLOC": "0"}),
    # combo recomendado
    ("RECO (latch8+tgt35+gb40/15)", dict(RECO)),
    ("RECO + dip_alloc OFF", {**RECO, "BT_DIP_ALLOC": "0"}),
    ("RECO + dip_alloc OFF + 8 slots", {**RECO, "BT_DIP_ALLOC": "0", "BT_SLOTS": "8"}),
    (
        "RECO + dip_alloc OFF + 8 slots + dip10",
        {**RECO, "BT_DIP_ALLOC": "0", "BT_SLOTS": "8", "HV_DIP_MIN_DIP_PCT": "10"},
    ),
    (
        "RECO + dip_alloc OFF + 8 slots + dip8",
        {**RECO, "BT_DIP_ALLOC": "0", "BT_SLOTS": "8", "HV_DIP_MIN_DIP_PCT": "8"},
    ),
    (
        "RECO + dip_alloc OFF + 8 slots + dip15",
        {**RECO, "BT_DIP_ALLOC": "0", "BT_SLOTS": "8", "HV_DIP_MIN_DIP_PCT": "15"},
    ),
    (
        "RECO + dip_alloc OFF + 6 slots + piso10",
        {**RECO, "BT_DIP_ALLOC": "0", "BT_SLOTS": "6", "BT_FLOOR_PCT": "10"},
    ),
]


def run(overrides: dict[str, str]) -> dict | None:
    env = dict(os.environ)
    env.update(overrides)
    proc = subprocess.run(
        [PY, SCRIPT],
        cwd=str(BASE),
        env=env,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if proc.returncode != 0:
        print(f"    FALHOU: {proc.stderr[-300:]}", file=sys.stderr)
        return None
    start = proc.stdout.find("{")
    if start < 0:
        return None
    try:
        return json.loads(proc.stdout[start:])
    except json.JSONDecodeError:
        return None


def main() -> int:
    hdr = (
        f"{'config':<34}{'final$':>9}{'ret%':>8}{'CAGR%':>8}{'maxDD%':>8}"
        f"{'n':>5}{'win%':>7}{'avg%':>7}{'PF':>6}{'noCash':>8}{'noSlot':>8}"
    )
    print(hdr)
    print("-" * len(hdr))
    rows = []
    for name, ov in CONFIGS:
        r = run(ov)
        if r is None:
            continue
        pf = r["profit_factor"] if r["profit_factor"] is not None else 0
        print(
            f"{name:<34}{r['final_usd']:>9.0f}{r['return_pct']:>8.1f}"
            f"{r['cagr_pct']:>8.1f}{r['max_drawdown_pct']:>8.1f}{r['trades']:>5}"
            f"{r['win_rate_pct']:>7.1f}{r['avg_return_pct']:>7.2f}{pf:>6.2f}"
            f"{r['signals_dropped_no_cash']:>8}{r['signals_dropped_no_slot']:>8}"
        )
        rows.append((name, r))

    print("\n=== RANKING por CAGR (retorno por unidade de tempo) ===")
    for name, r in sorted(rows, key=lambda x: -x[1]["cagr_pct"]):
        calmar = r["cagr_pct"] / r["max_drawdown_pct"] if r["max_drawdown_pct"] else 0
        print(
            f"  CAGR {r['cagr_pct']:>6.1f}%  maxDD {r['max_drawdown_pct']:>5.1f}%  "
            f"Calmar {calmar:>5.2f}  {name}"
        )

    print("\n=== RANKING por Calmar (CAGR/maxDD - retorno ajustado a risco) ===")
    for name, r in sorted(
        rows,
        key=lambda x: -(
            x[1]["cagr_pct"] / x[1]["max_drawdown_pct"] if x[1]["max_drawdown_pct"] else 0
        ),
    ):
        calmar = r["cagr_pct"] / r["max_drawdown_pct"] if r["max_drawdown_pct"] else 0
        print(f"  Calmar {calmar:>5.2f}  CAGR {r['cagr_pct']:>6.1f}%  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
