"""hv_dip OCO on sandbox/paper; judgment hold cancels live legs."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.domain.models import (
    AccountCurrency,
    ExecutionMode,
    InvestmentAccount,
    Order,
    OrderSide,
    OrderStatus,
    Position,
    PositionStatus,
    StrategyKind,
)
from app.services.broker.base import BrokerResult
from app.services.hv_dip.bracket import cancel_open_oco, place_oco_bracket


def _account(**kw) -> InvestmentAccount:
    defaults = dict(
        id="acc1",
        name="NM USD Paper",
        owner_user_id="u1",
        broker_code="tastytrade",
        currency=AccountCurrency.USD,
        execution_mode=ExecutionMode.paper,
        cash_usd=300.0,
        automation_paused=False,
    )
    defaults.update(kw)
    return InvestmentAccount(**defaults)


def _pos(**kw) -> Position:
    defaults = dict(
        id="p1",
        account_id="acc1",
        order_id="o1",
        suggestion_id="s1",
        ticker="SOFI",
        strategy_kind=StrategyKind.hv_dip,
        quantity=10.0,
        entry_price=5.0,
        stop_price=4.5,
        target_price=6.0,
        status=PositionStatus.open,
        opened_at=datetime.now(timezone.utc),
        metrics={},
    )
    defaults.update(kw)
    return Position(**defaults)


def test_place_oco_bracket_paper_tastytrade(monkeypatch):
    adapter = MagicMock()
    adapter.place_bracket.return_value = BrokerResult(
        status=OrderStatus.submitted,
        broker_order_id="OCO-1",
        execution_payload={"mode": "tastytrade_sandbox"},
    )
    monkeypatch.setattr(
        "app.services.broker.get_broker_adapter", lambda acc: adapter
    )
    db = MagicMock()
    db.get.return_value = _account()
    order = place_oco_bracket(db, _pos())
    assert order is not None
    assert order.status == OrderStatus.submitted
    assert order.broker_order_id == "OCO-1"
    adapter.place_bracket.assert_called_once()
    payload = adapter.place_bracket.call_args.args[0].execution_payload
    assert payload["target_price"] == 6.0
    assert payload["stop_trigger"] == 4.5


def test_place_oco_skipped_for_non_tastytrade(monkeypatch):
    adapter = MagicMock()
    monkeypatch.setattr(
        "app.services.broker.get_broker_adapter", lambda acc: adapter
    )
    db = MagicMock()
    db.get.return_value = _account(broker_code="inter")
    assert place_oco_bracket(db, _pos()) is None
    adapter.place_bracket.assert_not_called()


def test_cancel_open_oco_on_hold(monkeypatch):
    adapter = MagicMock()
    adapter.cancel_order.return_value = BrokerResult(
        status=OrderStatus.cancelled,
        broker_order_id="OCO-1",
        execution_payload={"cancelled": True},
    )
    monkeypatch.setattr(
        "app.services.broker.get_broker_adapter", lambda acc: adapter
    )
    oco = Order(
        id="oco1",
        account_id="acc1",
        ticker="SOFI",
        strategy_kind=StrategyKind.hv_dip,
        side=OrderSide.sell,
        quantity=10.0,
        amount_brl=60.0,
        limit_price=6.0,
        status=OrderStatus.submitted,
        broker="tastytrade",
        execution_mode=ExecutionMode.paper,
        broker_order_id="OCO-1",
        position_id="p1",
        oco_group_id="oco-abc",
        execution_payload={"kind": "oco_bracket", "target_price": 6.0, "stop_trigger": 4.5},
    )
    db = MagicMock()
    db.get.return_value = _account()
    db.query.return_value.filter.return_value.all.return_value = [oco]
    n = cancel_open_oco(db, _pos())
    assert n == 1
    assert oco.status == OrderStatus.cancelled
    adapter.cancel_order.assert_called_once()


def test_cancel_already_filled_does_not_explode(monkeypatch):
    adapter = MagicMock()
    adapter.cancel_order.side_effect = RuntimeError("Order is filled")
    monkeypatch.setattr(
        "app.services.broker.get_broker_adapter", lambda acc: adapter
    )
    oco = Order(
        id="oco1",
        account_id="acc1",
        ticker="SOFI",
        strategy_kind=StrategyKind.hv_dip,
        side=OrderSide.sell,
        quantity=10.0,
        amount_brl=60.0,
        limit_price=6.0,
        status=OrderStatus.submitted,
        broker="tastytrade",
        execution_mode=ExecutionMode.paper,
        broker_order_id="OCO-1",
        position_id="p1",
        oco_group_id="oco-abc",
        execution_payload={"kind": "oco_bracket"},
    )
    db = MagicMock()
    db.get.return_value = _account()
    db.query.return_value.filter.return_value.all.return_value = [oco]
    n = cancel_open_oco(db, _pos())
    assert n == 0
    assert oco.status == OrderStatus.submitted


def test_cancel_skips_delete_when_not_cancellable(monkeypatch):
    adapter = MagicMock()
    adapter.get_remote_order.return_value = {
        "id": "OCO-1",
        "status": "Filled",
        "cancellable": False,
        "legs": [{"remaining-quantity": 0, "fills": [{"fill-price": 6.0}]}],
    }
    monkeypatch.setattr(
        "app.services.broker.get_broker_adapter", lambda acc: adapter
    )
    oco = Order(
        id="oco1",
        account_id="acc1",
        ticker="SOFI",
        strategy_kind=StrategyKind.hv_dip,
        side=OrderSide.sell,
        quantity=10.0,
        amount_brl=60.0,
        limit_price=6.0,
        status=OrderStatus.submitted,
        broker="tastytrade",
        execution_mode=ExecutionMode.paper,
        broker_order_id="OCO-1",
        position_id="p1",
        oco_group_id="oco-abc",
        execution_payload={"kind": "oco_bracket"},
    )
    db = MagicMock()
    db.get.return_value = _account()
    db.query.return_value.filter.return_value.all.return_value = [oco]
    n = cancel_open_oco(db, _pos())
    assert n == 0
    assert oco.status == OrderStatus.submitted
    adapter.cancel_order.assert_not_called()


def test_cancel_deletes_when_cancellable(monkeypatch):
    adapter = MagicMock()
    adapter.get_remote_order.return_value = {
        "id": "OCO-1",
        "status": "Live",
        "cancellable": True,
        "legs": [{"remaining-quantity": 10, "fills": []}],
    }
    adapter.cancel_order.return_value = BrokerResult(
        status=OrderStatus.cancelled,
        broker_order_id="OCO-1",
        execution_payload={"cancelled": True},
    )
    monkeypatch.setattr(
        "app.services.broker.get_broker_adapter", lambda acc: adapter
    )
    oco = Order(
        id="oco1",
        account_id="acc1",
        ticker="SOFI",
        strategy_kind=StrategyKind.hv_dip,
        side=OrderSide.sell,
        quantity=10.0,
        amount_brl=60.0,
        limit_price=6.0,
        status=OrderStatus.submitted,
        broker="tastytrade",
        execution_mode=ExecutionMode.paper,
        broker_order_id="OCO-1",
        position_id="p1",
        oco_group_id="oco-abc",
        execution_payload={"kind": "oco_bracket"},
    )
    db = MagicMock()
    db.get.return_value = _account()
    db.query.return_value.filter.return_value.all.return_value = [oco]
    n = cancel_open_oco(db, _pos())
    assert n == 1
    assert oco.status == OrderStatus.cancelled
    adapter.cancel_order.assert_called_once()
