"""Parameter sensitivity sweep for hv_dip (entry threshold + Exit Engine V2).

Each config runs `backtest_hv_dip.py --all` in a subprocess with env overrides,
because both the entry engine and the exit engine read settings from env at
import time. Daily bars are locally cached, so runs are fast.

Run from backend/:
    .venv/bin/python scripts/_bt_sweep.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
PY = str(BASE / ".venv/bin/python")
SCRIPT = str(BASE / "scripts/backtest_hv_dip.py")

# name -> env overrides. "" name = current production config (control).
CONFIGS: list[tuple[str, dict[str, str]]] = [
    ("ATUAL (controle)", {}),
    # --- stop width ---
    ("stop 8%", {"HV_DIP_HARD_STOP_PCT": "8"}),
    ("stop 10%", {"HV_DIP_HARD_STOP_PCT": "10"}),
    ("stop 15%", {"HV_DIP_HARD_STOP_PCT": "15"}),
    # --- latch: quando o trailing-protect liga ---
    ("latch 8%", {"HV_DIP_LATCH_PCT": "8"}),
    ("latch 10%", {"HV_DIP_LATCH_PCT": "10"}),
    ("latch 12%", {"HV_DIP_LATCH_PCT": "12"}),
    # --- giveback: quanto do pico devolve antes de vender ---
    ("giveback 60/30", {"HV_DIP_GIVEBACK_MAX": "0.60", "HV_DIP_GIVEBACK_MIN": "0.30"}),
    ("giveback 40/15", {"HV_DIP_GIVEBACK_MAX": "0.40", "HV_DIP_GIVEBACK_MIN": "0.15"}),
    # --- dip minimo de entrada ---
    ("dip min 8%", {"HV_DIP_MIN_DIP_PCT": "8"}),
    ("dip min 10%", {"HV_DIP_MIN_DIP_PCT": "10"}),
    ("dip min 15%", {"HV_DIP_MIN_DIP_PCT": "15"}),
    ("dip min 20%", {"HV_DIP_MIN_DIP_PCT": "20"}),
    # --- alvo ---
    ("alvo max 35%", {"HV_DIP_TARGET_MAX_PCT": "35"}),
    ("alvo max 70%", {"HV_DIP_TARGET_MAX_PCT": "70"}),
    ("alvo share 0.7", {"HV_DIP_TARGET_RECOVERY_SHARE": "0.7"}),
    # --- combinacao candidata: stop mais curto + deixa correr ---
    (
        "COMBO stop10 latch10 gb60/30",
        {
            "HV_DIP_HARD_STOP_PCT": "10",
            "HV_DIP_LATCH_PCT": "10",
            "HV_DIP_GIVEBACK_MAX": "0.60",
            "HV_DIP_GIVEBACK_MIN": "0.30",
        },
    ),
    (
        "COMBO stop10 latch10 gb60/30 dip10",
        {
            "HV_DIP_HARD_STOP_PCT": "10",
            "HV_DIP_LATCH_PCT": "10",
            "HV_DIP_GIVEBACK_MAX": "0.60",
            "HV_DIP_GIVEBACK_MIN": "0.30",
            "HV_DIP_MIN_DIP_PCT": "10",
        },
    ),
]


def run(overrides: dict[str, str]) -> dict | None:
    env = dict(os.environ)
    env.update(overrides)
    out = Path(tempfile.mktemp(suffix=".json"))
    proc = subprocess.run(
        [PY, SCRIPT, "--all", "--days", "500", "--size", "100", "--out", str(out)],
        cwd=str(BASE),
        env=env,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if proc.returncode != 0 or not out.exists():
        print(f"    FALHOU: {proc.stderr[-400:]}", file=sys.stderr)
        return None
    rep = json.loads(out.read_text(encoding="utf-8"))
    out.unlink(missing_ok=True)
    return rep


def main() -> int:
    print(
        f"{'config':<32}{'n':>5}{'win%':>7}{'avg%':>8}{'pnl$':>10}"
        f"{'PF':>7}{'maxDD':>8}{'stop%':>7}{'tgt%':>7}{'hold':>6}"
    )
    print("-" * 105)
    rows = []
    for name, ov in CONFIGS:
        rep = run(ov)
        if rep is None:
            continue
        a = rep["aggregate"]
        br = a.get("by_reason", {})
        n = a["trades"]
        stop_share = br.get("stop", {}).get("n", 0) / n * 100 if n else 0
        tgt_share = br.get("target", {}).get("n", 0) / n * 100 if n else 0
        pf = a.get("profit_factor")
        print(
            f"{name:<32}{n:>5}{a['win_rate_pct']:>7.1f}{a['avg_return_pct']:>8.2f}"
            f"{a['total_pnl_usd']:>10.2f}{(pf if pf is not None else 0):>7.2f}"
            f"{a['max_drawdown_usd']:>8.1f}{stop_share:>7.1f}{tgt_share:>7.1f}"
            f"{a['avg_hold_days']:>6.1f}"
        )
        rows.append((name, a))

    print("\n=== RANKING por PnL total ===")
    for name, a in sorted(rows, key=lambda r: -r[1]["total_pnl_usd"]):
        print(f"  {a['total_pnl_usd']:>9.2f}  PF={a.get('profit_factor')}  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
