"""Reject swing suggestions with zero/negative amount (not actionable)."""
import sys
sys.path.insert(0, "/home/<USER>/Projects/fiidesk/backend")

from app.db import SessionLocal
from app.domain.models import Suggestion, SuggestionStatus, StrategyKind

db = SessionLocal()
try:
    rows = (
        db.query(Suggestion)
        .filter(
            Suggestion.strategy_kind == StrategyKind.swing,
            Suggestion.status == SuggestionStatus.pending,
        )
        .all()
    )
    rejected = []
    for s in rows:
        amt = getattr(s, "proposed_amount_brl", None) or 0.0
        if amt <= 0:
            s.status = SuggestionStatus.rejected
            rejected.append((s.ticker, s.account_id))
    db.commit()
    print(f"REJECTED {len(rejected)} zero-amount swing suggestions:")
    for t, a in rejected:
        print(f"  {t} ({a})")
    print("remaining pending swing suggestions:")
    for s in rows:
        if getattr(s, "proposed_amount_brl", None) and getattr(s, "proposed_amount_brl") > 0:
            print(f"  {s.ticker} amt={s.proposed_amount_brl} status={s.status}")
finally:
    db.close()
