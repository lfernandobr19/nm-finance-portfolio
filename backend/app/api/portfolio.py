from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_membership, require_roles
from app.db import get_db
from app.domain.models import (
    AccountMembership,
    InvestmentAccount,
    MembershipRole,
    Position,
    PositionExitReason,
    PositionStatus,
    StrategyKind,
)
from app.schemas import (
    CloseAllOut,
    PnlReportOut,
    PnlSeriesOut,
    PnlSeriesPointOut,
    PortfolioOut,
    PositionCloseIn,
    PositionOut,
    RotationDismissIn,
    SuggestionOut,
)
from app.services.positions import (
    close_all_open_at_market,
    close_position,
    close_position_at_market,
    mark_open_positions,
    pnl_report,
    pnl_series,
    portfolio_snapshot,
)

router = APIRouter(tags=["portfolio"])


def _pos_out(
    p: Position,
    *,
    mark_price: float | None = None,
    cost_brl: float | None = None,
    market_value_brl: float | None = None,
    unrealized_pnl_brl: float | None = None,
    unrealized_pnl_pct: float | None = None,
    peak_unrealized_pct: float | None = None,
    price_alert: str | None = None,
    exit_state: str | None = None,
    latched_5: bool | None = None,
    protect_active: bool | None = None,
    must_review_by: str | None = None,
    days_until_review: int | None = None,
) -> PositionOut:
    kind = p.strategy_kind
    status = p.status
    reason = p.exit_reason
    return PositionOut(
        id=p.id,
        account_id=p.account_id,
        order_id=p.order_id,
        suggestion_id=p.suggestion_id,
        ticker=p.ticker,
        strategy_kind=kind.value if hasattr(kind, "value") else str(kind),
        quantity=p.quantity,
        entry_price=p.entry_price,
        stop_price=p.stop_price,
        target_price=p.target_price,
        setup_low=getattr(p, "setup_low", None),
        tranche_index=int(getattr(p, "tranche_index", 1) or 1),
        avg_entry_price=getattr(p, "avg_entry_price", None),
        status=status.value if hasattr(status, "value") else str(status),
        exit_reason=(
            reason.value if reason and hasattr(reason, "value") else (str(reason) if reason else None)
        ),
        exit_price=p.exit_price,
        realized_pnl_brl=p.realized_pnl_brl,
        realized_pnl_pct=p.realized_pnl_pct,
        r_multiple_realized=p.r_multiple_realized,
        opened_at=p.opened_at,
        closed_at=p.closed_at,
        mark_price=mark_price,
        cost_brl=cost_brl,
        market_value_brl=market_value_brl,
        unrealized_pnl_brl=unrealized_pnl_brl,
        unrealized_pnl_pct=unrealized_pnl_pct,
        peak_unrealized_pct=peak_unrealized_pct,
        price_alert=price_alert,
        exit_state=exit_state,
        latched_5=latched_5,
        protect_active=protect_active,
        must_review_by=must_review_by,
        days_until_review=days_until_review,
    )


