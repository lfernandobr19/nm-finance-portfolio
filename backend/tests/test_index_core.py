"""Index Core: autonomous index DCA (kill switch, regime guard, fractional buy)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.domain.models import (
    AccountCurrency,
    ExecutionMode,
    InvestmentAccount,
    OrderStatus,
    StrategyKind,
)


def _account(**kw) -> InvestmentAccount:
    defaults = dict(
        id="acc1",
        name="NM USD Paper",
        owner_user_id="u1",
        broker_code="tastytrade",
        currency=AccountCurrency.USD,
        execution_mode=ExecutionMode.paper,
        cash_usd=100.0,
        hv_dip_equity_usd=100.0,
        max_ticket_brl=100.0,
        automation_paused=False,
    )
    defaults.update(kw)
    return InvestmentAccount(**defaults)


def _settings(**kw) -> Settings:
    base = dict(
        index_core_enabled=True,
        index_core_account_id="",
        index_core_tickers="QQQ",
        index_core_weekly_usd=50.0,
        index_core_interval_seconds=604800,
        index_core_regime_guard=False,
    )
    base.update(kw)
    return Settings(**base)


def test_kill_switch_blocks_contribution(monkeypatch):
    from app.services import index_core as ic

    monkeypatch.setattr(ic, "get_settings", lambda: _settings())
    monkeypatch.setattr(ic, "_resolve_account", lambda db: _account(automation_paused=True))
    adapter = MagicMock()
    monkeypatch.setattr("app.services.broker.get_broker_adapter", lambda acc: adapter)

    db = MagicMock()
    placed = ic.run_index_core_cycle(db)
    assert placed == 0
    adapter.submit_order.assert_not_called()


def test_regime_guard_skips_contribution(monkeypatch):
    from app.services import index_core as ic

    monkeypatch.setattr(
        ic, "get_settings", lambda: _settings(index_core_regime_guard=True)
    )
    monkeypatch.setattr(ic, "_resolve_account", lambda db: _account())
    monkeypatch.setattr(ic, "_last_close", lambda ticker: 500.0)
    monkeypatch.setattr(ic, "_regime_allows", lambda ticker: False)
    adapter = MagicMock()
    monkeypatch.setattr("app.services.broker.get_broker_adapter", lambda acc: adapter)

    db = MagicMock()
    placed = ic.run_index_core_cycle(db)
    assert placed == 0
    adapter.submit_order.assert_not_called()


def test_places_fractional_when_price_exceeds_weekly(monkeypatch):
    from app.services import index_core as ic
    from app.services import desk_gate as dg

    monkeypatch.setattr(ic, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        dg,
        "get_settings",
        lambda: Settings(
            desk_gate_enabled=True,
            desk_gate_enforce=True,
            desk_gate_queue_enabled=False,
            desk_gate_usd_budgets="index_core=1",
            desk_gate_protect_enabled=False,
            desk_gate_regime_lock=False,
        ),
    )
    monkeypatch.setattr(ic, "_resolve_account", lambda db: _account())
    monkeypatch.setattr(ic, "_last_close", lambda ticker: 500.0)

    adapter = MagicMock()
    adapter.submit_order.return_value = MagicMock(
        status=OrderStatus.filled,
        broker_order_id="TT-IC-FRAC",
        filled_price=500.0,
        error_message=None,
        execution_payload={"mode": "tastytrade_sandbox"},
    )
    monkeypatch.setattr("app.services.broker.get_broker_adapter", lambda acc: adapter)
    monkeypatch.setattr("app.services.positions.open_position_from_fill", lambda *a, **k: None)

    added: list = []
    db = MagicMock()
    db.add.side_effect = added.append
    placed = ic.run_index_core_cycle(db)
    assert placed == 1
    adapter.submit_order.assert_called_once()
    order = adapter.submit_order.call_args.args[0]
    assert order.quantity == pytest.approx(0.1)  # 50 / 500
    assert order.amount_brl == pytest.approx(50.0)


def test_places_when_one_share_fits(monkeypatch):
    from app.services import index_core as ic
    from app.services import desk_gate as dg

    monkeypatch.setattr(ic, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        dg,
        "get_settings",
        lambda: Settings(
            desk_gate_enabled=True,
            desk_gate_enforce=True,
            desk_gate_queue_enabled=False,
            desk_gate_usd_budgets="index_core=1",
            desk_gate_protect_enabled=False,
            desk_gate_regime_lock=False,
        ),
    )
    monkeypatch.setattr(ic, "_resolve_account", lambda db: _account())
    monkeypatch.setattr(ic, "_last_close", lambda ticker: 20.0)

    adapter = MagicMock()
    adapter.submit_order.return_value = MagicMock(
        status=OrderStatus.filled,
        broker_order_id="TT-IC-1",
        filled_price=20.0,
        error_message=None,
        execution_payload={"mode": "tastytrade_sandbox"},
    )
    monkeypatch.setattr("app.services.broker.get_broker_adapter", lambda acc: adapter)
    monkeypatch.setattr("app.services.positions.open_position_from_fill", lambda *a, **k: None)

    added: list = []
    db = MagicMock()
    db.add.side_effect = added.append

    placed = ic.run_index_core_cycle(db)
    assert placed == 1
    adapter.submit_order.assert_called_once()

    order = adapter.submit_order.call_args.args[0]
    assert order.strategy_kind == StrategyKind.index_core
    assert order.quantity == pytest.approx(2.5)  # 50 / 20
    assert order.amount_brl == pytest.approx(50.0)

    suggestions = [o for o in added if o.__class__.__name__ == "Suggestion"]
    assert len(suggestions) == 1
    assert suggestions[0].strategy_kind == StrategyKind.index_core


def test_auto_pick_usd_tastytrade_account(monkeypatch):
    from app.services import index_core as ic

    monkeypatch.setattr(ic, "get_settings", lambda: _settings(index_core_account_id=""))
    account = _account()
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = account

    resolved = ic._resolve_account(db)
    assert resolved is account
