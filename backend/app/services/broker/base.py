from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.domain.models import Order, OrderStatus


@dataclass
class BrokerResult:
    status: OrderStatus
    broker_order_id: str | None = None
    filled_price: float | None = None
    error_message: str | None = None
    execution_payload: dict[str, Any] = field(default_factory=dict)


class BrokerAdapter(Protocol):
    def submit_order(self, order: Order) -> BrokerResult: ...

    def cancel_order(self, order: Order) -> BrokerResult: ...

    def sell(self, order: Order) -> BrokerResult: ...

    def place_bracket(self, order: Order) -> BrokerResult: ...
