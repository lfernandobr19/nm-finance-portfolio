"""Index Core: autonomous index DCA (paper-first).

Converts the only path with documented positive expectancy at < US$ 500 capital
— buying and holding the index — into an autonomous accumulation bot:

- Resolves the USD tastytrade account (explicit id or auto-pick).
- Honors the kill switch (`automation_paused`).
- Optional regime guard: skips the contribution when QQQ is below its SMA200.
- Buys a fixed dollar amount (notional) of each configured index ticker,
  fractional, so a $50 contribution works regardless of the ETF price.

The order flows through the normal broker adapter path (`qty < 1.0` routes to
`submit_equity_notional_market_buy`), and a fill opens a tracked position so the
Dashboard shows the growing index core like any other holding.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.models import (
    AccountCurrency,
    InvestmentAccount,
    StrategyKind,
)

logger = logging.getLogger("fiidesk.index_core")

_SMA_PERIOD = 200


def _resolve_account(db: Session) -> InvestmentAccount | None:
    """Return the target USD tastytrade account, or None when none exists."""
    settings = get_settings()
    if (settings.index_core_account_id or "").strip():
        return db.get(InvestmentAccount, settings.index_core_account_id.strip())
    return (
        db.query(InvestmentAccount)
        .filter(
            InvestmentAccount.currency == AccountCurrency.USD,
            InvestmentAccount.broker_code == "tastytrade",
        )
        .order_by(InvestmentAccount.created_at.asc())
        .first()
    )


def _last_close(ticker: str) -> float | None:
    """Latest daily close for a ticker (Yahoo history)."""
    from app.services.market_data import MarketDataClient

    try:
        bars = MarketDataClient().fetch_daily_bars(ticker)
    except Exception:  # noqa: BLE001
        logger.exception("index_core bars failed for %s", ticker)
        return None
    if not bars:
        return None
    return float(bars[-1].close)


def _regime_allows(ticker: str) -> bool:
    """True when the index is at/above its SMA200 (or when data is unavailable).

    A failed regime read must not silently block DCA — log and proceed.
    """
    from app.services.market_data import MarketDataClient
    from app.services.swing.indicators import sma

    try:
        bars = MarketDataClient().fetch_daily_bars(ticker)
    except Exception:  # noqa: BLE001
        logger.exception("index_core regime bars failed for %s", ticker)
        return True
    if len(bars) < _SMA_PERIOD:
        logger.info("index_core regime: insufficient history for %s (%d bars)", ticker, len(bars))
        return True
    closes = [float(b.close) for b in bars]
    avg = sma(closes, _SMA_PERIOD)
    if avg is None or avg <= 0:
        return True
    return closes[-1] >= avg


def run_index_core_cycle(db: Session) -> int:
    """Execute due index-core contributions. Returns the number of orders placed."""
    settings = get_settings()
    if not settings.index_core_enabled:
        return 0

    account = _resolve_account(db)
    if account is None:
        logger.info("index_core: no USD tastytrade account found — skip")
        return 0

    if bool(getattr(account, "automation_paused", False)):
        logger.info("index_core: kill switch active for %s — skip", account.name)
        return 0

    tickers = [t.strip().upper() for t in (settings.index_core_tickers or "").split(",") if t.strip()]
    if not tickers:
        return 0

    weekly = float(settings.index_core_weekly_usd or 0)
    if weekly <= 0:
        return 0

    from app.services.desk_gate import DeskIntent, propose_or_place, remaining_slice_usd

    remaining = remaining_slice_usd(db, account, StrategyKind.index_core)
    notional = min(weekly, remaining)
    if notional <= 0:
        logger.info("index_core: slice full — skip")
        return 0

    placed = 0
    for ticker in tickers:
        price = _last_close(ticker)
        if price is None or price <= 0:
            logger.warning("index_core: no price for %s — skip", ticker)
            continue

        if settings.index_core_regime_guard and not _regime_allows(ticker):
            logger.info("index_core: regime guard blocks %s (below SMA%d)", ticker, _SMA_PERIOD)
            continue

        placed += propose_or_place(
            db,
            DeskIntent(
                account=account,
                kind=StrategyKind.index_core,
                ticker=ticker,
                notional=notional,
                price=float(price),
                score=50.0,
                explanation="Index Core: DCA autonomo de indice (notional buy)",
                metrics={"index_core": True, "notional_usd": round(notional, 2)},
            ),
        )

    return placed


__all__ = ["run_index_core_cycle"]
