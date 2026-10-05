from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_membership
from app.db import get_db
from app.domain.models import AccountMembership, InvestmentAccount
from app.services.market_data import MarketDataClient
from app.services.brapi_client import BrapiClient
from sqlalchemy.orm import Session

router = APIRouter(tags=["market"])


@router.get("/accounts/{account_id}/tickers/{ticker}/bars")
def ticker_bars(
    account_id: str,
    ticker: str,
    _: AccountMembership = Depends(get_membership),
    db: Session = Depends(get_db),
) -> list[dict]:
    account = db.get(InvestmentAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    currency = str(getattr(account, "currency", "BRL") or "BRL").upper()
    broker = (account.broker_code or "").lower()
    use_us = currency.endswith("USD")
    if use_us:
        bars = MarketDataClient().fetch_daily_bars(ticker)
    else:
        bars = BrapiClient().fetch_daily_bars(ticker)
    return [
        {
            "date": b.date.isoformat(),
            "open": round(b.open, 2),
            "high": round(b.high, 2),
            "low": round(b.low, 2),
            "close": round(b.close, 2),
            "volume": round(b.volume, 0),
        }
        for b in bars
    ]
