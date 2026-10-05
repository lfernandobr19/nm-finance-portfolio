from app.domain.models import ExecutionMode, Order, OrderSide, OrderStatus
from app.services.broker.inter_manual import InterManualBrokerAdapter
from app.services.broker.simulated import SimulatedBrokerAdapter


def _order(**kwargs) -> Order:
    defaults = dict(
        account_id="a",
        suggestion_id="s",
        ticker="HGLG11",
        side=OrderSide.buy,
        quantity=10,
        amount_brl=1624.0,
        limit_price=162.4,
        status=OrderStatus.queued,
        broker="inter",
        execution_mode=ExecutionMode.paper,
        execution_payload={},
    )
    defaults.update(kwargs)
    return Order(**defaults)


def test_simulated_fills_paper_order():
    result = SimulatedBrokerAdapter().submit_order(_order())
    assert result.status == OrderStatus.filled
    assert result.filled_price == 162.4
    assert result.broker_order_id is not None


def test_simulated_rejects_zero_qty():
    result = SimulatedBrokerAdapter().submit_order(_order(quantity=0))
    assert result.status == OrderStatus.rejected


def test_inter_manual_awaits_broker():
    result = InterManualBrokerAdapter().submit_order(
        _order(execution_mode=ExecutionMode.live)
    )
    assert result.status == OrderStatus.awaiting_broker
    assert "hb_text" in result.execution_payload
    assert "HGLG11" in result.execution_payload["hb_text"]
