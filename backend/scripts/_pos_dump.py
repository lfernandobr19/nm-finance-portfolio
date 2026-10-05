from app.db import SessionLocal
from app.domain.models import Position, StrategyKind

db = SessionLocal()
rows = db.query(Position).filter(Position.strategy_kind == StrategyKind.hv_dip).order_by(Position.opened_at.desc()).limit(15).all()
for p in rows:
    print(p.ticker, p.status, p.quantity, p.entry_price, p.opened_at, p.closed_at)
print("open:", sum(1 for p in rows if str(p.status) == "open"))
db.close()
