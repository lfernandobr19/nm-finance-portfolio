"""T+2 settlement ledger and anti-GFV invariants for USD accounts.

Two complementary protections for a cash account (< US$ 25k, no PDT):

1. **T+2 (buy side)** — sell proceeds are not immediately re-spendable. A sell
   credits ``cash_usd`` but also reserves the amount in ``unsettled_cash_usd``
   with an ``unsettled_until`` date. Buying power is ``cash_usd - unsettled_cash_usd``.
   This prevents a Good Faith Violation (buying with unsettled funds).

2. **Anti-GFV (sell side)** — never sell a position opened on the same US
   session day. Selling before the opening purchase settles is free-riding.
   The hard invariant lives in `positions.close_position`.

The ledger is deliberately conservative: a single ``unsettled_cash_usd`` +
``unsettled_until`` (latest settle date) is used instead of per-trade aging, so
overlapping sells settle together on the latest date. At this account size the
conservatism is harmless and avoids state-explosion.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.domain.models import InvestmentAccount


def settled_usd(account: InvestmentAccount) -> float:
    """Spendable USD cash: total cash minus unsettled sell proceeds."""
    cash = float(getattr(account, "cash_usd", None) or 0)
    unsettled = float(getattr(account, "unsettled_cash_usd", None) or 0)
    return max(0.0, cash - unsettled)


def next_settlement_date(from_date: date, days: int = 2) -> date:
    """Return the settlement date ``days`` US business days after ``from_date``.

    Weekends are skipped; exchange holidays are not modeled (conservative only
    by a half-day at most, irrelevant at this scale).
    """
    d = from_date
    added = 0
    while added < days:
        d += timedelta(days=1)
        if d.weekday() < 5:  # Monday..Friday
            added += 1
    return d


def reserve_proceeds(
    account: InvestmentAccount,
    proceeds: float,
    *,
    days: int = 2,
    today: date | None = None,
) -> None:
    """Record sell proceeds as unsettled until they settle (T+2)."""
    if proceeds <= 0:
        return
    today = today or date.today()
    account.unsettled_cash_usd = round(
        float(getattr(account, "unsettled_cash_usd", None) or 0) + proceeds, 2
    )
    account.unsettled_until = next_settlement_date(today, days)


def settle_due(account: InvestmentAccount, *, today: date | None = None) -> float:
    """Release unsettled cash whose settlement date has passed. Returns amount released."""
    today = today or date.today()
    until = getattr(account, "unsettled_until", None)
    if until is None or today < until:
        return 0.0
    released = float(getattr(account, "unsettled_cash_usd", None) or 0)
    account.unsettled_cash_usd = 0.0
    account.unsettled_until = None
    return released


__all__ = [
    "next_settlement_date",
    "reserve_proceeds",
    "settle_due",
    "settled_usd",
]
