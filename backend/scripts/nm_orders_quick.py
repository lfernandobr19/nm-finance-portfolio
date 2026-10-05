from app.db import SessionLocal
from app.domain.models import Order, OrderStatus, StrategyKind

db = SessionLocal()
rows = db.query(Order).filter(Order.status == OrderStatus.submitted).all()
print("submitted", len(rows))
for o in rows:
    print(o.ticker, o.broker_order_id, (o.execution_payload or {}).get("mode"))
rejected = (
    db.query(Order)
    .filter(Order.status == OrderStatus.rejected)
    .order_by(Order.created_at.desc())
    .limit(5)
    .all()
)
print("\nrecent rejected")
for o in rejected:
    print(o.ticker, str(o.error_message)[:80])
db.close()
