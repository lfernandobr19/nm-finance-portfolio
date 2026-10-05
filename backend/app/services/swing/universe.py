"""Fixed ~30-ticker Swing Desk universe (B3 BDRs tech + IVVB11 + liquid non-tech)."""

from __future__ import annotations

# Agent-curated liquid list for MVP. Revisit monthly offline; not auto-rotated in-app.
SWING_UNIVERSE: list[str] = [
    # Tech BDRs
    "AAPL34",
    "MSFT34",
    "GOGL34",
    "AMZO34",
    "NVDC34",
    "M1TA34",
    "TSLA34",
    "NFLX34",
    "ITLC34",
    "QCOM34",
    "AVGO34",
    "A1MD34",
    "SSFO34",
    "ORCL34",
    "CSCO34",
    # US equity ETF B3
    "IVVB11",
    # Liquid non-tech / mixed
    "PETR4",
    "VALE3",
    "ITUB4",
    "BBDC4",
    "BBAS3",
    "WEGE3",
    "ABEV3",
    "B3SA3",
    "RENT3",
    "PRIO3",
    "SUZB3",
    "JBSS3",
    "RADL3",
    "EQTL3",
]


def swing_tickers() -> list[str]:
    return list(SWING_UNIVERSE)
