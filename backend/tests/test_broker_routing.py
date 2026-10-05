"""Regression: broker routing by broker_code + execution_mode."""

from __future__ import annotations

from app.domain.models import AccountCurrency, ExecutionMode, InvestmentAccount
from app.services.broker import get_broker_adapter


def _account(**kw) -> InvestmentAccount:
    defaults = dict(
        id="a1",
        name="NM",
        broker_code="tastytrade",
        currency=AccountCurrency.USD,
        cash_usd=100.0,
        execution_mode=ExecutionMode.paper,
    )
    defaults.update(kw)
    return InvestmentAccount(**defaults)


def test_tastytrade_live_account_uses_tastytrade_adapter_live():
    from app.services.broker.tastytrade_paper import TastytradeBrokerAdapter

    adapter = get_broker_adapter(
        _account(broker_code="tastytrade", execution_mode=ExecutionMode.live)
    )
    assert isinstance(adapter, TastytradeBrokerAdapter)
    assert adapter.live is True


def test_tastytrade_paper_account_uses_tastytrade_adapter_sandbox():
    from app.services.broker.tastytrade_paper import TastytradeBrokerAdapter

    adapter = get_broker_adapter(
        _account(broker_code="tastytrade", execution_mode=ExecutionMode.paper)
    )
    assert isinstance(adapter, TastytradeBrokerAdapter)
    assert adapter.live is False


def test_inter_live_account_uses_manual_adapter():
    from app.services.broker.inter_manual import InterManualBrokerAdapter

    adapter = get_broker_adapter(
        _account(broker_code="inter", execution_mode=ExecutionMode.live)
    )
    assert isinstance(adapter, InterManualBrokerAdapter)


def test_inter_paper_account_uses_simulated_adapter():
    from app.services.broker.simulated import SimulatedBrokerAdapter

    adapter = get_broker_adapter(
        _account(broker_code="inter", execution_mode=ExecutionMode.paper)
    )
    assert isinstance(adapter, SimulatedBrokerAdapter)
