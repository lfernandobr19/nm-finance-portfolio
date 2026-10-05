"""Run swing cycle and verify BRL-only + BRAPI recovery."""
import os
import sys

BACKEND_DIR = os.environ.get("FIIDESK_BACKEND_DIR", "/home/<USER>/Projects/fiidesk/backend")
sys.path.insert(0, BACKEND_DIR)

from app.db import SessionLocal
from app.services.swing.engine import run_swing_cycle

db = SessionLocal()
print("running swing cycle...")
try:
    created = run_swing_cycle(db)
    print(f"created {len(created)} swing suggestions:")
    for sg in created:
        print(f"  {sg.ticker} acct={sg.account_id[:8]} letter={sg.swing_score_letter} amt={sg.proposed_amount_brl}")
except Exception:
    import traceback
    traceback.print_exc()
db.close()
print("done")
