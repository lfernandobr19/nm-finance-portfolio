"""OCO bracket placement for hv_dip positions (Quick Target).

After a fill we place a resting OCO (take-profit limit + stop) at the broker
for tastytrade live *and* sandbox/paper. Mega rotation never gets a broker
stop — its exit stays on consider_exit. Simulated (non-tastytrade) accounts
still rely on the exit_watch poll.

Judgment hold/cut cancels live legs via DELETE (terminal broker states are
ignored so a filled stop does not explode).
"""

from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy.orm import Session

from app.domain.models import (
    InvestmentAccount,
    Order,
    OrderSide,
    OrderStatus,
    Position,
)

logger = logging.getLogger("fiidesk.hv_dip.bracket")

_WORKING = (OrderStatus.queued, OrderStatus.submitted, OrderStatus.awaiting_broker)


def _tastytrade_account(account: InvestmentAccount | None) -> bool:
    if account is None:
        return False
    return (account.broker_code or "").lower() == "tastytrade"


def _mode_val(account: InvestmentAccount) -> str:
    mode = getattr(account, "execution_mode", None)
    return mode.value if hasattr(mode, "value") else str(mode or "")


def place_oco_bracket(db: Session, position: Position) -> Order | None:
    """Place a resting OCO bracket after an hv_dip fill (live or sandbox)."""
    from app.services.broker import get_broker_adapter

    account = db.get(InvestmentAccount, position.account_id)
    if not _tastytrade_account(account):
        return None
    if _mode_val(account) not in ("live", "paper"):
        return None

    adapter = get_broker_adapter(account)
    if not hasattr(adapter, "place_bracket"):
        return None

    target = float(position.target_price) if position.target_price is not None else None
    stop = float(position.stop_price) if position.stop_price is not None else None
    if target is None or stop is None:
        logger.warning("bracket skipped %s: sem target/stop", position.ticker)
        return None

    order = Order(
        account_id=position.account_id,
        suggestion_id=None,
        ticker=position.ticker,
        strategy_kind=position.strategy_kind,
        side=OrderSide.sell,
        quantity=float(position.quantity),
        amount_brl=round(float(position.quantity) * target, 2),
        limit_price=round(target, 2),
        status=OrderStatus.queued,
        broker=(account.broker_code or "tastytrade"),
        execution_mode=account.execution_mode,
        position_id=position.id,
        oco_group_id=f"oco-{uuid4().hex[:16]}",
        execution_payload={
            "kind": "oco_bracket",
            "target_price": target,
            "stop_trigger": stop,
        },
    )
    result = adapter.place_bracket(order)
    order.status = result.status
    order.broker_order_id = result.broker_order_id
    order.error_message = result.error_message
    order.execution_payload = {**order.execution_payload, **result.execution_payload}
    db.add(order)
    db.flush()
    if order.error_message:
        logger.warning("bracket %s note: %s", position.ticker, order.error_message[:200])
    logger.info(
        "oco bracket placed %s qty=%s target=%.2f stop=%.2f st=%s",
        position.ticker, position.quantity, target, stop, order.status,
    )
    return order


def _is_oco_order(order: Order) -> bool:
    payload = order.execution_payload or {}
    if payload.get("kind") == "oco_bracket":
        return True
    return bool(order.oco_group_id)


def _mark_local_cancelled(order: Order) -> None:
    order.status = OrderStatus.cancelled
    payload = dict(order.execution_payload or {})
    payload["cancelled_by_judgment"] = True
    order.execution_payload = payload


def _remote_for_cancel(adapter, order: Order) -> dict | None:
    getter = getattr(adapter, "get_remote_order", None)
    if not callable(getter):
        return None
    try:
        remote = getter(order)
    except Exception:
        logger.warning(
            "oco GET before cancel failed %s %s",
            order.ticker,
            order.broker_order_id,
            exc_info=True,
        )
        return None
    return remote if isinstance(remote, dict) else None


def cancel_open_oco(db: Session, position: Position) -> int:
    """DELETE still-live OCO legs only when the broker says cancellable."""
    from app.services.broker import get_broker_adapter
    from app.services.tastytrade_reconcile import classify_remote_status

    account = db.get(InvestmentAccount, position.account_id)
    if not _tastytrade_account(account):
        return 0
    try:
        rows = (
            db.query(Order)
            .filter(
                Order.position_id == position.id,
                Order.status.in_(_WORKING),
            )
            .all()
        )
    except Exception:
        logger.debug("cancel_open_oco query failed", exc_info=True)
        return 0
    if not isinstance(rows, list):
        return 0
    adapter = get_broker_adapter(account)
    cancelled = 0
    for order in rows:
        if not isinstance(order, Order) or not _is_oco_order(order):
            continue
        remote = _remote_for_cancel(adapter, order)
        if remote is not None:
            if remote.get("cancellable") is not True:
                kind = classify_remote_status(remote)
                if kind in ("cancelled", "rejected"):
                    _mark_local_cancelled(order)
                    cancelled += 1
                else:
                    logger.info(
                        "oco skip DELETE %s %s cancellable=%s kind=%s",
                        position.ticker,
                        order.broker_order_id,
                        remote.get("cancellable"),
                        kind,
                    )
                continue
        try:
            result = adapter.cancel_order(order)
        except Exception:
            logger.warning(
                "oco cancel exploded %s %s",
                position.ticker,
                getattr(order, "broker_order_id", None),
                exc_info=True,
            )
            continue
        status = getattr(result, "status", None)
        if status == OrderStatus.cancelled or str(getattr(status, "value", status)) == "cancelled":
            _mark_local_cancelled(order)
            cancelled += 1
        elif getattr(result, "error_message", None):
            logger.info(
                "oco cancel %s %s: %s",
                position.ticker,
                order.broker_order_id,
                str(result.error_message)[:200],
            )
    if cancelled:
        db.flush()
        logger.info("oco cancelled %s legs=%s", position.ticker, cancelled)
    return cancelled


__all__ = ["place_oco_bracket", "cancel_open_oco"]
