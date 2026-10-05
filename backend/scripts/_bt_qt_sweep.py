"""Parameter sweep for the Quick Target strategy (target_R x stop_pct x hold).

Each config runs `backtest_quick_target.py --all` in a subprocess with env
overrides, because both the entry and exit engines read settings from env.
Daily bars are locally cached, so runs are fast.

Run from backend/:
    .venv/bin/python scripts/_bt_qt_sweep.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
PY = sys.executable
SCRIPT = str(BASE / "scripts/backtest_quick_target.py")

# (name, target_R, stop_pct, max_hold_days)
CONFIGS: list[tuple[str, float, float, int]] = [
    ("ATUAL (controle)", 1.0, 5.0, 3),
    # --- target multiple ---
    ("R 0.5", 0.5, 5.0, 3),
    ("R 1.5", 1.5, 5.0, 3),
    ("R 2.0", 2.0, 5.0, 3),
    # --- stop width ---
    ("stop 3%", 1.0, 3.0, 3),
    ("stop 8%", 1.0, 8.0, 3),
    ("stop 12%", 1.0, 12.0, 3),
    # --- hold horizon ---
    ("hold 1d", 1.0, 5.0, 1),
    ("hold 2d", 1.0, 5.0, 2),
    ("hold 5d", 1.0, 5.0, 5),
    # --- candidate combos ---
    ("R1.5 stop8 hold3", 1.5, 8.0, 3),
    ("R2.0 stop8 hold5", 2.0, 8.0, 5),
    ("R0.5 stop3 hold1", 0.5, 3.0, 1),
]


def run(name: str, target_r: float, stop_pct: float, hold: int) -> dict | None:
    env = dict(os.environ)
    env.update(
        {
            "HV_DIP_QT_TARGET_R": str(target_r),
            "HV_DIP_QT_STOP_PCT": str(stop_pct),
            "HV_DIP_QT_MAX_HOLD_DAYS": str(hold),
        }
    )
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
        f"{'config':<22}{'n':>5}{'win%':>7}{'avg%':>8}{'pnl$':>10}"
        f"{'PF':>7}{'maxDD':>8}{'stop%':>7}{'tgt%':>7}{'hold':>6}"
    )
    print("-" * 96)
    rows = []
    for name, tr, sp, hold in CONFIGS:
        rep = run(name, tr, sp, hold)
        if rep is None:
            continue
        a = rep["aggregate"]
        br = a.get("by_reason", {})
        n = a["trades"]
        stop_share = br.get("stop", {}).get("n", 0) / n * 100 if n else 0
        tgt_share = br.get("target", {}).get("n", 0) / n * 100 if n else 0
        pf = a.get("profit_factor")
        print(
            f"{name:<22}{n:>5}{a['win_rate_pct']:>7.1f}{a['avg_return_pct']:>8.2f}"
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
