"""Single source of truth for hv_dip sizing and guardrail bases.

The floor/cap basis used to be recomputed at four call sites as
``max(cash, hv_dip_equity_usd)``. That pinned the basis to a stale reference
(the 100 USD column default) whenever real cash fell below it, so a 20% cash
floor could hold back 71% of the actual cash and the per-ticker cap could land
above the whole account balance — making the concentration guard inert.

The basis here is real desk equity: cash plus what is currently deployed in
open hv_dip positions. Cash alone would not work, because the per-ticker cap
would shrink as capital is deployed and block every scale-in tranche.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.domain.models import (
    InvestmentAccount,
    Position,
    PositionStatus,
    StrategyKind,
)
from app.services.hv_dip.settlement import settled_usd

# Fallbacks live here only. They mirror the ORM column defaults in
# `domain/models.py`; call sites must not invent their own.
DEFAULT_CASH_FLOOR_PCT = 20.0
DEFAULT_MAX_TICKER_PCT = 80.0


def usd_cash(account: InvestmentAccount) -> float:
    """Spendable USD cash, falling back to the equity column when cash is unset."""
    cash = float(getattr(account, "cash_usd", None) or 0)
    equity = float(getattr(account, "hv_dip_equity_usd", None) or 0)
    return cash if cash > 0 else equity


def _open_hv_dip_positions(db: Session, account_id: str, ticker: str | None = None):
    query = db.query(Position).filter(
        Position.account_id == account_id,
        Position.strategy_kind == StrategyKind.hv_dip,
        Position.status == PositionStatus.open,
    )
    if ticker is not None:
        query = query.filter(Position.ticker == ticker)
    return query.all()


def invested_usd(db: Session, account_id: str) -> float:
    """Cost basis currently deployed across all open hv_dip positions."""
    rows = _open_hv_dip_positions(db, account_id)
    return float(sum(float(p.entry_price) * float(p.quantity) for p in rows))


def deployed_on_ticker_usd(db: Session, account_id: str, ticker: str) -> float:
    """Cost basis deployed on one ticker (per-ticker concentration numerator)."""
    rows = _open_hv_dip_positions(db, account_id, ticker)
    return float(sum(float(p.entry_price) * float(p.quantity) for p in rows))


@dataclass(frozen=True)
class SizingBasis:
    """Resolved sizing envelope for one account at one point in time.

    ``cash`` is gross cash (used for equity/floor accounting); ``settled`` is
    T+2-aware spendable cash. ``deployable`` is the amount above the cash floor
    that can actually be spent today (settled cash only).
    """

    cash: float
    settled: float
    equity: float
    floor_pct: float
    floor_cash: float
    deployable: float
    max_ticker_pct: float
    ticker_cap: float

    def spendable(self, letter: str | None) -> float:
        """Score A may dip into the cash floor (setup imperdível); B and C may not.

        Both are bounded by settled cash — unsettled (T+2) proceeds are never
        spendable, even for an A setup.
        """
        return self.settled if (letter or "").upper() == "A" else self.deployable


def sizing_basis(
    account: InvestmentAccount,
    *,
    invested_usd: float = 0.0,
) -> SizingBasis:
    """Build the sizing envelope from real cash plus real deployed capital."""
    cash = usd_cash(account)
    settled = settled_usd(account)
    equity = cash + max(0.0, float(invested_usd))
    floor_pct = float(
        getattr(account, "hv_dip_cash_floor_pct", DEFAULT_CASH_FLOOR_PCT)
        or DEFAULT_CASH_FLOOR_PCT
    )
    max_ticker_pct = float(
        getattr(account, "hv_dip_max_ticker_pct", DEFAULT_MAX_TICKER_PCT)
        or DEFAULT_MAX_TICKER_PCT
    )
    floor_cash = equity * (floor_pct / 100.0)
    return SizingBasis(
        cash=cash,
        settled=settled,
        equity=equity,
        floor_pct=floor_pct,
        floor_cash=floor_cash,
        deployable=max(0.0, settled - floor_cash),
        max_ticker_pct=max_ticker_pct,
        ticker_cap=equity * (max_ticker_pct / 100.0),
    )


def account_sizing_basis(db: Session, account: InvestmentAccount) -> SizingBasis:
    """`sizing_basis` with the deployed capital resolved from the database."""
    return sizing_basis(account, invested_usd=invested_usd(db, account.id))


__all__ = [
    "DEFAULT_CASH_FLOOR_PCT",
    "DEFAULT_MAX_TICKER_PCT",
    "SizingBasis",
    "account_sizing_basis",
    "deployed_on_ticker_usd",
    "invested_usd",
    "sizing_basis",
    "usd_cash",
]
