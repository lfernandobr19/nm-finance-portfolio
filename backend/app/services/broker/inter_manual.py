from __future__ import annotations

from app.domain.models import Order, OrderStatus
from app.services.broker.base import BrokerResult


class InterManualBrokerAdapter:
    """Live Inter: no API — returns awaiting_broker with HB instructions."""

    def submit_order(self, order: Order) -> BrokerResult:
        hb_text = (
            f"INTER HB — COMPRA LIMITADA\n"
            f"Ticker: {order.ticker}\n"
            f"Quantidade: {order.quantity}\n"
            f"Preço limite: R$ {order.limit_price:.2f}\n"
            f"Valor aprox.: R$ {order.amount_brl:.2f}\n"
            f"Conta: Inter Invest (home broker)"
        )
        payload = {
            "mode": "live",
            "broker": "inter",
            "instructions": (
                "Abra o Home Broker do Inter, lance a ordem com os dados abaixo "
                "e marque como executada no NM Finance."
            ),
            "hb_text": hb_text,
            "ticker": order.ticker,
            "quantity": order.quantity,
            "limit_price": order.limit_price,
            "side": "buy",
        }
        return BrokerResult(
            status=OrderStatus.awaiting_broker,
            execution_payload=payload,
        )

    def cancel_order(self, order: Order) -> BrokerResult:
        return BrokerResult(
            status=OrderStatus.cancelled,
            execution_payload={
                **(order.execution_payload or {}),
                "cancelled_in_app": True,
                "note": "Cancelada no NM Finance — confira se cancelou também no Inter.",
            },
        )

    def sell(self, order: Order) -> BrokerResult:
        hb_text = (
            f"INTER HB — VENDA\n"
            f"Ticker: {order.ticker}\n"
            f"Quantidade: {order.quantity}\n"
            f"Preço (ref.): US$ {order.limit_price:.2f}\n"
            f"Conta: Inter Invest (home broker)"
        )
        return BrokerResult(
            status=OrderStatus.awaiting_broker,
            execution_payload={
                "mode": "live",
                "broker": "inter",
                "instructions": (
                    "Abra o Home Broker do Inter, lance a ordem de venda e marque "
                    "como executada no NM Finance."
                ),
                "hb_text": hb_text,
                "ticker": order.ticker,
                "quantity": order.quantity,
                "limit_price": order.limit_price,
                "side": "sell",
            },
        )

    def place_bracket(self, order: Order) -> BrokerResult:
        return BrokerResult(
            status=OrderStatus.awaiting_broker,
            execution_payload={
                "mode": "live",
                "broker": "inter",
                "note": "OCO não suportado no Inter manual — acompanhar stop/alvo manualmente.",
                "ticker": order.ticker,
                "quantity": order.quantity,
                "target_price": (order.execution_payload or {}).get("target_price"),
                "stop_trigger": (order.execution_payload or {}).get("stop_trigger"),
                "side": "sell",
            },
        )