@router.get("/accounts/{account_id}/portfolio", response_model=PortfolioOut)
def get_portfolio(
    account_id: str,
    _: AccountMembership = Depends(get_membership),
    db: Session = Depends(get_db),
) -> PortfolioOut:
    account = db.get(InvestmentAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    snap = portfolio_snapshot(db, account)
    return PortfolioOut(**{k: snap[k] for k in PortfolioOut.model_fields if k in snap})


@router.get("/accounts/{account_id}/positions", response_model=list[PositionOut])
def list_positions(
    account_id: str,
    status_filter: str | None = Query(default=None, alias="status"),
    strategy_kind: StrategyKind | None = Query(default=None),
    _: AccountMembership = Depends(get_membership),
    db: Session = Depends(get_db),
) -> list[PositionOut]:
    q = db.query(Position).filter(Position.account_id == account_id)
    if status_filter:
        try:
            q = q.filter(Position.status == PositionStatus(status_filter))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="status must be open or closed") from exc
    if strategy_kind:
        q = q.filter(Position.strategy_kind == strategy_kind)
    rows = q.order_by(Position.opened_at.desc()).limit(200).all()

    if status_filter == "open":
        enriched, _ = mark_open_positions(db, account_id, strategy_kind=strategy_kind)
        by_id = {e["position"].id: e for e in enriched}
        out: list[PositionOut] = []
        for p in rows:
            e = by_id.get(p.id)
            if e:
                out.append(
                    _pos_out(
                        p,
                        mark_price=e["mark_price"],
                        cost_brl=e["cost_brl"],
                        market_value_brl=e["market_value_brl"],
                        unrealized_pnl_brl=e["unrealized_pnl_brl"],
                        unrealized_pnl_pct=e.get("unrealized_pnl_pct"),
                        peak_unrealized_pct=e.get("peak_unrealized_pct"),
                        price_alert=e.get("price_alert"),
                        exit_state=e.get("exit_state"),
                        latched_5=e.get("latched_5"),
                        protect_active=e.get("protect_active"),
                        must_review_by=e.get("must_review_by"),
                        days_until_review=e.get("days_until_review"),
                    )
                )
            else:
                out.append(_pos_out(p))
        return out
    return [_pos_out(p) for p in rows]


@router.post(
    "/accounts/{account_id}/positions/{position_id}/close",
    response_model=PositionOut,
)
def api_close_position(
    account_id: str,
    position_id: str,
    body: PositionCloseIn,
    _: AccountMembership = Depends(
        require_roles(MembershipRole.owner, MembershipRole.operator)
    ),
    db: Session = Depends(get_db),
) -> PositionOut:
    position = (
        db.query(Position)
        .filter(Position.id == position_id, Position.account_id == account_id)
        .one_or_none()
    )
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")

    reason_raw = (body.reason or "").strip().lower()
    try:
        if reason_raw == "market":
            close_position_at_market(db, position)
        else:
            reason = PositionExitReason(reason_raw)
            close_position(db, position, reason=reason, manual_price=body.price)
        db.commit()
        db.refresh(position)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _pos_out(position)


