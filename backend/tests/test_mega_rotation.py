"""Mega Rotation: single-cash rotation among liquid mega-caps (unit tests)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.domain.models import (
    AccountCurrency,
    ExecutionMode,
    InvestmentAccount,
    OrderStatus,
    Position,
    PositionStatus,
    StrategyKind,
)


def _account(**kw) -> InvestmentAccount:
    defaults = dict(
        id="acc1",
        name="NM Rotation Paper",
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
        mega_rotation_enabled=True,
        mega_rotation_account_id="",
        mega_rotation_tickers="AAPL,MSFT,NVDA",
        mega_rotation_dip_pct=5.0,
        mega_rotation_giveback_pct=3.0,
        mega_rotation_lookback=20,
        mega_rotation_confirm=False,
        mega_rotation_position_usd=25.0,
        mega_rotation_interval_seconds=300,
    )
    base.update(kw)
    return Settings(**base)


def _bar(day_offset, o, h, l, c):
    from app.services.brapi_client import Bar

    from datetime import datetime, timedelta, timezone

    dt = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=day_offset)
    return Bar(date=dt, open=o, high=h, low=l, close=c, volume=1e6)


def _bars_from_closes(closes: list[float]) -> list:
    out = []
    for i, c in enumerate(closes):
        out.append(_bar(i, c, c * 1.01, c * 0.99, c))
    return out


def _position(ticker="AAPL", entry=100.0, metrics=None, **kw) -> Position:
    from datetime import datetime, timedelta, timezone

    opened_at = kw.pop("opened_at", datetime.now(timezone.utc) - timedelta(days=3))
    return Position(
        id="p1",
        account_id="acc1",
        order_id="o1",
        suggestion_id="s1",
        ticker=ticker,
        strategy_kind=StrategyKind.mega_rotation,
        quantity=0.25,
        entry_price=entry,
        stop_price=None,
        target_price=None,
        status=PositionStatus.open,
        metrics=metrics or {},
        opened_at=opened_at,
        **kw,
    )


# ---- entry selection -----------------------------------------------------

def test_pick_entry_returns_deepest_dip(monkeypatch):
    from app.services import mega_rotation as mr

    closes = [100.0] * 30 + [90.0]  # AAPL dipped 10%
    monkeypatch.setattr(mr, "_daily_bars", lambda t: _bars_from_closes(closes))
    pick = mr._pick_entry(
        ["AAPL"], dip_pct=5.0, lookback=20, confirm=False, prices={"AAPL": 90.0}
    )
    assert pick is not None
    assert pick[0] == "AAPL"
    assert pick[1] == pytest.approx(90.0)
    assert pick[2] == pytest.approx(10.89, rel=0.02)


def test_pick_entry_skips_when_no_dip(monkeypatch):
    from app.services import mega_rotation as mr

    closes = [100.0] * 30
    monkeypatch.setattr(mr, "_daily_bars", lambda t: _bars_from_closes(closes))
    pick = mr._pick_entry(
        ["AAPL"], dip_pct=5.0, lookback=20, confirm=False, prices={"AAPL": 100.0}
    )
    assert pick is None


def test_pick_entry_confirm_requires_turn_up(monkeypatch):
    from app.services import mega_rotation as mr

    # Still falling today: confirm blocks the entry.
    falling = [100.0] * 30 + [90.0, 88.0]
    monkeypatch.setattr(mr, "_daily_bars", lambda t: _bars_from_closes(falling))
    pick = mr._pick_entry(
        ["AAPL"], dip_pct=5.0, lookback=20, confirm=True, prices={"AAPL": 88.0}
    )
    assert pick is None

    # Turned up today: confirm allows it.
    turning = [100.0] * 30 + [90.0, 91.0]
    monkeypatch.setattr(mr, "_daily_bars", lambda t: _bars_from_closes(turning))
    pick = mr._pick_entry(
        ["AAPL"], dip_pct=5.0, lookback=20, confirm=True, prices={"AAPL": 91.0}
    )
    assert pick is not None


# ---- cycle gating --------------------------------------------------------

def test_cycle_disabled(monkeypatch):
    from app.services import mega_rotation as mr

    monkeypatch.setattr(
        mr, "get_settings", lambda: _settings(mega_rotation_enabled=False)
    )
    assert mr.run_mega_rotation_cycle(MagicMock()) == 0


def test_cycle_kill_switch_blocks(monkeypatch):
    from app.services import mega_rotation as mr

    monkeypatch.setattr(mr, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        mr, "_resolve_account", lambda db: _account(automation_paused=True)
    )
    adapter = MagicMock()
    monkeypatch.setattr("app.services.broker.get_broker_adapter", lambda acc: adapter)
    db = MagicMock()
    assert mr.run_mega_rotation_cycle(db) == 0
    adapter.submit_order.assert_not_called()


# ---- trailing stop -------------------------------------------------------

def test_sell_when_giveback_exceeded(monkeypatch):
    from app.services import mega_rotation as mr
    from app.services import desk_judgment as dj

    monkeypatch.setattr(mr, "get_settings", lambda: _settings())
    monkeypatch.setattr(mr, "_mark_prices", lambda tickers: {"AAPL": 92.0})
    monkeypatch.setattr(dj, "load_news", lambda db, ticker, days=7: [])
    monkeypatch.setattr(dj, "load_memories", lambda ticker: [])
    monkeypatch.setattr(dj, "get_settings", lambda: Settings(desk_judgment_enabled=True))

    pos = _position(entry=100.0, metrics={"peak_price": 100.0})
    db = MagicMock()
    db.get.return_value = _account()

    sold = mr._maybe_sell(db, _account(), pos)
    assert sold == 1
    assert pos.status == PositionStatus.closed


def test_hold_shallow_giveback_when_thesis_intact(monkeypatch):
    from app.services import mega_rotation as mr
    from app.services import desk_judgment as dj

    monkeypatch.setattr(mr, "get_settings", lambda: _settings())
    monkeypatch.setattr(mr, "_mark_prices", lambda tickers: {"AAPL": 96.9})
    monkeypatch.setattr(dj, "load_news", lambda db, ticker, days=7: [])
    monkeypatch.setattr(dj, "load_memories", lambda ticker: [])
    monkeypatch.setattr(dj, "get_settings", lambda: Settings(desk_judgment_enabled=True))

    pos = _position(entry=100.0, metrics={"peak_price": 100.0})
    db = MagicMock()
    db.get.return_value = _account()

    sold = mr._maybe_sell(db, _account(), pos)
    assert sold == 0
    assert pos.status == PositionStatus.open


def test_sell_on_scandal_even_above_giveback(monkeypatch):
    from types import SimpleNamespace

    from app.services import mega_rotation as mr
    from app.services import desk_judgment as dj

    monkeypatch.setattr(mr, "get_settings", lambda: _settings())
    monkeypatch.setattr(mr, "_mark_prices", lambda tickers: {"AAPL": 99.0})
    monkeypatch.setattr(
        dj,
        "load_news",
        lambda db, ticker, days=7: [
            SimpleNamespace(
                ticker="AAPL",
                title="AAPL bankruptcy filing after accounting fraud",
                event_type="litigation",
                sentiment="bearish",
                confidence=0.9,
            )
        ],
    )
    monkeypatch.setattr(dj, "load_memories", lambda ticker: [])
    monkeypatch.setattr(dj, "get_settings", lambda: Settings(desk_judgment_enabled=True))

    pos = _position(entry=100.0, metrics={"peak_price": 100.0})
    db = MagicMock()
    db.get.return_value = _account()

    sold = mr._maybe_sell(db, _account(), pos)
    assert sold == 1
    assert pos.status == PositionStatus.closed


def test_hold_when_above_giveback(monkeypatch):
    from app.services import mega_rotation as mr

    monkeypatch.setattr(mr, "get_settings", lambda: _settings(giveback_pct=3.0))
    monkeypatch.setattr(mr, "_mark_prices", lambda tickers: {"AAPL": 99.0})

    pos = _position(entry=100.0, metrics={"peak_price": 100.0})
    db = MagicMock()
    db.get.return_value = _account()

    sold = mr._maybe_sell(db, _account(), pos)
    assert sold == 0
    assert pos.status == PositionStatus.open
    # peak updated to the higher mark
    assert pos.metrics["peak_price"] == pytest.approx(100.0)


def test_sell_peak_tracks_high_water(monkeypatch):
    from app.services import mega_rotation as mr

    monkeypatch.setattr(mr, "get_settings", lambda: _settings(giveback_pct=3.0))
    monkeypatch.setattr(mr, "_mark_prices", lambda tickers: {"AAPL": 110.0})

    # peak was 100, price ran to 110 then fell to 106 (still above 110*0.97)
    pos = _position(entry=100.0, metrics={"peak_price": 100.0})
    db = MagicMock()
    db.get.return_value = _account()

    # first mark: 110 → peak becomes 110, hold
    sold = mr._maybe_sell(db, _account(), pos)
    assert sold == 0
    assert pos.metrics["peak_price"] == pytest.approx(110.0)


# ---- auto-pick account ---------------------------------------------------

def test_buy_proposes_one_share_when_ticket_is_below_price(monkeypatch):
    from app.services import mega_rotation as mr
    from app.services import desk_gate as dg
    from app.domain.models import OrderStatus

    monkeypatch.setattr(mr, "get_settings", lambda: _settings(mega_rotation_position_usd=25.0))
    monkeypatch.setattr(
        dg,
        "get_settings",
        lambda: Settings(
            desk_gate_enabled=True,
            desk_gate_enforce=True,
            desk_gate_queue_enabled=False,
            desk_gate_usd_budgets="mega_rotation=1",
            desk_gate_protect_enabled=False,
            desk_gate_regime_lock=False,
            desk_gate_calibration_enabled=False,
            desk_judgment_enabled=True,
            mega_rotation_account_id="",
        ),
    )
    from app.services import desk_judgment as dj

    monkeypatch.setattr(dj, "load_news", lambda db, ticker, days=7: [])
    monkeypatch.setattr(dj, "load_memories", lambda ticker: [])
    monkeypatch.setattr(dj, "get_settings", lambda: Settings(desk_judgment_enabled=True))
    adapter = MagicMock()
    adapter.submit_order.return_value = MagicMock(
        status=OrderStatus.rejected,
        broker_order_id=None,
        filled_price=None,
        error_message="paper",
        execution_payload={},
    )
    monkeypatch.setattr("app.services.broker.get_broker_adapter", lambda acc: adapter)
    db = MagicMock()
    assert mr._buy(db, _account(cash_usd=300.0, hv_dip_equity_usd=300.0), "NVDA", 219.0) == 1
    adapter.submit_order.assert_called_once()


def test_buy_skips_when_one_share_exceeds_cash(monkeypatch):
    from app.services import mega_rotation as mr
    from app.domain.models import Order

    monkeypatch.setattr(mr, "get_settings", lambda: _settings(mega_rotation_position_usd=25.0))
    adapter = MagicMock()
    monkeypatch.setattr("app.services.broker.get_broker_adapter", lambda acc: adapter)
    added: list = []
    db = MagicMock()
    db.add.side_effect = added.append
    assert mr._buy(db, _account(), "AMZN", 180.0) == 0
    adapter.submit_order.assert_not_called()
    assert not any(o.__class__.__name__ == "Order" or isinstance(o, Order) for o in added)


def test_buy_places_when_one_share_fits(monkeypatch):
    from app.services import mega_rotation as mr
    from app.services import desk_gate as dg
    from app.domain.models import OrderStatus

    monkeypatch.setattr(mr, "get_settings", lambda: _settings(mega_rotation_position_usd=25.0))
    monkeypatch.setattr(
        dg,
        "get_settings",
        lambda: Settings(
            desk_gate_enabled=True,
            desk_gate_enforce=True,
            desk_gate_queue_enabled=False,
            desk_gate_usd_budgets="mega_rotation=1",
            desk_gate_protect_enabled=False,
            desk_gate_regime_lock=False,
            desk_gate_calibration_enabled=False,
            desk_judgment_enabled=True,
        ),
    )
    adapter = MagicMock()
    adapter.submit_order.return_value = MagicMock(
        status=OrderStatus.rejected,
        broker_order_id=None,
        filled_price=None,
        error_message="paper",
        execution_payload={},
    )
    monkeypatch.setattr("app.services.broker.get_broker_adapter", lambda acc: adapter)
    db = MagicMock()
    assert mr._buy(db, _account(), "NIO", 20.0) == 1
    adapter.submit_order.assert_called_once()
    assert db.add.call_count >= 2


def test_auto_pick_usd_tastytrade_account(monkeypatch):
    from app.services import mega_rotation as mr

    monkeypatch.setattr(mr, "get_settings", lambda: _settings(mega_rotation_account_id=""))
    account = _account()
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = account
    assert mr._resolve_account(db) is account


def test_buy_skips_when_working_order_open(monkeypatch):
    from app.services import mega_rotation as mr
    from app.services import desk_gate as dg

    monkeypatch.setattr(mr, "get_settings", lambda: _settings())
    monkeypatch.setattr(dg, "load_pending", lambda *a, **k: [])
    monkeypatch.setattr(dg, "working_order", lambda *a, **k: object())
    monkeypatch.setattr("app.services.broker.get_broker_adapter", lambda acc: MagicMock())
    placed = []
    monkeypatch.setattr(dg, "propose_or_place", lambda *a, **k: placed.append(1) or 1)
    n = mr._buy(MagicMock(), _account(cash_usd=300.0), "NVDA", 218.86)
    assert n == 0
    assert placed == []
