from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_membership, require_roles
from app.config import get_settings
from app.db import get_db
from app.domain.models import AccountMembership, DayTradeSignal, InvestmentAccount, MembershipRole
from app.schemas import (
    DayTradeAnalyticsOut,
    DayTradeConfigHistoryOut,
    DayTradeConfigOut,
    DayTradeConfigSetIn,
    DayTradeRegimeOut,
    DayTradeSignalOut,
    DayTradeStateOut,
    IntradayBarOut,
)
from app.services.day_trade import analytics as dt_analytics
from app.services.day_trade import configs as dt_configs
from app.services.day_trade.cache import DayTradeBarCache
from app.services.day_trade.regime import classify_regime

router = APIRouter(tags=["day-trade"])


def _require_us_account(account: InvestmentAccount | None) -> InvestmentAccount:
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    currency = str(getattr(account, "currency", "BRL") or "BRL").upper()
    broker = (account.broker_code or "").lower()
    if not (currency.endswith("USD") or broker == "tastytrade"):
        raise HTTPException(status_code=400, detail="Day trade study is US accounts only")
    return account


@router.get(
    "/accounts/{account_id}/day-trade/signals",
    response_model=list[DayTradeSignalOut],
)
def list_day_trade_signals(
    account_id: str,
    session_day: date | None = Query(default=None, alias="date"),
    _: AccountMembership = Depends(get_membership),
    db: Session = Depends(get_db),
) -> list[DayTradeSignal]:
    settings = get_settings()
    if not settings.day_trade_enabled:
        raise HTTPException(status_code=503, detail="Day trade study disabled")
    account = _require_us_account(db.get(InvestmentAccount, account_id))
    q = db.query(DayTradeSignal).filter(DayTradeSignal.account_id == account.id)
    if session_day:
        q = q.filter(DayTradeSignal.session_date == session_day)
    return q.order_by(DayTradeSignal.created_at.desc()).limit(200).all()