@router.post(
    "/accounts/{account_id}/positions/{position_id}/suggest-more",
    response_model=SuggestionOut,
)
def api_suggest_more(
    account_id: str,
    position_id: str,
    _: AccountMembership = Depends(
        require_roles(MembershipRole.owner, MembershipRole.operator)
    ),
    db: Session = Depends(get_db),
) -> SuggestionOut:
    """Comprar mais: re-analisa um ativo já detido e emite nova sugestão pendente
    (tranche N+1) que passa pela revisão/auto-buy normal."""
    position = (
        db.query(Position)
        .filter(Position.id == position_id, Position.account_id == account_id)
        .one_or_none()
    )
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    if position.status != PositionStatus.open:
        raise HTTPException(status_code=400, detail="Position is not open")
    if position.strategy_kind != StrategyKind.hv_dip:
        raise HTTPException(
            status_code=400,
            detail="Comprar mais (tranche) só se aplica a posições NM High-Vol",
        )
    account = db.get(InvestmentAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    from app.services.hv_dip.engine import suggest_more_for_ticker

    try:
        suggestion = suggest_more_for_ticker(db, account, position.ticker)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return suggestion


@router.post(
    "/accounts/{account_id}/positions/close-all",
    response_model=CloseAllOut,
)
def api_close_all_positions(
    account_id: str,
    strategy_kind: StrategyKind | None = Query(default=None),
    _: AccountMembership = Depends(
        require_roles(MembershipRole.owner, MembershipRole.operator)
    ),
    db: Session = Depends(get_db),
) -> CloseAllOut:
    account = db.get(InvestmentAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    try:
        closed = close_all_open_at_market(db, account_id, strategy_kind=strategy_kind)
        db.commit()
        for p in closed:
            db.refresh(p)
        db.refresh(account)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CloseAllOut(
        closed=len(closed),
        cash_brl=float(account.cash_brl or 0),
        items=[_pos_out(p) for p in closed],
    )


@router.get("/accounts/{account_id}/pnl", response_model=PnlReportOut)
def get_pnl(
    account_id: str,
    period: str = Query(default="day"),
    strategy_kind: StrategyKind | None = Query(default=None),
    _: AccountMembership = Depends(get_membership),
    db: Session = Depends(get_db),
) -> PnlReportOut:
    if period not in {"day", "week", "month", "year"}:
        raise HTTPException(status_code=400, detail="period must be day|week|month|year")
    report = pnl_report(db, account_id, period=period, strategy_kind=strategy_kind)
    return PnlReportOut(
        period=report["period"],
        strategy_kind=report["strategy_kind"],
        **{"from": report["from"]},
        total_pnl_brl=report["total_pnl_brl"],
        trades=report["trades"],
        wins=report["wins"],
        losses=report["losses"],
        items=[_pos_out(p) for p in report["items"]],
        goals=report.get("goals"),
        scorecard=report.get("scorecard"),
    )


@router.get("/accounts/{account_id}/pnl/series", response_model=PnlSeriesOut)
def get_pnl_series(
    account_id: str,
    period: str = Query(default="month"),
    strategy_kind: StrategyKind | None = Query(default=None),
    _: AccountMembership = Depends(get_membership),
    db: Session = Depends(get_db),
) -> PnlSeriesOut:
    if period not in {"day", "week", "month", "year"}:
        raise HTTPException(status_code=400, detail="period must be day|week|month|year")
    series = pnl_series(db, account_id, period=period, strategy_kind=strategy_kind)
    return PnlSeriesOut(
        period=series["period"],
        strategy_kind=series["strategy_kind"],
        currency=series["currency"],
        **{"from": series["from"]},
        points=[PnlSeriesPointOut(**p) for p in series["points"]],
        goals=series.get("goals"),
        daily_target_pct=series.get("daily_target_pct", 7.0),
        equity_ref=series.get("equity_ref", 0.0),
    )


@router.post(
    "/accounts/{account_id}/positions/{position_id}/extend-review",
    response_model=PositionOut,
)
def extend_position_review(
    account_id: str,
    position_id: str,
    _: AccountMembership = Depends(
        require_roles(MembershipRole.owner, MembershipRole.operator)
    ),
    db: Session = Depends(get_db),
) -> PositionOut:
    position = (
        db.query(Position)
        .filter(Position.id == position_id, Position.account_id == account_id)
        .one_or_none()
    )
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    if position.status != PositionStatus.open:
        raise HTTPException(status_code=400, detail="Position is not open")
    from app.services.hv_dip.exit_engine import extend_time_review

    try:
        metrics = extend_time_review(dict(position.metrics or {}))
        position.metrics = metrics
        db.commit()
        db.refresh(position)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _pos_out(position)


@router.post(
    "/accounts/{account_id}/positions/{position_id}/rotation/dismiss",
    response_model=PositionOut,
)
def dismiss_rotation(
    account_id: str,
    position_id: str,
    body: RotationDismissIn,
    _: AccountMembership = Depends(
        require_roles(MembershipRole.owner, MembershipRole.operator)
    ),
    db: Session = Depends(get_db),
) -> PositionOut:
    position = (
        db.query(Position)
        .filter(Position.id == position_id, Position.account_id == account_id)
        .one_or_none()
    )
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    metrics = dict(position.metrics or {})
    dismissed = list(metrics.get("rotation_dismissed_ids") or [])
    if body.suggestion_id not in dismissed:
        dismissed.append(body.suggestion_id)
    metrics["rotation_dismissed_ids"] = dismissed[-50:]
    position.metrics = metrics
    db.commit()
    db.refresh(position)
    return _pos_out(position)
