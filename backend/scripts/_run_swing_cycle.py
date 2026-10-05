"""Run a full swing cycle end-to-end and report results."""
import sys

BACKEND_DIR = "/home/<USER>/Projects/fiidesk/backend"
sys.path.insert(0, BACKEND_DIR)

from app.db import SessionLocal
from app.services.swing.engine import run_swing_cycle

db = SessionLocal()
try:
    created = run_swing_cycle(db)
    db.commit()
    print(f"SWING_CYCLE_DONE created={len(created)}")
    for s in created:
        print(f"  {s.ticker}: amt_brl={getattr(s, 'proposed_amount_brl', None)} status={getattr(s, 'status', None)}")
except Exception as e:
    db.rollback()
    print(f"SWING_CYCLE_ERROR {type(e).__name__}: {e}")
finally:
    db.close()
