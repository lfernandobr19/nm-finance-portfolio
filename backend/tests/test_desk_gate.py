"""Desk gate: shadow/enforce, protections, allocate, regime, learn skip."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.domain.models import (
    AccountCurrency,
    DeskDecision,
    ExecutionMode,
    InvestmentAccount,
    StrategyKind,
)
from app.services.desk_gate import (
    DeskIntent,
    allocate_pending,
    evaluate_gate,
    parse_slices,
    propose_or_place,
)


def _account(**kw) -> InvestmentAccount:
    defaults = dict(
        id="acc1",
        name="NM Paper",
        owner_user_id="u1",
        broker_code="tastytrade",
        currency=AccountCurrency.USD,
        execution_mode=ExecutionMode.paper,
        cash_usd=100.0,
        hv_dip_equity_usd=100.0,
        hv_dip_cash_floor_pct=20.0,
        max_ticket_brl=100.0,
        automation_paused=False,
    )
    defaults.update(kw)
    return InvestmentAccount(**defaults)


def _gate_settings(**kw) -> Settings:
    base = dict(
        desk_gate_enabled=True,
        desk_gate_enforce=True,
        desk_gate_queue_enabled=False,
        desk_gate_usd_budgets="hv_dip=0.4,index_core=0.4,mega_rotation=0",
        desk_gate_window_seconds=300,
        desk_gate_protect_enabled=False,
        desk_gate_regime_lock=False,
        desk_gate_learn_enabled=False,
        desk_gate_calibration_enabled=False,
        desk_judgment_enabled=False,
    )
    base.update(kw)
    return Settings(**base)


def _intent(account=None, **kw) -> DeskIntent:
    defaults = dict(
        account=account or _account(),
        kind=StrategyKind.mega_rotation,
        ticker="NIO",
        notional=25.0,
        price=20.0,
        score=80.0,
    )
    defaults.update(kw)
    return DeskIntent(**defaults)


def test_parse_slices_defaults_and_override():
    slices = parse_slices("hv_dip=0.4,index_core=0.4,mega_rotation=0")
    assert slices["mega_rotation"] == pytest.approx(0.0)
    assert slices["hv_dip"] == pytest.approx(0.4)


def test_live_without_flag_skips_the_gate(monkeypatch):
    from app.services import desk_gate as dg

    monkeypatch.setattr(dg, "get_settings", lambda: _gate_settings())
    live = _account(execution_mode=ExecutionMode.live)
    v = evaluate_gate(MagicMock(), _intent(account=live))
    assert v.reason == "not_usd_paper"
    assert v.allow is True


def test_live_as_paper_shadows_and_does_not_enforce(monkeypatch):
    from app.services import desk_gate as dg

    monkeypatch.setattr(dg, "get_settings", lambda: _gate_settings())
    live = _account(execution_mode=ExecutionMode.live)
    v = evaluate_gate(MagicMock(), _intent(account=live), as_paper=True)
    assert v.enforce is False
    assert v.reason != "not_usd_paper"


def test_live_with_auto_buy_flag_uses_paper_rules(monkeypatch):
    from app.services import desk_gate as dg

    monkeypatch.setattr(
        dg, "get_settings", lambda: _gate_settings(hv_dip_live_auto_buy=True)
    )
    live = _account(execution_mode=ExecutionMode.live)
    v = evaluate_gate(MagicMock(), _intent(account=live, kind=StrategyKind.hv_dip))
    assert v.reason != "not_usd_paper"


def test_unaffordable_always_denies(monkeypatch):
    from app.services import desk_gate as dg

    monkeypatch.setattr(dg, "get_settings", lambda: _gate_settings())
    v = evaluate_gate(MagicMock(), _intent(price=180.0, notional=25.0, ticker="AMZN"))
    assert v.allow is False
    assert v.reason == "unaffordable"


def test_one_share_rounding_is_not_unaffordable(monkeypatch):
    from app.services import desk_gate as dg

    monkeypatch.setattr(
        dg,
        "get_settings",
        lambda: _gate_settings(desk_gate_usd_budgets="mega_rotation=1"),
    )
    v = evaluate_gate(
        MagicMock(),
        _intent(
            account=_account(cash_usd=300.0, hv_dip_equity_usd=300.0),
            ticker="NVDA",
            price=218.860107,
            notional=218.86,
        ),
    )
    assert v.allow is True
    assert v.reason == "ok"


def test_index_fractional_qqq_allows(monkeypatch):
    from app.services import desk_gate as dg

    monkeypatch.setattr(dg, "get_settings", lambda: _gate_settings())
    v = evaluate_gate(
        MagicMock(),
        _intent(kind=StrategyKind.index_core, ticker="QQQ", notional=50.0, price=480.0),
    )
    assert v.allow is True
    assert v.reason == "ok"


def test_index_clips_notional_to_remaining_slice(monkeypatch):
    from app.services import desk_gate as dg

    monkeypatch.setattr(dg, "get_settings", lambda: _gate_settings())
    intent = _intent(kind=StrategyKind.index_core, ticker="QQQ", notional=50.0, price=480.0)
    v = evaluate_gate(MagicMock(), intent)
    assert v.allow is True
    # equity ~100, slice 40% → cap 40; weekly 50 is clipped, not denied.
    assert intent.notional == pytest.approx(40.0)


def test_regime_chop_denies_hv_dip_allows_index(monkeypatch):
    from app.services import desk_gate as dg

    monkeypatch.setattr(
        dg,
        "get_settings",
        lambda: _gate_settings(desk_gate_regime_lock=True),
    )
    monkeypatch.setattr(dg, "spy_regime", lambda db=None: "chop")
    hv = evaluate_gate(MagicMock(), _intent(kind=StrategyKind.hv_dip, notional=20.0, price=20.0))
    assert hv.allow is False
    assert hv.reason == "regime_lock"
    ix = evaluate_gate(
        MagicMock(),
        _intent(kind=StrategyKind.index_core, ticker="QQQ", notional=20.0, price=480.0),
    )
    assert ix.allow is True
    assert ix.reason == "ok"


def test_mega_budget_zero_denies(monkeypatch):
    from app.services import desk_gate as dg

    monkeypatch.setattr(dg, "get_settings", lambda: _gate_settings())
    v = evaluate_gate(MagicMock(), _intent(price=20.0, notional=25.0))
    assert v.allow is False
    assert v.reason == "budget"


def test_index_budget_allows_when_slice_fits(monkeypatch):
    from app.services import desk_gate as dg

    monkeypatch.setattr(dg, "get_settings", lambda: _gate_settings())
    v = evaluate_gate(
        MagicMock(),
        _intent(kind=StrategyKind.index_core, ticker="QQQ", notional=20.0, price=20.0),
    )
    assert v.allow is True
    assert v.reason == "ok"


def test_shadow_does_not_block_budget(monkeypatch):
    from app.services import desk_gate as dg

    monkeypatch.setattr(dg, "get_settings", lambda: _gate_settings(desk_gate_enforce=False))
    v = evaluate_gate(MagicMock(), _intent(price=20.0, notional=25.0))
    assert v.allow is True
    assert v.shadow is True
    assert v.reason == "budget"


def test_paused_denies(monkeypatch):
    from app.services import desk_gate as dg

    monkeypatch.setattr(dg, "get_settings", lambda: _gate_settings())
    v = evaluate_gate(MagicMock(), _intent(account=_account(automation_paused=True)))
    assert v.allow is False
    assert v.reason == "paused"


def test_live_usd_skips_enforce(monkeypatch):
    from app.services import desk_gate as dg

    monkeypatch.setattr(dg, "get_settings", lambda: _gate_settings())
    v = evaluate_gate(
        MagicMock(),
        _intent(account=_account(execution_mode=ExecutionMode.live), price=20.0, notional=25.0),
    )
    assert v.allow is True
    assert v.reason == "not_usd_paper"


def test_stoploss_guard(monkeypatch):
    from app.services import desk_gate as dg

    monkeypatch.setattr(
        dg,
        "get_settings",
        lambda: _gate_settings(
            desk_gate_protect_enabled=True,
            desk_gate_usd_budgets="mega_rotation=1",
        ),
    )
    monkeypatch.setattr(dg, "_stoploss_count", lambda *a, **k: 4)
    v = evaluate_gate(MagicMock(), _intent(notional=20.0, price=20.0))
    assert v.allow is False
    assert v.reason == "stoploss_guard"


def test_cooldown(monkeypatch):
    from app.services import desk_gate as dg

    monkeypatch.setattr(
        dg,
        "get_settings",
        lambda: _gate_settings(
            desk_gate_protect_enabled=True,
            desk_gate_usd_budgets="mega_rotation=1",
        ),
    )
    monkeypatch.setattr(dg, "_cooldown_active", lambda *a, **k: True)
    v = evaluate_gate(MagicMock(), _intent(notional=20.0, price=20.0))
    assert v.allow is False
    assert v.reason == "cooldown"


def test_max_drawdown(monkeypatch):
    from app.services import desk_gate as dg

    monkeypatch.setattr(
        dg,
        "get_settings",
        lambda: _gate_settings(
            desk_gate_protect_enabled=True,
            desk_gate_usd_budgets="mega_rotation=1",
            desk_gate_max_drawdown_pct=20.0,
        ),
    )
    monkeypatch.setattr(dg, "account_equity_usd", lambda db, acc: 75.0)
    monkeypatch.setattr(dg, "_peak_and_touch", lambda db, eq: 100.0)
    v = evaluate_gate(MagicMock(), _intent(notional=20.0, price=20.0))
    assert v.allow is False
    assert v.reason == "max_drawdown"


def test_low_profit_pair(monkeypatch):
    from app.services import desk_gate as dg

    monkeypatch.setattr(
        dg,
        "get_settings",
        lambda: _gate_settings(
            desk_gate_protect_enabled=True,
            desk_gate_usd_budgets="mega_rotation=1",
        ),
    )
    monkeypatch.setattr(dg, "_ticker_expectancy", lambda *a, **k: -0.2)
    v = evaluate_gate(MagicMock(), _intent(notional=20.0, price=20.0))
    assert v.allow is False
    assert v.reason == "low_profit_pair"


def test_regime_chop_denies(monkeypatch):
    from app.services import desk_gate as dg

    monkeypatch.setattr(
        dg,
        "get_settings",
        lambda: _gate_settings(
            desk_gate_regime_lock=True,
            desk_gate_usd_budgets="mega_rotation=1",
        ),
    )
    monkeypatch.setattr(dg, "spy_regime", lambda db=None: "chop")
    v = evaluate_gate(MagicMock(), _intent(notional=20.0, price=20.0))
    assert v.allow is False
    assert v.reason == "regime_lock"


def test_regime_trend_allows(monkeypatch):
    from app.services import desk_gate as dg

    monkeypatch.setattr(
        dg,
        "get_settings",
        lambda: _gate_settings(
            desk_gate_regime_lock=True,
            desk_gate_usd_budgets="mega_rotation=1",
        ),
    )
    monkeypatch.setattr(dg, "spy_regime", lambda db=None: "trend")
    v = evaluate_gate(MagicMock(), _intent(notional=20.0, price=20.0))
    assert v.allow is True


def test_regime_unknown_fail_closed(monkeypatch):
    from app.services import desk_gate as dg

    monkeypatch.setattr(
        dg,
        "get_settings",
        lambda: _gate_settings(
            desk_gate_regime_lock=True,
            desk_gate_regime_fail_closed=True,
            desk_gate_usd_budgets="mega_rotation=1",
        ),
    )
    monkeypatch.setattr(dg, "spy_regime", lambda db=None: "unknown")
    v = evaluate_gate(MagicMock(), _intent(notional=20.0, price=20.0))
    assert v.allow is False
    assert v.reason == "regime_lock"


def test_window_busy_on_allocate(monkeypatch):
    from app.services import desk_gate as dg

    monkeypatch.setattr(
        dg,
        "get_settings",
        lambda: _gate_settings(desk_gate_usd_budgets="mega_rotation=1"),
    )
    monkeypatch.setattr(dg, "_recent_auto_buys", lambda *a, **k: 1)
    v = evaluate_gate(MagicMock(), _intent(notional=20.0, price=20.0), for_allocate=True)
    assert v.allow is False
    assert v.reason == "window_busy"


def test_allocate_picks_one_of_three(monkeypatch):
    from app.services import desk_gate as dg

    monkeypatch.setattr(
        dg,
        "get_settings",
        lambda: _gate_settings(desk_gate_usd_budgets="mega_rotation=1,index_core=1,hv_dip=1"),
    )
    account = _account()
    rows = [
        DeskDecision(
            id="d1",
            account_id=account.id,
            strategy_kind=StrategyKind.mega_rotation,
            ticker="AAPL",
            verdict="pending",
            reason="ok",
            notional=20.0,
            price=20.0,
            cash_before=100.0,
            score=10.0,
            payload={},
        ),
        DeskDecision(
            id="d2",
            account_id=account.id,
            strategy_kind=StrategyKind.index_core,
            ticker="QQQ",
            verdict="pending",
            reason="ok",
            notional=20.0,
            price=20.0,
            cash_before=100.0,
            score=90.0,
            payload={},
        ),
        DeskDecision(
            id="d3",
            account_id=account.id,
            strategy_kind=StrategyKind.hv_dip,
            ticker="NIO",
            verdict="pending",
            reason="ok",
            notional=20.0,
            price=20.0,
            cash_before=100.0,
            score=40.0,
            payload={},
        ),
    ]
    db = MagicMock()
    db.get.return_value = account
    monkeypatch.setattr(dg, "load_pending", lambda db, account_id=None: rows)
    placed_tickers: list[str] = []

    def _place(db, intent):
        placed_tickers.append(intent.ticker)
        return 1

    monkeypatch.setattr(dg, "place_auto_order", _place)
    n = allocate_pending(db)
    assert n == 1
    assert placed_tickers == ["QQQ"]
    assert rows[1].verdict == "allow"
    assert rows[0].verdict == "not_selected"
    assert rows[2].verdict == "not_selected"


def test_propose_unaffordable_does_not_place(monkeypatch):
    from app.services import desk_gate as dg

    monkeypatch.setattr(dg, "get_settings", lambda: _gate_settings())
    adapter_place = MagicMock()
    monkeypatch.setattr(dg, "place_auto_order", adapter_place)
    db = MagicMock()
    n = propose_or_place(db, _intent(ticker="AMZN", price=180.0, notional=25.0))
    assert n == 0
    adapter_place.assert_not_called()


def test_learn_skips_when_n_below_floor(monkeypatch):
    from app.services import desk_learn as dl

    monkeypatch.setattr(
        dl, "get_settings", lambda: _gate_settings(desk_gate_learn_enabled=True)
    )
    monkeypatch.setattr(dl, "load_closed_usd_auto", lambda db: [{"kind": "hv_dip", "r": 1.0}] * 5)
    res = dl.run_budget_learning(MagicMock())
    assert res["status"] == "no_data"


def test_job_desk_allocate_is_registered():
    from app.workers.arq_settings import WorkerSettings
    from app.workers.jobs import job_desk_allocate

    assert job_desk_allocate in WorkerSettings.functions


def test_working_order_blocks_second_buy(monkeypatch):
    from app.domain.models import Order, OrderSide, OrderStatus
    from app.services import desk_gate as dg

    dummy = Order(
        id="o-nvda",
        account_id="acc1",
        ticker="NVDA",
        strategy_kind=StrategyKind.mega_rotation,
        side=OrderSide.buy,
        quantity=1.0,
        amount_brl=218.86,
        limit_price=218.86,
        status=OrderStatus.submitted,
        broker="tastytrade",
        execution_mode=ExecutionMode.paper,
        broker_order_id="1650607",
        execution_payload={},
    )
    monkeypatch.setattr(dg, "get_settings", lambda: _gate_settings(desk_gate_usd_budgets="mega_rotation=1"))
    monkeypatch.setattr(dg, "account_equity_usd", lambda *a, **k: 300.0)
    monkeypatch.setattr(dg, "deployed_kind_usd", lambda *a, **k: 0.0)
    monkeypatch.setattr(dg, "working_order", lambda *a, **k: dummy)
    monkeypatch.setattr(
        "app.services.broker.get_broker_adapter",
        lambda acc: MagicMock(**{"replace_open_limit.return_value": None}),
    )
    verdict = evaluate_gate(
        MagicMock(),
        _intent(
            _account(cash_usd=300.0),
            kind=StrategyKind.mega_rotation,
            ticker="NVDA",
            notional=218.86,
            price=218.86,
        ),
    )
    assert verdict.allow is False
    assert verdict.reason == "working_order"
