"""Walk-forward validation of the hv_dip changes + execution-cost sensitivity.

Only changes that hold up in BOTH halves of the sample are trustworthy; a change
that only wins on the full sample is in-sample curve fitting.

Run from backend/:
    .venv/bin/python scripts/_bt_validate.py
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

CANDIDATES: list[tuple[str, dict[str, str]]] = [
    ("ATUAL (controle)", {}),
    ("A) dip_alloc OFF", {"BT_DIP_ALLOC": "0"}),
    ("B) dip_alloc OFF + piso 10%", {"BT_DIP_ALLOC": "0", "BT_FLOOR_PCT": "10"}),
    ("C) piso 10% (mantem dip_alloc)", {"BT_FLOOR_PCT": "10"}),
    ("D) giveback 40/15", {"HV_DIP_GIVEBACK_MAX": "0.40", "HV_DIP_GIVEBACK_MIN": "0.15"}),
    ("E) latch 8", {"HV_DIP_LATCH_PCT": "8"}),
    (
        "F) dip_alloc OFF + piso10 + gb40/15",
        {
            "BT_DIP_ALLOC": "0",
            "BT_FLOOR_PCT": "10",
            "HV_DIP_GIVEBACK_MAX": "0.40",
            "HV_DIP_GIVEBACK_MIN": "0.15",
        },
    ),
]

SLIPPAGES = ["0", "0.15", "0.25", "0.5", "0.75"]


def run(overrides: dict[str, str]) -> dict | None:
    env = dict(os.environ)
    env.update(overrides)
    proc = subprocess.run(
        [PY, SCRIPT], cwd=str(BASE), env=env, capture_output=True, text=True, timeout=1800
    )
    if proc.returncode != 0:
        print(f"    FALHOU: {proc.stderr[-300:]}", file=sys.stderr)
        return None
    i = proc.stdout.find("{")
    if i < 0:
        return None
    try:
        return json.loads(proc.stdout[i:])
    except json.JSONDecodeError:
        return None


def main() -> int:
    print("=== VALIDACAO WALK-FORWARD (CAGR% / maxDD%) ===")
    hdr = f"{'config':<34}{'H1 CAGR':>10}{'H1 DD':>8}{'H2 CAGR':>10}{'H2 DD':>8}{'FULL':>9}{'robusto':>9}"
    print(hdr)
    print("-" * len(hdr))
    control = {}
    results = []
    for name, ov in CANDIDATES:
        got = {}
        for period in ("h1", "h2", "full"):
            r = run({**ov, "BT_PERIOD": period})
            got[period] = r
        if not all(got.values()):
            continue
        if name.startswith("ATUAL"):
            control = got
        better_h1 = got["h1"]["cagr_pct"] > control.get("h1", got["h1"])["cagr_pct"]
        better_h2 = got["h2"]["cagr_pct"] > control.get("h2", got["h2"])["cagr_pct"]
        if name.startswith("ATUAL"):
            robust = "base"
        elif better_h1 and better_h2:
            robust = "SIM"
        elif better_h1 or better_h2:
            robust = "parcial"
        else:
            robust = "nao"
        print(
            f"{name:<34}{got['h1']['cagr_pct']:>10.1f}{got['h1']['max_drawdown_pct']:>8.1f}"
            f"{got['h2']['cagr_pct']:>10.1f}{got['h2']['max_drawdown_pct']:>8.1f}"
            f"{got['full']['cagr_pct']:>9.1f}{robust:>9}"
        )
        results.append((name, got, robust))

    print("\n=== CUSTO DE EXECUCAO (config: dip_alloc OFF + piso 10%) ===")
    print(f"{'slippage/lado':<16}{'CAGR%':>9}{'final$':>9}{'PF':>7}{'avg%':>7}")
    print("-" * 48)
    for s in SLIPPAGES:
        r = run({"BT_DIP_ALLOC": "0", "BT_FLOOR_PCT": "10", "BT_SLIPPAGE_PCT": s})
        if r is None:
            continue
        pf = r["profit_factor"] or 0
        print(
            f"{s + '%':<16}{r['cagr_pct']:>9.1f}{r['final_usd']:>9.0f}"
            f"{pf:>7.2f}{r['avg_return_pct']:>7.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
