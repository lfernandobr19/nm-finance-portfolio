from fastapi import APIRouter

from app.api import (
    accounts,
    auth,
    day_trade,
    hv_dip,
    intelligence,
    market,
    news,
    orders,
    portfolio,
    suggestions,
    watchlist,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(accounts.router)
api_router.include_router(suggestions.router)
api_router.include_router(orders.router)
api_router.include_router(news.router)
api_router.include_router(market.router)
api_router.include_router(day_trade.router)
api_router.include_router(hv_dip.router)
api_router.include_router(intelligence.router)
api_router.include_router(portfolio.router)
api_router.include_router(watchlist.router)
