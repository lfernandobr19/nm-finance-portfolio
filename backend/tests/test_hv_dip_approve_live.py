"""Tests for hv_dip hybrid approve with live quote."""

from __future__ import annotations

from app.domain.models import ExecutionMode, Order, OrderSide, OrderStatus
from app.services.broker.tastytrade_paper import resolve_hv_dip_submit


def test_resolve_hv_dip_notional_path():
    order = Order(
        account_id="a",
        suggestion_id="s",
        ticker="LCID",
        side=OrderSide.buy,
        quantity=0.4,
        amount_brl=5.0,
        limit_price=5.0,
        status=OrderStatus.queued,
        broker="tastytrade",
        execution_mode=ExecutionMode.live,
        execution_payload={},
    )
    limit, qty, mode = resolve_hv_dip_submit(order, live_price=5.2, slippage_pct=0.5)
    assert qty < 1.0
    assert mode == "notional_market"
    assert limit == 5.2


def test_resolve_hv_dip_limit_whole_share():
    order = Order(
        account_id="a",
        suggestion_id="s",
        ticker="SNAP",
        side=OrderSide.buy,
        quantity=3.0,
        amount_brl=30.0,
        limit_price=10.0,
        status=OrderStatus.queued,
        broker="tastytrade",
        execution_mode=ExecutionMode.live,
        execution_payload={},
    )
    limit, qty, mode = resolve_hv_dip_submit(order, live_price=10.0, slippage_pct=0.5)
    assert qty == 3.0
    assert mode == "limit_live"
    assert limit == 10.05


def test_hv_dip_live_price_fallback(monkeypatch):
    from app.config import get_settings
    from app.domain.models import (
        AccountCurrency,
        AssetClass,
        DividendFrequency,
        InvestmentAccount,
        StrategyKind,
        Suggestion,
        SuggestionStatus,
    )
    from app.services.orders import _hv_dip_live_price

    get_settings.cache_clear()

    sug = Suggestion(
        account_id="a",
        ticker="XPEV",
        strategy_kind=StrategyKind.hv_dip,
        asset_class=AssetClass.us_equity,
        dividend_frequency=DividendFrequency.other,
        score=70,
        entry_price=11.5,
        status=SuggestionStatus.pending,
        reasons=[],
        metrics={"price": 11.5},
        price_explanation="",
        rule_version=1,
        proposed_amount_brl=20,
        expires_at=None,
    )

    class FakeClient:
        def fetch_last_prices(self, tickers):
            return {"XPEV": 12.0}

    monkeypatch.setattr("app.services.market_data.MarketDataClient", lambda: FakeClient())
    price, source = _hv_dip_live_price(sug)
    assert price == 12.0
    assert source == "tastytrade_last"
    get_settings.cache_clear()
