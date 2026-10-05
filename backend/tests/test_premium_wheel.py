"""Phase B skeleton: premium wheel (options) gating + OCC symbol + payloads."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.domain.models import (
    AccountCurrency,
    ExecutionMode,
    InvestmentAccount,
)
from app.services.tastytrade_client import occ_option_symbol


def _account(**kw) -> InvestmentAccount:
    defaults = dict(
        id="acc1",
        name="NM USD Live",
        owner_user_id="u1",
        broker_code="tastytrade",
        currency=AccountCurrency.USD,
        execution_mode=ExecutionMode.live,
        cash_usd=2000.0,
        hv_dip_equity_usd=2000.0,
        max_ticket_brl=100.0,
        automation_paused=False,
    )
    defaults.update(kw)
    return InvestmentAccount(**defaults)


def _settings(**kw) -> Settings:
    base = dict(
        premium_enabled=True,
        premium_account_id="",
        premium_min_capital_usd=1000.0,
        premium_tickers="QQQ,SPY",
    )
    base.update(kw)
    return Settings(**base)


# ---- OCC symbol ----------------------------------------------------------

def test_occ_option_symbol_put():
    assert occ_option_symbol("QQQ", date(2026, 9, 18), "P", 480.0) == "QQQ   260918P00480000"


def test_occ_option_symbol_call_and_decimal_strike():
    assert occ_option_symbol("SPY", date(2026, 9, 18), "C", 500.0) == "SPY   260918C00500000"
    assert occ_option_symbol("QQQ", date(2026, 9, 18), "P", 480.5) == "QQQ   260918P00480500"


# ---- wheel eligibility ---------------------------------------------------

def test_wheel_disabled(monkeypatch):
    from app.services.premium.wheel import wheel_eligible

    monkeypatch.setattr(
        "app.services.premium.wheel.get_settings", lambda: _settings(premium_enabled=False)
    )
    ok, reason = wheel_eligible(MagicMock(), _account())
    assert not ok
    assert "premium_enabled" in reason


def test_wheel_blocks_when_options_not_approved(monkeypatch):
    from app.services.premium.wheel import wheel_eligible

    monkeypatch.setattr("app.services.premium.wheel.get_settings", lambda: _settings())
    ok, reason = wheel_eligible(MagicMock(), _account(), options_level=None)
    assert not ok
    assert "opções" in reason


def test_wheel_blocks_when_options_none(monkeypatch):
    from app.services.premium.wheel import wheel_eligible

    monkeypatch.setattr("app.services.premium.wheel.get_settings", lambda: _settings())
    ok, _ = wheel_eligible(MagicMock(), _account(), options_level="None")
    assert not ok


def test_wheel_blocks_when_below_min_capital(monkeypatch):
    from app.services.premium.wheel import wheel_eligible

    monkeypatch.setattr("app.services.premium.wheel.get_settings", lambda: _settings())
    ok, reason = wheel_eligible(MagicMock(), _account(cash_usd=500.0), options_level="No Restrictions")
    assert not ok
    assert "capital" in reason


def test_wheel_blocks_when_not_live(monkeypatch):
    from app.services.premium.wheel import wheel_eligible

    monkeypatch.setattr("app.services.premium.wheel.get_settings", lambda: _settings())
    ok, reason = wheel_eligible(
        MagicMock(),
        _account(execution_mode=ExecutionMode.paper),
        options_level="No Restrictions",
    )
    assert not ok
    assert "live" in reason


def test_wheel_blocks_on_kill_switch(monkeypatch):
    from app.services.premium.wheel import wheel_eligible

    monkeypatch.setattr("app.services.premium.wheel.get_settings", lambda: _settings())
    ok, reason = wheel_eligible(
        MagicMock(),
        _account(automation_paused=True),
        options_level="No Restrictions",
    )
    assert not ok
    assert "kill switch" in reason


def test_wheel_eligible_when_all_ok(monkeypatch):
    from app.services.premium.wheel import wheel_eligible

    monkeypatch.setattr("app.services.premium.wheel.get_settings", lambda: _settings())
    ok, reason = wheel_eligible(MagicMock(), _account(), options_level="No Restrictions")
    assert ok
    assert reason == "ok"


# ---- cycle gating --------------------------------------------------------

def test_cycle_returns_zero_when_disabled(monkeypatch):
    from app.services.premium.wheel import run_premium_wheel_cycle

    monkeypatch.setattr(
        "app.services.premium.wheel.get_settings", lambda: _settings(premium_enabled=False)
    )
    assert run_premium_wheel_cycle(MagicMock()) == 0


def test_cycle_returns_zero_when_not_eligible(monkeypatch):
    from app.services.premium.wheel import run_premium_wheel_cycle

    monkeypatch.setattr("app.services.premium.wheel.get_settings", lambda: _settings())
    monkeypatch.setattr(
        "app.services.premium.wheel._resolve_account", lambda db: _account()
    )
    monkeypatch.setattr(
        "app.services.tastytrade_client.TastytradeClient",
        MagicMock(configured=lambda self: True, fetch_options_level=lambda self: None),
    )
    assert run_premium_wheel_cycle(MagicMock()) == 0


# ---- option order payload -------------------------------------------------

def test_submit_cash_secured_put_payload():
    from app.services.tastytrade_client import TastytradeClient

    client = TastytradeClient(live=False)
    captured: dict = {}
    client._post_order = lambda body: captured.update(body) or body  # type: ignore[method-assign]

    client.submit_cash_secured_put(
        option_symbol="QQQ   260918P00480000", quantity=1, limit_price=0.85
    )
    assert captured["order-type"] == "Limit"
    assert captured["price"] == 0.85
    assert captured["price-effect"] == "Credit"
    leg = captured["legs"][0]
    assert leg["instrument-type"] == "Equity Option"
    assert leg["action"] == "Sell to Open"
    assert leg["quantity"] == 1
    assert leg["symbol"] == "QQQ   260918P00480000"


def test_submit_covered_call_market_payload():
    from app.services.tastytrade_client import TastytradeClient

    client = TastytradeClient(live=False)
    captured: dict = {}
    client._post_order = lambda body: captured.update(body) or body  # type: ignore[method-assign]

    client.submit_covered_call(option_symbol="SPY   260918C00500000", quantity=1)
    assert captured["order-type"] == "Market"
    assert "price" not in captured
    assert captured["legs"][0]["action"] == "Sell to Open"
