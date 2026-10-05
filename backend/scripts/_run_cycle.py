"""Run hv_dip cycle end-to-end and report detailed results."""
import os
import sys
import logging
from datetime import datetime, timezone

BACKEND_DIR = os.environ.get("FIIDESK_BACKEND_DIR", "/home/<USER>/Projects/fiidesk/backend")
sys.path.insert(0, BACKEND_DIR)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from app.db import SessionLocal
from app.domain.models import Order, OrderStatus, Position, Suggestion, SuggestionStatus
from app.services.hv_dip.engine import run_hv_dip_cycle

db = SessionLocal()
print("=== RUNNING HV DIP CYCLE ===")
print("start_utc", datetime.now(timezone.utc).isoformat())
try:
    created = run_hv_dip_cycle(db)
except Exception as e:
    import traceback
    print("CYCLE ERROR:")
    traceback.print_exc()
    created = []

print(f"\n=== CREATED {len(created)} SUGGESTIONS ===")
for sg in created:
    m = sg.metrics or {}
    print(f"  {sg.ticker} status={sg.status} letter={sg.swing_score_letter} score={sg.score}")
    print(f"    dip={m.get('dip_pct')} entry={sg.entry_price} stop={sg.stop_price} target={sg.target_price} amt={sg.proposed_amount_brl}")
    print(f"    review={sg.review_required} catalyst={bool(m.get('catalyst'))} risky={m.get('risky_recovery')}")

print("\n=== ORDERS CREATED THIS RUN (last 5) ===")
for o in db.query(Order).order_by(Order.created_at.desc()).limit(5).all():
    p = o.execution_payload or {}
    print(f"  {o.ticker} status={o.status} qty={o.quantity} limit={o.limit_price} filled={o.filled_price} mode={p.get('mode')}")

print("\n=== OPEN POSITIONS NOW ===")
for p in db.query(Position).filter(Position.status == "open").all():
    print(f"  {p.ticker} qty={p.quantity} entry={p.entry_price} tranche={p.tranche_index}")

db.close()
print("\n=== DONE ===")
