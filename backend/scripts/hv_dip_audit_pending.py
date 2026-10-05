"""Audit pending hv_dip suggestions against the new oscillation filter (Fase 6).

For each pending hv_dip suggestion, re-evaluate the ticker with the current
build_hv_dip_setup and report whether it would still pass (and its letter) or be
rejected/flagged under the new mean-reversion / quality / fresh-high logic.
Read-only: does not mutate suggestions.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.db import SessionLocal
from app.domain.models import StrategyKind, Suggestion, SuggestionStatus
from app.services.market_data import MarketDataClient
from app.services.hv_dip.engine import build_hv_dip_setup


def main() -> None:
    settings = get_settings()
    db = SessionLocal()
    client = MarketDataClient()
    try:
        rows = (
            db.query(Suggestion)
            .filter(Suggestion.strategy_kind == StrategyKind.hv_dip)
            .filter(Suggestion.status == SuggestionStatus.pending)
            .order_by(Suggestion.created_at.desc())
            .all()
        )
        print(f"pending hv_dip suggestions: {len(rows)}")
        if not rows:
            return
        for s in rows:
            m = s.metrics or {}
            old_dip = m.get("dip_pct")
            old_letter = s.swing_score_letter
            bars = client.fetch_daily_bars(s.ticker)
            row = build_hv_dip_setup(s.ticker, bars, min_dip_pct=settings.hv_dip_live_min_dip_pct)
            if row is None:
                verdict = "REJECTED (sem setup novo)"
                new_letter = "-"
                reason = "build_hv_dip_setup -> None"
            else:
                new_letter = row["scored"].letter
                if row["review_required"]:
                    verdict = "REVIEW (mudaria p/ review)"
                else:
                    verdict = "PASS (ainda válido)"
                reason = (
                    f"dip={row['dip_pct']:.1f}% recovery={row['recovery_rate']} "
                    f"tier={row['quality_tier']} fresh_high={row['is_fresh_high']} "
                    f"structural={row['structural_decline']}"
                )
            print(
                f"{s.ticker:6} old={old_letter} dip={old_dip} | new={new_letter} | "
                f"{verdict} | {reason}"
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
