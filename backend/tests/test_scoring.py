from app.domain.models import (
    AccountRule,
    AssetClass,
    CurrencyExposure,
    DividendFrequency,
    MarketSnapshot,
)
from app.services.scoring import score_snapshot


def _rule(**kwargs) -> AccountRule:
    defaults = dict(
        account_id="x",
        version=1,
        is_active=True,
        min_dividend_yield=8.0,
        min_effective_yield=8.0,
        max_p_vp=1.05,
        min_avg_volume=500_000,
        allowed_sectors=[],
        excluded_tickers=[],
        allowed_asset_classes=["fii", "bdr_reit"],
        prefer_monthly_dividends=True,
        score_threshold=70.0,
    )
    defaults.update(kwargs)
    return AccountRule(**defaults)


def _snap(**kwargs) -> MarketSnapshot:
    defaults = dict(
        ticker="HGLG11",
        name="Test",
        sector="logistica",
        price=160,
        dividend_yield=9.0,
        p_vp=0.95,
        avg_volume=2_000_000,
        change_day_pct=0.1,
        change_month_pct=1.0,
        asset_class=AssetClass.fii,
        venue="B3",
        dividend_frequency=DividendFrequency.monthly,
        currency_exposure=CurrencyExposure.BRL,
        withholding_rate=0.0,
        underlying_ticker="",
        raw={},
    )
    defaults.update(kwargs)
    return MarketSnapshot(**defaults)


def test_score_passes_good_fii_monthly():
    result = score_snapshot(_snap(), _rule())
    assert result.passed
    assert result.score >= 70
    assert result.effective_yield == 9.0
    assert all(r["passed"] for r in result.reasons)


def test_score_fails_excluded_ticker():
    result = score_snapshot(_snap(ticker="HGLG11"), _rule(excluded_tickers=["HGLG11"]))
    assert any(r["rule"] == "excluded_tickers" and not r["passed"] for r in result.reasons)


def test_bdr_net_yield_below_minimum_fails():
    # Gross 10% with 30% withholding => 7% net < 8% min
    snap = _snap(
        ticker="R1IN34",
        asset_class=AssetClass.bdr_reit,
        currency_exposure=CurrencyExposure.USD_via_BDR,
        dividend_yield=10.0,
        withholding_rate=0.30,
        p_vp=1.0,
        avg_volume=600_000,
        underlying_ticker="O",
    )
    result = score_snapshot(snap, _rule(min_effective_yield=8.0))
    assert result.effective_yield == 7.0
    assert any(r["rule"] == "min_effective_yield" and not r["passed"] for r in result.reasons)


def test_quarterly_fails_when_prefer_monthly():
    snap = _snap(
        ticker="S2TA34",
        asset_class=AssetClass.bdr_reit,
        dividend_frequency=DividendFrequency.quarterly,
        dividend_yield=12.0,
        withholding_rate=0.30,
        p_vp=0.9,
        avg_volume=600_000,
        currency_exposure=CurrencyExposure.USD_via_BDR,
    )
    result = score_snapshot(snap, _rule(prefer_monthly_dividends=True, min_effective_yield=5.0))
    assert any(r["rule"] == "prefer_monthly_dividends" and not r["passed"] for r in result.reasons)


def test_bdr_monthly_passes_with_enough_net_yield():
    # Gross 12% * 0.7 = 8.4% net
    snap = _snap(
        ticker="L1TC34",
        asset_class=AssetClass.bdr_reit,
        dividend_yield=12.0,
        withholding_rate=0.30,
        p_vp=0.98,
        avg_volume=600_000,
        currency_exposure=CurrencyExposure.USD_via_BDR,
        underlying_ticker="LTC",
    )
    result = score_snapshot(snap, _rule(min_effective_yield=8.0, min_avg_volume=100_000))
    assert result.effective_yield == 8.4
    assert result.passed


def test_fii_fails_us_equity_only_rule():
    snap = _snap(ticker="HGLG11", asset_class=AssetClass.fii)
    result = score_snapshot(snap, _rule(allowed_asset_classes=["us_equity"], score_threshold=50.0))
    assert not result.passed
    assert any(r["rule"] == "allowed_asset_classes" and not r["passed"] for r in result.reasons)
