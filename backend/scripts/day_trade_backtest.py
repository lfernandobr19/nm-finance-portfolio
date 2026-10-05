"""Offline day trade backtest / calibration over persisted bars.

Usage (from backend/):
    python scripts/day_trade_backtest.py [--rule vwap_reclaim] [--max-combos 60]

Reads `day_trade_bars` from the DB, replays each rule, prints walk-forward metrics
(expectancy, Sharpe, DSR, PBO) and the current best param set.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.db import SessionLocal
from app.services.day_trade.configs import get_active_params
from app.services.day_trade.learning import load_sessions, run_walk_forward
from app.services.day_trade.params import RULE_IDS


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rule", choices=RULE_IDS, default=None)
    parser.add_argument("--max-combos", type=int, default=60)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        sessions = load_sessions(db)
        print(f"sessions={len(sessions)} bars_sessions_loaded")
        if not sessions:
            print("No bars in day_trade_bars — run the streamer or backfill first.")
            return
        current = get_active_params(db)
        rules = [args.rule] if args.rule else RULE_IDS
        for rule_id in rules:
            print(f"\n=== {rule_id} ===")
            wf = run_walk_forward(
                rule_id,
                sessions,
                max_combos=args.max_combos,
                current_params=current.get(rule_id),
            )
            if wf is None:
                print("  insufficient data for walk-forward")
                continue
            print(f"  OOS n={wf['oos_n']} expectancy={wf['oos_expectancy']:.3f}R")
            print(f"  Sharpe={wf['oos_sharpe']:.3f} DSR={wf['dsr']:.3f} PBO={wf['pbo']:.3f}")
            print(f"  best_params={wf['best_params']}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
