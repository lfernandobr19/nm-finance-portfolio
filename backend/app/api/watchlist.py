"""User watchlist (observação): follow tickers and see their price at market open.

Read is enriched with live quotes; add/remove are role-protected mutations.
Synced across Windows and Android (single source of truth in the DB).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_membership, require_roles
from app.db import get_db
from app.domain.models import (
    AccountMembership,
    InvestmentAccount,
    MembershipRole,
    WatchlistItem,
)
from app.schemas import WatchlistAddIn, WatchlistItemOut
from app.services.market_data import MarketDataClient
from app.services.brapi_client import BrapiClient

router = APIRouter(tags=["watchlist"])


def _is_us(account: InvestmentAccount | None) -> bool:
    if account is None:
        return False
    currency = str(getattr(account, "currency", "BRL") or "BRL").upper()
    broker = (account.broker_code or "").lower()
    return currency.endswith("USD") or broker == "tastytrade"


def _prev_close(account: InvestmentAccount | None, ticker: str) -> float | None:
    """Last daily close before today (fallback: any last close) for variation."""
    try:
        if _is_us(account):
            bars = MarketDataClient().fetch_daily_bars(ticker)
        else:
            bars = BrapiClient().fetch_daily_bars(ticker)
    except Exception:
        return None
    if not bars:
        return None
    if len(bars) >= 2:
        return float(bars[-2].close)
    return float(bars[-1].close)


@router.get(
    "/accounts/{account_id}/watchlist",
    response_model=list[WatchlistItemOut],
)
def list_watchlist(
    account_id: str,
    _: AccountMembership = Depends(get_membership),
    db: Session = Depends(get_db),
) -> list[WatchlistItemOut]:
    account = db.get(InvestmentAccount, account_id)
    items = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.account_id == account_id)
        .order_by(WatchlistItem.created_at.desc())
        .all()
    )
    if not items:
        return []

    tickers = [i.ticker for i in items]
    md = MarketDataClient() if _is_us(account) else None
    brapi = None if md else BrapiClient()
    if md:
        prices = md.fetch_last_prices(tickers)
        currency = "USD"
    else:
        prices = brapi.fetch_last_prices(tickers)
        currency = "BRL"
    out: list[WatchlistItemOut] = []
    for item in items:
        price = prices.get(item.ticker.upper()) or prices.get(item.ticker)
        try:
            bars = md.fetch_daily_bars(item.ticker) if md else brapi.fetch_daily_bars(item.ticker)
        except Exception:
            bars = None
        prev = None
        if bars:
            prev = float(bars[-2].close) if len(bars) >= 2 else float(bars[-1].close)
        change_pct = None
        if price is not None and prev:
            change_pct = round((price - prev) / prev * 100.0, 4)
        out.append(
            WatchlistItemOut(
                id=item.id,
                account_id=item.account_id,
                ticker=item.ticker,
                note=item.note,
                created_at=item.created_at,
                price=round(float(price), 4) if price is not None else None,
                prev_close=round(float(prev), 4) if prev is not None else None,
                change_pct=change_pct,
                currency=currency,
            )
        )
    return out


@router.post(
    "/accounts/{account_id}/watchlist",
    response_model=WatchlistItemOut,
    status_code=201,
)
def add_watchlist(
    account_id: str,
    body: WatchlistAddIn,
    membership: AccountMembership = Depends(
        require_roles(MembershipRole.owner, MembershipRole.operator)
    ),
    db: Session = Depends(get_db),
) -> WatchlistItemOut:
    ticker = body.ticker.strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="Ticker is required")
    existing = (
        db.query(WatchlistItem)
        .filter(
            WatchlistItem.account_id == account_id,
            WatchlistItem.ticker == ticker,
        )
        .one_or_none()
    )
    if existing:
        return WatchlistItemOut(
            id=existing.id,
            account_id=existing.account_id,
            ticker=existing.ticker,
            note=existing.note,
            created_at=existing.created_at,
            currency="USD" if _is_us(db.get(InvestmentAccount, account_id)) else "BRL",
        )

    item = WatchlistItem(
        account_id=account_id,
        ticker=ticker,
        added_by_user_id=membership.user_id,
        note=(body.note or "").strip() or None,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return WatchlistItemOut(
        id=item.id,
        account_id=item.account_id,
        ticker=item.ticker,
        note=item.note,
        created_at=item.created_at,
        currency="USD" if _is_us(db.get(InvestmentAccount, account_id)) else "BRL",
    )


@router.delete("/accounts/{account_id}/watchlist/{ticker}", status_code=204)
def remove_watchlist(
    account_id: str,
    ticker: str,
    _: AccountMembership = Depends(
        require_roles(MembershipRole.owner, MembershipRole.operator)
    ),
    db: Session = Depends(get_db),
) -> None:
    item = (
        db.query(WatchlistItem)
        .filter(
            WatchlistItem.account_id == account_id,
            WatchlistItem.ticker == ticker.upper(),
        )
        .one_or_none()
    )
    if item:
        db.delete(item)
        db.commit()
