"""Market data ingestion. Stub SAMPLE_ASSETS (FII + BDR REIT) when MARKET_PROVIDER_URL is empty."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.models import (
    AssetClass,
    CurrencyExposure,
    DividendFrequency,
    MarketSnapshot,
)

settings = get_settings()

SAMPLE_ASSETS: list[dict[str, Any]] = [
    {
        "ticker": "HGLG11",
        "name": "CSHG Logística",
        "sector": "logistica",
        "price": 162.40,
        "dividend_yield": 9.1,
        "p_vp": 0.97,
        "avg_volume": 2_100_000,
        "change_day_pct": 0.35,
        "change_month_pct": 1.8,
        "asset_class": "fii",
        "dividend_frequency": "monthly",
        "currency_exposure": "BRL",
        "withholding_rate": 0.0,
        "underlying_ticker": "",
    },
    {
        "ticker": "XPML11",
        "name": "XP Malls",
        "sector": "shopping",
        "price": 98.20,
        "dividend_yield": 10.2,
        "p_vp": 0.92,
        "avg_volume": 3_400_000,
        "change_day_pct": -0.12,
        "change_month_pct": 2.4,
        "asset_class": "fii",
        "dividend_frequency": "monthly",
        "currency_exposure": "BRL",
        "withholding_rate": 0.0,
        "underlying_ticker": "",
    },
    {
        "ticker": "MXRF11",
        "name": "Maxi Renda",
        "sector": "papel",
        "price": 10.05,
        "dividend_yield": 12.5,
        "p_vp": 1.01,
        "avg_volume": 8_000_000,
        "change_day_pct": 0.05,
        "change_month_pct": 0.9,
        "asset_class": "fii",
        "dividend_frequency": "monthly",
        "currency_exposure": "BRL",
        "withholding_rate": 0.0,
        "underlying_ticker": "",
    },
    {
        "ticker": "KNRI11",
        "name": "Kinea Renda Imobiliária",
        "sector": "hibrido",
        "price": 145.10,
        "dividend_yield": 7.2,
        "p_vp": 0.88,
        "avg_volume": 1_500_000,
        "change_day_pct": 0.20,
        "change_month_pct": -0.5,
        "asset_class": "fii",
        "dividend_frequency": "monthly",
        "currency_exposure": "BRL",
        "withholding_rate": 0.0,
        "underlying_ticker": "",
    },
    {
        "ticker": "VISC11",
        "name": "Vinci Shopping Centers",
        "sector": "shopping",
        "price": 112.30,
        "dividend_yield": 8.6,
        "p_vp": 0.95,
        "avg_volume": 2_800_000,
        "change_day_pct": 0.55,
        "change_month_pct": 3.1,
        "asset_class": "fii",
        "dividend_frequency": "monthly",
        "currency_exposure": "BRL",
        "withholding_rate": 0.0,
        "underlying_ticker": "",
    },
    # BDR REIT stubs (tickers ilustrativos *34 — documentados no README)
    {
        "ticker": "R1IN34",
        "name": "Realty Income BDR",
        "sector": "net_lease",
        "price": 48.50,
        "dividend_yield": 12.0,
        "p_vp": 1.12,
        "avg_volume": 520_000,
        "change_day_pct": 0.15,
        "change_month_pct": 1.2,
        "asset_class": "bdr_reit",
        "dividend_frequency": "monthly",
        "currency_exposure": "USD_via_BDR",
        "withholding_rate": settings.bdr_withholding_rate,
        "underlying_ticker": "O",
    },
    {
        "ticker": "L1TC34",
        "name": "LTC Properties BDR",
        "sector": "healthcare",
        "price": 32.10,
        "dividend_yield": 12.5,
        "p_vp": 0.98,
        "avg_volume": 280_000,
        "change_day_pct": -0.40,
        "change_month_pct": 0.5,
        "asset_class": "bdr_reit",
        "dividend_frequency": "monthly",
        "currency_exposure": "USD_via_BDR",
        "withholding_rate": settings.bdr_withholding_rate,
        "underlying_ticker": "LTC",
    },
    {
        "ticker": "A1DC34",
        "name": "Agree Realty BDR",
        "sector": "net_lease",
        "price": 55.20,
        "dividend_yield": 4.3,
        "p_vp": 1.05,
        "avg_volume": 95_000,
        "change_day_pct": 0.22,
        "change_month_pct": -0.8,
        "asset_class": "bdr_reit",
        "dividend_frequency": "monthly",
        "currency_exposure": "USD_via_BDR",
        "withholding_rate": settings.bdr_withholding_rate,
        "underlying_ticker": "ADC",
    },
    {
        # Quarterly REIT BDR — fails prefer_monthly by default
        "ticker": "S2TA34",
        "name": "STAG Industrial BDR",
        "sector": "industrial",
        "price": 28.90,
        "dividend_yield": 11.0,
        "p_vp": 0.94,
        "avg_volume": 150_000,
        "change_day_pct": 0.10,
        "change_month_pct": 2.0,
        "asset_class": "bdr_reit",
        "dividend_frequency": "quarterly",
        "currency_exposure": "USD_via_BDR",
        "withholding_rate": settings.bdr_withholding_rate,
        "underlying_ticker": "STAG",
    },
]


def _parse_asset_class(value: str) -> AssetClass:
    try:
        return AssetClass(value)
    except ValueError:
        return AssetClass.fii


def _parse_frequency(value: str) -> DividendFrequency:
    try:
        return DividendFrequency(value)
    except ValueError:
        return DividendFrequency.other


def _parse_exposure(value: str) -> CurrencyExposure:
    try:
        return CurrencyExposure(value)
    except ValueError:
        return CurrencyExposure.BRL


def _fetch_remote() -> list[dict[str, Any]]:
    if not settings.market_provider_url:
        return SAMPLE_ASSETS
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(settings.market_provider_url)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        return data.get("items", SAMPLE_ASSETS)


def ingest_market(db: Session) -> list[MarketSnapshot]:
    now = datetime.now(timezone.utc)
    created: list[MarketSnapshot] = []
    for item in _fetch_remote():
        asset_class = _parse_asset_class(str(item.get("asset_class", "fii")))
        default_w = settings.bdr_withholding_rate if asset_class == AssetClass.bdr_reit else 0.0
        snap = MarketSnapshot(
            ticker=str(item["ticker"]).upper(),
            name=item.get("name", ""),
            sector=item.get("sector", ""),
            price=float(item["price"]),
            dividend_yield=float(item.get("dividend_yield", 0)),
            p_vp=float(item.get("p_vp", 0)),
            avg_volume=float(item.get("avg_volume", 0)),
            change_day_pct=float(item.get("change_day_pct", 0)),
            change_month_pct=float(item.get("change_month_pct", 0)),
            asset_class=asset_class,
            venue=str(item.get("venue", "B3")),
            dividend_frequency=_parse_frequency(str(item.get("dividend_frequency", "monthly"))),
            currency_exposure=_parse_exposure(str(item.get("currency_exposure", "BRL"))),
            withholding_rate=float(item.get("withholding_rate", default_w)),
            underlying_ticker=str(item.get("underlying_ticker", "")),
            as_of=now,
            raw=item,
        )
        db.add(snap)
        created.append(snap)
    db.commit()
    for s in created:
        db.refresh(s)
    return created
