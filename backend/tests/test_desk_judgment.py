"""Desk judgment: courage vs observe (numeric gates are priors)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.domain.models import (
    AccountCurrency,
    ExecutionMode,
    InvestmentAccount,
    StrategyKind,
)
from app.services.desk_gate import DeskIntent, evaluate_gate
from app.services.desk_judgment import consider, structural_risk


def _news(**kw) -> SimpleNamespace:
    defaults = dict(
        ticker="NVDA",
        title="NVIDIA announces new chip",
        event_type="product_launch",
        sentiment="bullish",
        confidence=0.8,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def test_scandal_headline_is_structural():
    ok, why = structural_risk(
        [_news(title="SEC investigation into accounting fraud", sentiment="bearish")]
    )
    assert ok is True
    assert "headline" in why


def test_bearish_litigation_is_structural():
    ok, why = structural_risk(
        [_news(event_type="litigation", sentiment="bearish", confidence=0.8, title="suit")]
    )
    assert ok is True
    assert "litigation" in why


def test_bullish_product_is_not_structural():
    ok, _ = structural_risk([_news()])
    assert ok is False


def test_observe_scandal_instead_of_buying_the_dip():
    j = consider(
        ticker="PATH",
        price=13.8,
        cash=300.0,
        deny_reason="fresh_high",
        news=[_news(title="PATH bankruptcy filing", sentiment="bearish")],
        dip_pct=25.0,
    )
    assert j is not None
    assert j.action == "observe"
    assert j.reason == "observe_structural"


def test_courage_resizes_cash_floor_to_one_share():
    j = consider(
        ticker="NVDA",
        price=219.0,
        cash=300.0,
        deny_reason="cash_floor",
        news=[],
        dip_pct=6.8,
    )
    assert j is not None
    assert j.action == "resize"
    assert j.reason == "judgment_courage"
    assert j.notional == pytest.approx(219.0)


def test_fresh_high_crash_is_lifted_without_scandal():
    j = consider(
        ticker="PATH",
        price=13.8,
        cash=300.0,
        deny_reason="fresh_high",
        news=[],
        dip_pct=26.7,
    )
    assert j is not None
    assert j.action == "allow"
    assert j.reason == "judgment_courage"


def test_no_cash_for_one_share_stays_denied():
    j = consider(
        ticker="NVDA",
        price=219.0,
        cash=100.0,
        deny_reason="cash_floor",
        news=[],
    )
    assert j is not None
    assert j.action == "deny"
    assert j.reason == "no_share"


def test_courage_overrides_a_hard_risk_lock():
    """Cooldown/drawdown/stoploss/regime/calibration are priors, not laws."""
    j = consider(
        ticker="NVDA",
        price=219.0,
        cash=300.0,
        deny_reason="cooldown",
        news=[],
        dip_pct=6.8,
    )
    assert j is not None
    assert j.action == "resize"
    assert j.reason == "judgment_courage"
    assert j.notional == pytest.approx(219.0)


def test_working_order_is_not_double_bought():
    """A working order is dedup (replace), never a courage double-buy."""
    j = consider(
        ticker="NVDA",
        price=219.0,
        cash=300.0,
        deny_reason="working_order",
        news=[],
    )
    assert j is None


def test_window_busy_stays_throttled():
    """The allocate throttle is operational, not a risk lock to lift."""
    j = consider(
        ticker="NVDA",
        price=219.0,
        cash=300.0,
        deny_reason="window_busy",
        news=[],
    )
    assert j is None


def _account(**kw) -> InvestmentAccount:
    defaults = dict(
        id="rot1",
        name="NM Rotation Paper",
        owner_user_id="u1",
        broker_code="tastytrade",
        currency=AccountCurrency.USD,
        execution_mode=ExecutionMode.paper,
        cash_usd=300.0,
        hv_dip_equity_usd=300.0,
        hv_dip_cash_floor_pct=20.0,
        max_ticket_brl=500.0,
        automation_paused=False,
    )
    defaults.update(kw)
    return InvestmentAccount(**defaults)


def _gate_on(**kw) -> Settings:
    base = dict(
        desk_gate_enabled=True,
        desk_gate_enforce=True,
        desk_gate_queue_enabled=False,
        desk_gate_usd_budgets="mega_rotation=1",
        desk_gate_protect_enabled=False,
        desk_gate_regime_lock=False,
        desk_gate_calibration_enabled=False,
        desk_judgment_enabled=True,
        mega_rotation_account_id="",
    )
    base.update(kw)
    return Settings(**base)


def test_gate_courage_allows_nvda_when_ticket_trips_floor(monkeypatch):
    from app.services import desk_gate as dg
    from app.services import desk_judgment as dj

    monkeypatch.setattr(dg, "get_settings", lambda: _gate_on())
    monkeypatch.setattr(dj, "load_news", lambda db, ticker, days=7: [])
    monkeypatch.setattr(dj, "load_memories", lambda ticker: [])
    monkeypatch.setattr(dj, "get_settings", lambda: Settings(desk_judgment_enabled=True))
    intent = DeskIntent(
        account=_account(),
        kind=StrategyKind.mega_rotation,
        ticker="NVDA",
        notional=250.0,
        price=219.0,
        score=100.0,
        metrics={"dip_pct": 6.8},
    )
    v = evaluate_gate(MagicMock(), intent)
    assert v.allow is True
    assert v.reason == "judgment_courage"
    assert intent.notional == pytest.approx(219.0)


def test_gate_observes_scandal_even_if_cash_fits(monkeypatch):
    from app.services import desk_gate as dg
    from app.services import desk_judgment as dj

    monkeypatch.setattr(dg, "get_settings", lambda: _gate_on())
    monkeypatch.setattr(
        dj,
        "load_news",
        lambda db, ticker, days=7: [
            _news(title="accounting fraud investigation", sentiment="bearish")
        ],
    )
    monkeypatch.setattr(dj, "load_memories", lambda ticker: [])
    monkeypatch.setattr(dj, "get_settings", lambda: Settings(desk_judgment_enabled=True))
    intent = DeskIntent(
        account=_account(),
        kind=StrategyKind.mega_rotation,
        ticker="NVDA",
        notional=250.0,
        price=219.0,
    )
    v = evaluate_gate(MagicMock(), intent)
    assert v.allow is False
    assert v.reason == "observe_structural"


def test_gate_observes_scandal_on_numeric_ok(monkeypatch):
    from app.services import desk_gate as dg
    from app.services import desk_judgment as dj

    monkeypatch.setattr(dg, "get_settings", lambda: _gate_on())
    monkeypatch.setattr(
        dj,
        "load_news",
        lambda db, ticker, days=7: [
            _news(title="PATH bankruptcy filing after accounting scandal", sentiment="bearish")
        ],
    )
    monkeypatch.setattr(dj, "load_memories", lambda ticker: [])
    monkeypatch.setattr(dj, "get_settings", lambda: Settings(desk_judgment_enabled=True))
    intent = DeskIntent(
        account=_account(cash_usd=10_000.0, hv_dip_equity_usd=10_000.0),
        kind=StrategyKind.mega_rotation,
        ticker="PATH",
        notional=219.0,
        price=219.0,
        metrics={"dip_pct": 25.0},
    )
    v = evaluate_gate(MagicMock(), intent)
    assert v.allow is False
    assert v.reason == "observe_structural"


def test_gate_courage_overrides_zero_budget(monkeypatch):
    from app.services import desk_gate as dg
    from app.services import desk_judgment as dj

    monkeypatch.setattr(
        dg,
        "get_settings",
        lambda: _gate_on(desk_gate_usd_budgets="hv_dip=0.4,index_core=0.4,mega_rotation=0"),
    )
    monkeypatch.setattr(dj, "load_news", lambda db, ticker, days=7: [])
    monkeypatch.setattr(dj, "load_memories", lambda ticker: [])
    monkeypatch.setattr(dj, "get_settings", lambda: Settings(desk_judgment_enabled=True))
    intent = DeskIntent(
        account=_account(),
        kind=StrategyKind.mega_rotation,
        ticker="NVDA",
        notional=250.0,
        price=219.0,
        score=100.0,
        metrics={"dip_pct": 6.8},
    )
    v = evaluate_gate(MagicMock(), intent)
    assert v.allow is True
    assert v.reason == "judgment_courage"
    assert intent.notional == pytest.approx(219.0)


def test_gate_courage_resizes_undersized_ticket(monkeypatch):
    from app.services import desk_gate as dg
    from app.services import desk_judgment as dj

    monkeypatch.setattr(dg, "get_settings", lambda: _gate_on())
    monkeypatch.setattr(dj, "load_news", lambda db, ticker, days=7: [])
    monkeypatch.setattr(dj, "load_memories", lambda ticker: [])
    monkeypatch.setattr(dj, "get_settings", lambda: Settings(desk_judgment_enabled=True))
    intent = DeskIntent(
        account=_account(),
        kind=StrategyKind.mega_rotation,
        ticker="NVDA",
        notional=25.0,
        price=219.0,
        score=100.0,
        metrics={"dip_pct": 6.8},
    )
    v = evaluate_gate(MagicMock(), intent)
    assert v.allow is True
    assert v.reason == "judgment_courage"
    assert intent.notional == pytest.approx(219.0)


def test_gate_courage_lifts_regime_lock(monkeypatch):
    from app.services import desk_gate as dg
    from app.services import desk_judgment as dj

    monkeypatch.setattr(
        dg, "get_settings", lambda: _gate_on(desk_gate_regime_lock=True)
    )
    monkeypatch.setattr(dg, "spy_regime", lambda db: "unknown")
    monkeypatch.setattr(dj, "load_news", lambda db, ticker, days=7: [])
    monkeypatch.setattr(dj, "load_memories", lambda ticker: [])
    monkeypatch.setattr(dj, "get_settings", lambda: Settings(desk_judgment_enabled=True))
    intent = DeskIntent(
        account=_account(),
        kind=StrategyKind.mega_rotation,
        ticker="NVDA",
        notional=218.86,
        price=218.86,
        score=100.0,
        metrics={"dip_pct": 6.8},
    )
    v = evaluate_gate(MagicMock(), intent)
    assert v.allow is True
    assert v.reason == "judgment_courage"


def test_apply_intent_courage_skips_queue(monkeypatch):
    from app.services import desk_gate as dg
    from app.services import desk_judgment as dj
    from app.services.desk_gate import apply_intent

    monkeypatch.setattr(
        dg, "get_settings", lambda: _gate_on(desk_gate_queue_enabled=True)
    )
    monkeypatch.setattr(dj, "load_news", lambda db, ticker, days=7: [])
    monkeypatch.setattr(dj, "load_memories", lambda ticker: [])
    monkeypatch.setattr(dj, "get_settings", lambda: Settings(desk_judgment_enabled=True))
    monkeypatch.setattr(dg, "persist_decision", lambda *a, **k: None)
    intent = DeskIntent(
        account=_account(),
        kind=StrategyKind.mega_rotation,
        ticker="NVDA",
        notional=250.0,
        price=219.0,
        score=100.0,
        metrics={"dip_pct": 6.8},
    )
    v = apply_intent(MagicMock(), intent)
    assert v.allow is True
    assert v.queued is False
    assert v.reason == "judgment_courage"


def test_exit_scandal_sells_before_giveback():
    from app.services.desk_judgment import consider_exit

    j = consider_exit(
        ticker="NVDA",
        entry=219.0,
        price=218.0,
        peak=219.0,
        trigger="none",
        news=[_news(title="NVDA bankruptcy filing after accounting fraud", sentiment="bearish")],
        pnl_pct=-0.5,
    )
    assert j is not None
    assert j.action == "sell"
    assert j.reason == "judgment_cut"


def test_exit_giveback_hold_when_thesis_intact():
    from app.services.desk_judgment import consider_exit

    j = consider_exit(
        ticker="NVDA",
        entry=219.0,
        price=212.0,
        peak=219.0,
        trigger="giveback",
        news=[],
        pnl_pct=-3.2,
    )
    assert j is not None
    assert j.action == "hold"
    assert j.reason == "judgment_hold"


def test_exit_collapsed_bounce_sells():
    from app.services.desk_judgment import consider_exit

    j = consider_exit(
        ticker="NVDA",
        entry=219.0,
        price=200.0,
        peak=219.0,
        trigger="giveback",
        news=[],
        pnl_pct=-8.7,
    )
    assert j is not None
    assert j.action == "sell"
    assert j.reason == "judgment_cut"


def test_exit_target_is_prior_when_thesis_intact():
    from app.services.desk_judgment import consider_exit

    j = consider_exit(
        ticker="AMD",
        entry=5.0,
        price=5.3,
        trigger="target",
        news=[],
        pnl_pct=6.0,
    )
    assert j is not None
    assert j.action == "hold"
    assert j.reason == "judgment_hold"
