"""Revert premature LCID fill while tastytrade order still Received."""
from app.db import SessionLocal
from app.domain.models import InvestmentAccount, Order, OrderStatus, Position, PositionStatus

db = SessionLocal()
try:
    acc = db.query(InvestmentAccount).filter(InvestmentAccount.broker_code == "alpaca").first()
    pos = (
        db.query(Position)
        .filter(
            Position.account_id == acc.id,
            Position.ticker == "LCID",
            Position.status == PositionStatus.open,
        )
        .one_or_none()
    )
    order = db.query(Order).filter(Order.id == pos.order_id).one() if pos else None
    if pos and order:
        acc.cash_usd = round(float(acc.cash_usd or 0) + float(pos.quantity) * float(pos.entry_price), 2)
        db.delete(pos)
        order.status = OrderStatus.submitted
        order.filled_price = None
        order.filled_at = None
        db.commit()
        print(f"reverted LCID position; cash_usd={acc.cash_usd}; order={order.status}")
    else:
        print("nothing to revert")
finally:
    db.close()