@router.get(
    "/accounts/{account_id}/day-trade/signals/{signal_id}",
    response_model=DayTradeSignalOut,
)
def get_day_trade_signal(
    account_id: str,
    signal_id: str,
    _: AccountMembership = Depends(get_membership),
    db: Session = Depends(get_db),
) -> DayTradeSignal:
    settings = get_settings()
    if not settings.day_trade_enabled:
        raise HTTPException(status_code=503, detail="Day trade study disabled")
    _require_us_account(db.get(InvestmentAccount, account_id))
    row = (
        db.query(DayTradeSignal)
        .filter(DayTradeSignal.id == signal_id, DayTradeSignal.account_id == account_id)
        .one_or_none()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Signal not found")
    return row


@router.get(
    "/accounts/{account_id}/tickers/{ticker}/bars/intraday",
    response_model=list[IntradayBarOut],
)
def intraday_bars(
    account_id: str,
    ticker: str,
    timeframe: str = Query(default="5m"),
    _: AccountMembership = Depends(get_membership),
    db: Session = Depends(get_db),
) -> list[IntradayBarOut]:
    settings = get_settings()
    if not settings.day_trade_enabled:
        raise HTTPException(status_code=503, detail="Day trade study disabled")
    _require_us_account(db.get(InvestmentAccount, account_id))
    if timeframe != settings.day_trade_candle_period:
        raise HTTPException(status_code=400, detail=f"Only {settings.day_trade_candle_period} supported")
    bars = DayTradeBarCache().get_bars(ticker)
    return [
        IntradayBarOut(
            ts=b.ts.isoformat(),
            open=round(b.open, 4),
            high=round(b.high, 4),
            low=round(b.low, 4),
            close=round(b.close, 4),
            volume=round(b.volume, 0),
        )
        for b in bars
    ]


@router.get(
    "/accounts/{account_id}/day-trade/analytics",
    response_model=DayTradeAnalyticsOut,
)
def day_trade_analytics(
    account_id: str,
    _: AccountMembership = Depends(get_membership),
    db: Session = Depends(get_db),
) -> dict:
    settings = get_settings()
    if not settings.day_trade_enabled:
        raise HTTPException(status_code=503, detail="Day trade study disabled")
    _require_us_account(db.get(InvestmentAccount, account_id))
    return dt_analytics.analytics_summary(db, account_id)


@router.get(
    "/accounts/{account_id}/day-trade/config",
    response_model=DayTradeConfigOut,
)
def day_trade_config(
    account_id: str,
    _: AccountMembership = Depends(get_membership),
    db: Session = Depends(get_db),
) -> DayTradeConfigOut:
    settings = get_settings()
    if not settings.day_trade_enabled:
        raise HTTPException(status_code=503, detail="Day trade study disabled")
    _require_us_account(db.get(InvestmentAccount, account_id))
    cfg = dt_configs.ensure_default_config(db)
    db.commit()
    return DayTradeConfigOut(
        version=cfg.version,
        is_active=cfg.is_active,
        params=cfg.params or {},
        origin=cfg.origin,
        validation=cfg.validation or {},
        activated_at=cfg.activated_at,
        created_at=cfg.created_at,
    )


@router.get(
    "/accounts/{account_id}/day-trade/config/history",
    response_model=list[DayTradeConfigHistoryOut],
)
def day_trade_config_history(
    account_id: str,
    _: AccountMembership = Depends(get_membership),
    db: Session = Depends(get_db),
) -> list[DayTradeConfigHistoryOut]:
    settings = get_settings()
    if not settings.day_trade_enabled:
        raise HTTPException(status_code=503, detail="Day trade study disabled")
    _require_us_account(db.get(InvestmentAccount, account_id))
    rows = dt_configs.list_history(db, limit=50)
    return [
        DayTradeConfigHistoryOut(
            version=r.version,
            params=r.params or {},
            origin=r.origin,
            reason=r.reason,
            validation=r.validation or {},
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.post(
    "/accounts/{account_id}/day-trade/config",
    response_model=DayTradeConfigOut,
)
def day_trade_config_set(
    account_id: str,
    body: DayTradeConfigSetIn,
    _: AccountMembership = Depends(require_roles(MembershipRole.owner, MembershipRole.operator)),
    db: Session = Depends(get_db),
) -> DayTradeConfigOut:
    settings = get_settings()
    if not settings.day_trade_enabled:
        raise HTTPException(status_code=503, detail="Day trade study disabled")
    _require_us_account(db.get(InvestmentAccount, account_id))
    if body.origin not in {"manual", "auto"}:
        raise HTTPException(status_code=400, detail="origin must be manual|auto")
    cfg = dt_configs.activate_params(
        db,
        body.params,
        origin=body.origin,
        reason=body.reason or "manual update via API",
    )
    db.commit()
    return DayTradeConfigOut(
        version=cfg.version,
        is_active=cfg.is_active,
        params=cfg.params or {},
        origin=cfg.origin,
        validation=cfg.validation or {},
        activated_at=cfg.activated_at,
        created_at=cfg.created_at,
    )


@router.post(
    "/accounts/{account_id}/day-trade/config/rollback",
    response_model=DayTradeConfigOut,
)
def day_trade_config_rollback(
    account_id: str,
    version: int | None = Query(default=None),
    _: AccountMembership = Depends(require_roles(MembershipRole.owner, MembershipRole.operator)),
    db: Session = Depends(get_db),
) -> DayTradeConfigOut:
    settings = get_settings()
    if not settings.day_trade_enabled:
        raise HTTPException(status_code=503, detail="Day trade study disabled")
    _require_us_account(db.get(InvestmentAccount, account_id))
    cfg = dt_configs.rollback_config(db, version=version)
    if cfg is None:
        raise HTTPException(status_code=404, detail="No rollback target available")
    db.commit()
    return DayTradeConfigOut(
        version=cfg.version,
        is_active=cfg.is_active,
        params=cfg.params or {},
        origin=cfg.origin,
        validation=cfg.validation or {},
        activated_at=cfg.activated_at,
        created_at=cfg.created_at,
    )


@router.get(
    "/accounts/{account_id}/day-trade/state",
    response_model=DayTradeStateOut,
)
def day_trade_state(
    account_id: str,
    _: AccountMembership = Depends(get_membership),
    db: Session = Depends(get_db),
) -> DayTradeStateOut:
    """Live day-trade health: circuit breaker + per-ticker session regime."""
    settings = get_settings()
    if not settings.day_trade_enabled:
        raise HTTPException(status_code=503, detail="Day trade study disabled")
    _require_us_account(db.get(InvestmentAccount, account_id))

    cfg = dt_configs.get_active_config(db)
    tripped = list((cfg.validation or {}).get("circuit_breaker_tripped") or [])

    cache = DayTradeBarCache()
    regimes: list[DayTradeRegimeOut] = []
    for ticker in cache.list_tickers():
        state = classify_regime(cache.get_bars(ticker))
        regimes.append(
            DayTradeRegimeOut(ticker=ticker, regime=state.regime, slope=state.slope)
        )
    regimes.sort(key=lambda r: r.ticker)

    return DayTradeStateOut(circuit_breaker_tripped=tripped, regimes=regimes)
