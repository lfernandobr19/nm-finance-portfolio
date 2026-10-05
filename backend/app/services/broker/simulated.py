from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.domain.models import Order, OrderStatus
from app.services.broker.base import BrokerResult


class SimulatedBrokerAdapter:
    """Paper trading: fills immediately at limit_price."""

    def submit_order(self, order: Order) -> BrokerResult:
        if order.quantity <= 0 or order.limit_price <= 0:
            return BrokerResult(
                status=OrderStatus.rejected,
                error_message="Invalid quantity or limit_price for paper fill",
            )
        return BrokerResult(
            status=OrderStatus.filled,
            broker_order_id=f"PAPER-{uuid4().hex[:10].upper()}",
            filled_price=order.limit_price,
            execution_payload={
                "mode": "paper",
                "simulated_at": datetime.now(timezone.utc).isoformat(),
                "message": "Ordem preenchida no simulador (paper).",
            },
        )

    def cancel_order(self, order: Order) -> BrokerResult:
        return BrokerResult(
            status=OrderStatus.cancelled,
            broker_order_id=order.broker_order_id,
            execution_payload={"mode": "paper", "cancelled": True},
        )

    def sell(self, order: Order) -> BrokerResult:
        if order.quantity <= 0:
            return BrokerResult(
                status=OrderStatus.rejected,
                error_message="Invalid quantity for paper sell",
            )
        return BrokerResult(
            status=OrderStatus.filled,
            broker_order_id=f"PAPER-SELL-{uuid4().hex[:10].upper()}",
            filled_price=order.limit_price,
            execution_payload={
                "mode": "paper",
                "simulated_at": datetime.now(timezone.utc).isoformat(),
                "message": "Venda preenchida no simulador (paper).",
            },
        )

    def place_bracket(self, order: Order) -> BrokerResult:
        return BrokerResult(
            status=OrderStatus.submitted,
            broker_order_id=f"PAPER-OCO-{uuid4().hex[:10].upper()}",
            execution_payload={
                "mode": "paper",
                "bracket": True,
                "target_price": (order.execution_payload or {}).get("target_price"),
                "stop_trigger": (order.execution_payload or {}).get("stop_trigger"),
            },
        )
