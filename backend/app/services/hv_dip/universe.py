"""Curated liquid US high-vol universe for NM High-Vol Dip."""

from __future__ import annotations

import logging
import re

import httpx

from app.config import get_settings

logger = logging.getLogger("fiidesk.hv_dip.universe")

# Core seed: mega-caps (news catalyst targets) + high-vol liquid names.
# Always scanned and offline-safe.
HV_DIP_UNIVERSE: list[str] = [
    # Mega caps — news catalyst targets (Amazon/NVIDIA case)
    "AMZN",
    "AAPL",
    "MSFT",
    "GOOGL",
    "META",
    "NVDA",
    "TSLA",
    "AMD",
    "NFLX",
    "AVGO",
    # High-vol / momentum names
    "COIN",
    "MSTR",
    "MARA",
    "RIOT",
    "PLTR",
    "SOFI",
    "RIVN",
    "NIO",
    "UBER",
    "SHOP",
    "XYZ",
    "HOOD",
    "AFRM",
    "UPST",
    "SNAP",
    "ROKU",
    "DKNG",
    "ABNB",
    "SNOW",
    "CRWD",
    "NET",
    "DDOG",
    "MDB",
    "PATH",
    "U",
    "RBLX",
    "TTD",
    "ENPH",
    "SEDG",
    "LCID",
    "F",
    "GM",
    "BA",
    "XPEV",
    "CVNA",
    "GME",
    "AMC",
    # Additional liquid large caps
    "CRM",
    "ORCL",
    "ADBE",
    "INTC",
    "QCOM",
    "MU",
    "PFE",
    "JPM",
    "V",
    "MA",
    "DIS",
    "PYPL",
    "SQ",
    "ZM",
    "DOCU",
]

_SYMBOL_RE = re.compile(r"^[A-Z]{1,5}$")


def hv_dip_tickers() -> list[str]:
    return list(HV_DIP_UNIVERSE)


def fetch_finnhub_universe(max_symbols: int = 500) -> list[str]:
    """Fetch US common stocks from Finnhub and merge with the curated seed.

    Liquidity (dollar-volume) filtering is applied downstream via snapshots when
    market data is available; this returns a bounded candidate list merged with
    the seed so the offline path keeps working.
    """
    settings = get_settings()
    if not settings.finnhub_api_key:
        return hv_dip_tickers()
    url = f"{settings.finnhub_base_url.rstrip('/')}/stock/symbol"
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(
                url,
                params={"exchange": "US", "token": settings.finnhub_api_key},
            )
            if resp.status_code >= 400:
                logger.warning("Finnhub symbols HTTP %s", resp.status_code)
                return hv_dip_tickers()
            data = resp.json()
    except httpx.HTTPError:
        logger.exception("Finnhub symbols failed")
        return hv_dip_tickers()

    symbols = [
        str(row.get("symbol", "")).upper()
        for row in data
        if row.get("type") == "Common Stock"
        and _SYMBOL_RE.match(str(row.get("symbol", "")).upper())
    ]
    merged = list(dict.fromkeys([*HV_DIP_UNIVERSE, *symbols[:max_symbols]]))
    logger.info("Finnhub universe: %d symbols (seed %d)", len(merged), len(HV_DIP_UNIVERSE))
    return merged
