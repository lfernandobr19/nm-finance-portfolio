from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_membership, require_roles
from app.db import get_db
from app.domain.models import AccountMembership, MembershipRole, Order, OrderStatus
from app.schemas import OrderMarkFilled, OrderOut
from app.services.orders import mark_order_cancelled, mark_order_filled

router = APIRouter(tags=["orders"])


def _order_out(order: Order) -> OrderOut:
    kind = getattr(order, "strategy_kind", None)
    return OrderOut(
        id=order.id,
        account_id=order.account_id,
        suggestion_id=order.suggestion_id,
        ticker=order.ticker,
        strategy_kind=kind.value if hasattr(kind, "value") else str(kind or "income"),
        side=order.side.value if hasattr(order.side, "value") else str(order.side),
        quantity=order.quantity,
        amount_brl=order.amount_brl,
        limit_price=order.limit_price,
        status=order.status.value if hasattr(order.status, "value") else str(order.status),
        broker=order.broker,
        execution_mode=(
            order.execution_mode.value
            if hasattr(order.execution_mode, "value")
            else str(order.execution_mode)
        ),
        broker_order_id=order.broker_order_id,
        filled_price=order.filled_price,
        filled_at=order.filled_at,
        error_message=order.error_message,
        execution_payload=order.execution_payload or {},
        acted_by_user_id=order.acted_by_user_id,
        created_at=order.created_at,
    )


@router.get("/accounts/{account_id}/orders", response_model=list[OrderOut])
def list_orders(
    account_id: str,
    status_filter: OrderStatus | None = Query(default=None, alias="status"),
    _: AccountMembership = Depends(get_membership),
    db: Session = Depends(get_db),
) -> list[OrderOut]:
    q = db.query(Order).filter(Order.account_id == account_id)
    if status_filter:
        q = q.filter(Order.status == status_filter)
    rows = q.order_by(Order.created_at.desc()).limit(100).all()
    return [_order_out(o) for o in rows]


@router.get("/accounts/{account_id}/orders/{order_id}", response_model=OrderOut)
def get_order(
    account_id: str,
    order_id: str,
    _: AccountMembership = Depends(get_membership),
    db: Session = Depends(get_db),
) -> OrderOut:
    order = (
        db.query(Order)
        .filter(Order.id == order_id, Order.account_id == account_id)
        .one_or_none()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return _order_out(order)


@router.post("/accounts/{account_id}/orders/{order_id}/mark-filled", response_model=OrderOut)
def api_mark_filled(
    account_id: str,
    order_id: str,
    body: OrderMarkFilled,
    membership: AccountMembership = Depends(
        require_roles(MembershipRole.owner, MembershipRole.operator)
    ),
    db: Session = Depends(get_db),
) -> OrderOut:
    order = (
        db.query(Order)
        .filter(Order.id == order_id, Order.account_id == account_id)
        .one_or_none()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    try:
        mark_order_filled(
            db, order, user_id=membership.user_id, filled_price=body.filled_price
        )
        db.commit()
        db.refresh(order)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _order_out(order)


@router.post("/accounts/{account_id}/orders/{order_id}/mark-cancelled", response_model=OrderOut)
def api_mark_cancelled(
    account_id: str,
    order_id: str,
    membership: AccountMembership = Depends(
        require_roles(MembershipRole.owner, MembershipRole.operator)
    ),
    db: Session = Depends(get_db),
) -> OrderOut:
    order = (
        db.query(Order)
        .filter(Order.id == order_id, Order.account_id == account_id)
        .one_or_none()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    try:
        mark_order_cancelled(db, order, user_id=membership.user_id)
        db.commit()
        db.refresh(order)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _order_out(order)
