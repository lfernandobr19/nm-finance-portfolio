"""Phase 2: real sell + OCO bracket plumbing (mocked broker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.domain.models import (
    AccountCurrency,
    ExecutionMode,
    InvestmentAccount,
    Order,
    OrderSide,
    OrderStatus,
    Position,
    PositionExitReason,
    PositionStatus,
)
from app.services.positions import close_position


def _account(**kw) -> InvestmentAccount:
    defaults = dict(
        id="acc1",
        name="NM USD Live",
        owner_user_id="u1",
        broker_code="tastytrade",
        currency=AccountCurrency.USD,
        execution_mode=ExecutionMode.live,
        cash_usd=100.0,
        hv_dip_equity_usd=100.0,
        max_ticket_brl=100.0,
        hv_dip_cash_floor_pct=20.0,
        hv_dip_max_ticker_pct=80.0,
    )
    defaults.update(kw)
    return InvestmentAccount(**defaults)


def _position(*, opened_at: datetime) -> Position:
    return Position(
        id="p1",
        account_id="acc1",
        order_id="o1",
        suggestion_id="s1",
        ticker="LCID",
        strategy_kind="hv_dip",
        quantity=10.0,
        entry_price=5.0,
        stop_price=4.5,
        target_price=6.0,
        status=PositionStatus.open,
        opened_at=opened_at,
    )


def test_close_position_live_submits_sell(monkeypatch):
    adapter = MagicMock()
    adapter.sell.return_value = MagicMock(
        status=OrderStatus.filled,
        broker_order_id="TT-SELL-1",
        filled_price=5.5,
        error_message=None,
        execution_payload={"mode": "tastytrade"},
    )
    monkeypatch.setattr(
        "app.services.broker.get_broker_adapter", lambda acc: adapter
    )

    db = MagicMock()
    acc = _account()
    db.get.return_value = acc
    pos = _position(opened_at=datetime.now(timezone.utc) - timedelta(days=3))

    closed = close_position(
        db, pos, reason=PositionExitReason.manual, manual_price=5.5
    )
    assert closed.status == PositionStatus.closed
    # A sell Order was submitted with the fill price used as exit.
    adapter.sell.assert_called_once()
    sell_order = adapter.sell.call_args.args[0]
    assert sell_order.side == OrderSide.sell
    assert sell_order.position_id == "p1"
    assert sell_order.suggestion_id is None
    # exit price came from the broker fill (5.5), cash credited + T+2 reserved.
    assert acc.cash_usd == pytest.approx(100.0 + 55.0)
    assert acc.unsettled_cash_usd == pytest.approx(55.0)


def test_close_position_paper_skips_broker(monkeypatch):
    adapter = MagicMock()
    monkeypatch.setattr(
        "app.services.broker.get_broker_adapter", lambda acc: adapter
    )

    db = MagicMock()
    acc = _account(execution_mode=ExecutionMode.paper, broker_code="inter")
    db.get.return_value = acc
    pos = _position(opened_at=datetime.now(timezone.utc) - timedelta(days=3))

    closed = close_position(
        db, pos, reason=PositionExitReason.manual, manual_price=5.5
    )
    assert closed.status == PositionStatus.closed
    # Simulated (non-tastytrade) paper never hits the broker sell path.
    adapter.sell.assert_not_called()


def test_close_position_skip_broker_sell(monkeypatch):
    adapter = MagicMock()
    monkeypatch.setattr(
        "app.services.broker.get_broker_adapter", lambda acc: adapter
    )

    db = MagicMock()
    acc = _account()
    db.get.return_value = acc
    pos = _position(opened_at=datetime.now(timezone.utc) - timedelta(days=3))

    closed = close_position(
        db,
        pos,
        reason=PositionExitReason.manual,
        manual_price=5.5,
        skip_broker_sell=True,
    )
    assert closed.status == PositionStatus.closed
    adapter.sell.assert_not_called()


def test_reconcile_sell_fill_closes_position(monkeypatch):
    """A submitted sell order that fills in the broker closes the position."""
    from app.services import tastytrade_reconcile as tr

    db = MagicMock()
    acc = _account(cash_usd=100.0)

    # Build an in-memory store that maps Order → Position like SQLAlchemy would.
    position = _position(opened_at=datetime.now(timezone.utc) - timedelta(days=3))

    order = Order(
        id="sell1",
        account_id="acc1",
        suggestion_id=None,
        ticker="LCID",
        strategy_kind="hv_dip",
        side=OrderSide.sell,
        quantity=10.0,
        amount_brl=55.0,
        limit_price=5.5,
        status=OrderStatus.submitted,
        broker="tastytrade",
        execution_mode=ExecutionMode.live,
        broker_order_id="TT-SELL-1",
        position_id="p1",
        execution_payload={"mode": "tastytrade"},
    )

    db.query.return_value.filter.return_value.all.return_value = [order]
    db.get.side_effect = lambda model, id_: acc if model is InvestmentAccount else position

    # Stub the broker status poll to return a filled order.
    monkeypatch.setattr(tr, "_order_status", lambda *a, **k: {
        "status": "filled",
        "legs": [{"quantity": 10.0, "fills": [{"fill-price": 5.5}]}],
    })
    monkeypatch.setattr(tr.TastytradeClient, "configured", lambda self: True)

    updated = tr.reconcile_submitted_tastytrade_orders(db)
    assert updated == 1
    assert position.status == PositionStatus.closed
    assert acc.cash_usd == pytest.approx(155.0)
    assert acc.unsettled_cash_usd == pytest.approx(55.0)


def _submitted_buy(**kw) -> Order:
    defaults = dict(
        id="buy1",
        account_id="acc1",
        suggestion_id=None,
        ticker="NVDA",
        strategy_kind="mega_rotation",
        side=OrderSide.buy,
        quantity=1.0,
        amount_brl=218.86,
        limit_price=218.86,
        status=OrderStatus.submitted,
        broker="tastytrade",
        execution_mode=ExecutionMode.paper,
        broker_order_id="1650607",
        execution_payload={"mode": "tastytrade_sandbox"},
    )
    defaults.update(kw)
    return Order(**defaults)


def test_reconcile_live_without_fill_stays_submitted():
    from app.services.tastytrade_reconcile import classify_remote_status

    kind = classify_remote_status({"status": "Live", "id": "1650607", "legs": []})
    assert kind == "working"
    assert classify_remote_status({"status": "Routed"}) == "working"
    assert classify_remote_status({"status": "In Flight"}) == "working"
    assert classify_remote_status({"status": "Replace Requested"}) == "working"
    assert classify_remote_status({"status": "Contingent"}) == "working"


def test_reconcile_expired_and_rejected_map_terminal():
    from app.services.tastytrade_reconcile import classify_remote_status

    assert classify_remote_status({"status": "Expired"}) == "cancelled"
    assert classify_remote_status({"status": "Canceled"}) == "cancelled"
    assert classify_remote_status({"status": "Removed"}) == "cancelled"
    assert classify_remote_status({"status": "Partially Removed"}) == "cancelled"
    assert classify_remote_status({"status": "Rejected"}) == "rejected"
    assert classify_remote_status(
        {
            "status": "Filled",
            "legs": [{"remaining-quantity": 0, "fills": [{"fill-price": 10.0}]}],
        }
    ) == "filled"


def test_partial_fill_with_remaining_stays_working():
    from app.services.tastytrade_reconcile import classify_remote_status

    assert (
        classify_remote_status(
            {
                "status": "Live",
                "legs": [
                    {
                        "remaining-quantity": 50,
                        "fills": [{"fill-price": 10.0, "quantity": 50}],
                    }
                ],
            }
        )
        == "working"
    )
    assert (
        classify_remote_status(
            {
                "status": "Live",
                "legs": [{"remaining-quantity": 100, "fills": []}],
            }
        )
        == "working"
    )
    assert (
        classify_remote_status(
            {
                "status": "Live",
                "legs": [{"remaining-quantity": 0, "fills": [{"fill-price": 10.0}]}],
            }
        )
        == "filled"
    )
    assert (
        classify_remote_status(
            {
                "status": "Filled",
                "legs": [{"remaining-quantity": 0, "fills": [{"fill-price": 10.0}]}],
            }
        )
        == "filled"
    )


def test_reconcile_live_status_does_not_open_position(monkeypatch):
    from app.services import tastytrade_reconcile as tr

    db = MagicMock()
    order = _submitted_buy()
    db.query.return_value.filter.return_value.all.return_value = [order]
    monkeypatch.setattr(tr, "_order_status", lambda *a, **k: {"status": "Live", "id": "1650607"})
    monkeypatch.setattr(tr, "_position_as_fill", lambda *a, **k: None)
    opened = []
    monkeypatch.setattr(tr, "open_position_from_fill", lambda *a, **k: opened.append(1))

    updated = tr.reconcile_submitted_tastytrade_orders(db)
    assert updated == 0
    assert order.status == OrderStatus.submitted
    assert opened == []


def test_reconcile_expired_marks_cancelled(monkeypatch):
    from app.services import tastytrade_reconcile as tr

    db = MagicMock()
    order = _submitted_buy()
    db.query.return_value.filter.return_value.all.return_value = [order]
    monkeypatch.setattr(tr, "_order_status", lambda *a, **k: {"status": "Expired", "id": "1650607"})

    updated = tr.reconcile_submitted_tastytrade_orders(db)
    assert updated == 1
    assert order.status == OrderStatus.cancelled


def test_reconcile_get_id_fails_live_list_fills(monkeypatch):
    from app.services import tastytrade_reconcile as tr
    from app.services.tastytrade_client import TastytradeHttpError

    db = MagicMock()
    order = _submitted_buy()
    db.query.return_value.filter.return_value.all.return_value = [order]
    db.get.return_value = None

    class _Client:
        def configured(self):
            return True

        def get_order(self, oid):
            raise TastytradeHttpError(502, "bad gateway")

        def list_live_orders(self):
            return [
                {
                    "id": "1650607",
                    "status": "Filled",
                    "legs": [{"quantity": 1.0, "fills": [{"fill-price": 218.5}]}],
                }
            ]

    monkeypatch.setattr(tr, "_client_for_order", lambda order: _Client())
    opened = []
    monkeypatch.setattr(tr, "open_position_from_fill", lambda *a, **k: opened.append(1))

    updated = tr.reconcile_submitted_tastytrade_orders(db)
    assert updated == 1
    assert order.status == OrderStatus.filled
    assert opened == [1]


def test_reconcile_auth_failure_does_not_expire(monkeypatch, caplog):
    from app.services import tastytrade_reconcile as tr
    from app.services.tastytrade_client import TastytradeHttpError

    db = MagicMock()
    order = _submitted_buy()
    db.query.return_value.filter.return_value.all.return_value = [order]

    class _Client:
        def configured(self):
            return True

        def get_order(self, oid):
            raise TastytradeHttpError(400, "User is not a TastyTrade customer")

        def list_live_orders(self):
            raise AssertionError("live list must not run after auth failure")

    monkeypatch.setattr(tr, "_client_for_order", lambda order: _Client())
    caplog.set_level("ERROR")
    updated = tr.reconcile_submitted_tastytrade_orders(db)
    assert updated == 0
    assert order.status == OrderStatus.submitted
    assert "token/auth failed" in caplog.text


def test_reconcile_history_fills_when_live_misses(monkeypatch):
    from app.services import tastytrade_reconcile as tr
    from app.services.tastytrade_client import TastytradeHttpError

    db = MagicMock()
    order = _submitted_buy()
    db.query.return_value.filter.return_value.all.return_value = [order]
    db.get.return_value = None

    class _Client:
        def configured(self):
            return True

        def get_order(self, oid):
            raise TastytradeHttpError(502, "bad gateway")

        def list_live_orders(self):
            return []

        def list_orders(self, *, start_at=None):
            return [
                {
                    "id": "1650607",
                    "status": "Filled",
                    "legs": [
                        {
                            "remaining-quantity": 0,
                            "quantity": 1.0,
                            "fills": [{"fill-price": 218.5}],
                        }
                    ],
                }
            ]

    monkeypatch.setattr(tr, "_client_for_order", lambda order: _Client())
    opened = []
    monkeypatch.setattr(tr, "open_position_from_fill", lambda *a, **k: opened.append(1))
    updated = tr.reconcile_submitted_tastytrade_orders(db)
    assert updated == 1
    assert order.status == OrderStatus.filled
    assert opened == [1]


def test_reconcile_matches_ext_client_order_id(monkeypatch):
    from app.services import tastytrade_reconcile as tr
    from app.services.tastytrade_client import TastytradeHttpError

    db = MagicMock()
    order = _submitted_buy(
        broker_order_id=None,
        execution_payload={"mode": "tastytrade_sandbox", "client_order_id": "cid-nvda-1"},
    )
    db.query.return_value.filter.return_value.all.return_value = [order]
    db.get.return_value = None

    class _Client:
        def configured(self):
            return True

        def get_order(self, oid):
            raise AssertionError("no broker id — must not GET by id")

        def list_live_orders(self):
            return [
                {
                    "id": "9999",
                    "ext-client-order-id": "cid-nvda-1",
                    "status": "Filled",
                    "legs": [{"remaining-quantity": 0, "fills": [{"fill-price": 218.0}]}],
                }
            ]

        def list_orders(self, *, start_at=None):
            raise TastytradeHttpError(502, "unused")

    monkeypatch.setattr(tr, "_client_for_order", lambda order: _Client())
    opened = []
    monkeypatch.setattr(tr, "open_position_from_fill", lambda *a, **k: opened.append(1))
    updated = tr.reconcile_submitted_tastytrade_orders(db)
    assert updated == 1
    assert order.broker_order_id == "9999"
    assert order.status == OrderStatus.filled


def test_reconcile_matches_external_identifier(monkeypatch):
    from app.services import tastytrade_reconcile as tr

    db = MagicMock()
    order = _submitted_buy(
        broker_order_id=None,
        execution_payload={"mode": "tastytrade_sandbox", "client_order_id": "cid-nvda-2"},
    )
    db.query.return_value.filter.return_value.all.return_value = [order]
    db.get.return_value = None

    class _Client:
        def configured(self):
            return True

        def get_order(self, oid):
            raise AssertionError("no broker id")

        def list_live_orders(self):
            return [
                {
                    "id": "8888",
                    "external-identifier": "cid-nvda-2",
                    "status": "Filled",
                    "legs": [{"remaining-quantity": 0, "fills": [{"fill-price": 218.0}]}],
                }
            ]

        def list_orders(self, *, start_at=None):
            return []

    monkeypatch.setattr(tr, "_client_for_order", lambda order: _Client())
    opened = []
    monkeypatch.setattr(tr, "open_position_from_fill", lambda *a, **k: opened.append(1))
    updated = tr.reconcile_submitted_tastytrade_orders(db)
    assert updated == 1
    assert order.broker_order_id == "8888"
    assert order.status == OrderStatus.filled


def test_reconcile_broker_position_classifies_fill(monkeypatch):
    from app.services import tastytrade_reconcile as tr

    db = MagicMock()
    order = _submitted_buy()
    db.query.return_value.filter.return_value.all.return_value = [order]
    db.get.return_value = None

    class _Client:
        def configured(self):
            return True

        def list_positions(self):
            return [
                {
                    "symbol": "NVDA",
                    "quantity": 1,
                    "average-open-price": 218.5,
                }
            ]

    monkeypatch.setattr(tr, "_order_status", lambda *a, **k: {"status": "Live", "id": "1650607"})
    monkeypatch.setattr(tr, "_client_for_order", lambda order: _Client())
    opened = []
    monkeypatch.setattr(tr, "open_position_from_fill", lambda *a, **k: opened.append(1))
    updated = tr.reconcile_submitted_tastytrade_orders(db)
    assert updated == 1
    assert order.status == OrderStatus.filled
    assert opened == [1]


def test_replace_open_limit_puts_when_editable(monkeypatch):
    from app.services.broker.tastytrade_paper import TastytradeBrokerAdapter

    adapter = TastytradeBrokerAdapter(live=False)
    order = _submitted_buy()
    client = MagicMock()
    client.replace_equity_limit.return_value = {"data": {"id": "1650607", "status": "Live"}}
    monkeypatch.setattr(adapter, "_client", lambda: client)
    monkeypatch.setattr(
        adapter,
        "get_remote_order",
        lambda o: {"id": "1650607", "editable": True, "cancellable": True, "status": "Live"},
    )
    result = adapter.replace_open_limit(order, limit_price=210.0)
    client.replace_equity_limit.assert_called_once()
    assert client.replace_equity_limit.call_args.args[0] == "1650607"
    assert client.replace_equity_limit.call_args.kwargs["limit_price"] == 210.0
    client.submit_equity_limit_buy.assert_not_called()
    assert order.limit_price == 210.0
    assert (result.execution_payload or {}).get("replaced") is True


def test_replace_open_limit_skips_when_not_editable():
    from app.services.broker.tastytrade_paper import TastytradeBrokerAdapter

    adapter = TastytradeBrokerAdapter(live=False)
    order = _submitted_buy()
    client = MagicMock()
    adapter._client = lambda: client  # noqa: SLF001
    adapter.get_remote_order = lambda o: {  # type: ignore[method-assign]
        "id": "1650607",
        "editable": False,
        "cancellable": True,
    }
    result = adapter.replace_open_limit(order, limit_price=210.0)
    client.replace_equity_limit.assert_not_called()
    assert "replace skipped" in (result.error_message or "")


def test_stale_paper_order_is_cancelled_and_freed(monkeypatch):
    """A paper Day order stuck past the expiry window frees the rotation lock."""
    from app.services import tastytrade_reconcile as tr

    db = MagicMock()
    stale = _submitted_buy(
        created_at=datetime.now(timezone.utc) - timedelta(hours=26),
    )
    db.query.return_value.filter.return_value.all.return_value = [stale]
    db.get.return_value = None

    class _Client:
        def configured(self):
            return True

        def cancel_order(self, oid):
            return {"status": "Cancelled"}

    monkeypatch.setattr(tr, "_client_for_order", lambda order: _Client())
    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: __import__("app.config", fromlist=["Settings"]).Settings(
            order_stuck_expire_hours=20.0, order_stuck_alert_hours=2.0
        ),
    )
    updated = tr.reconcile_submitted_tastytrade_orders(db)
    assert updated == 1
    assert stale.status == OrderStatus.cancelled
    assert "stale submitted" in (stale.error_message or "")


def test_stale_live_order_is_never_auto_expired(monkeypatch):
    """Live money must not auto-expire on a token gap — alert only, keep the lock."""
    from app.services import tastytrade_reconcile as tr

    db = MagicMock()
    stale_live = _submitted_buy(
        execution_mode=ExecutionMode.live,
        execution_payload={"mode": "tastytrade"},
        created_at=datetime.now(timezone.utc) - timedelta(hours=26),
    )
    db.query.return_value.filter.return_value.all.return_value = [stale_live]
    db.get.return_value = None

    class _Client:
        def configured(self):
            return False

        def cancel_order(self, oid):
            raise AssertionError("live order must not be cancelled")

    monkeypatch.setattr(tr, "_client_for_order", lambda order: _Client())
    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: __import__("app.config", fromlist=["Settings"]).Settings(
            order_stuck_expire_hours=20.0, order_stuck_alert_hours=2.0
        ),
    )
    updated = tr.reconcile_submitted_tastytrade_orders(db)
    assert updated == 0
    assert stale_live.status == OrderStatus.submitted
