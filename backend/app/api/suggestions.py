from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_membership, require_roles
from app.db import get_db
from app.domain.models import (
    AccountMembership,
    InvestmentAccount,
    MembershipRole,
    Order,
    OrderStatus,
    StrategyKind,
    Suggestion,
    SuggestionStatus,
)
from app.schemas import (
    ApproveOptionOut,
    SuggestionAction,
    SuggestionApproveOptionsOut,
    SuggestionApproveOut,
    SuggestionOut,
)

router = APIRouter(tags=["suggestions"])


@router.get("/accounts/{account_id}/suggestions", response_model=list[SuggestionOut])
def list_suggestions(
    account_id: str,
     status_filter: SuggestionStatus | None = Query(default=None, alias="status"),
    strategy_kind: StrategyKind | None = Query(default=None),
    _: AccountMembership = Depends(get_membership),
    db: Session = Depends(get_db),
) -> list[Suggestion]:
    q = db.query(Suggestion).filter(Suggestion.account_id == account_id)
    if status_filter:
        q = q.filter(Suggestion.status == status_filter)
    if strategy_kind:
        q = q.filter(Suggestion.strategy_kind == strategy_kind)
    return q.order_by(Suggestion.created_at.desc()).limit(100).all()


@router.get("/accounts/{account_id}/suggestions/{suggestion_id}", response_model=SuggestionOut)
def get_suggestion(
    account_id: str,
    suggestion_id: str,
    _: AccountMembership = Depends(get_membership),
    db: Session = Depends(get_db),
) -> Suggestion:
    suggestion = (
        db.query(Suggestion)
        .filter(Suggestion.id == suggestion_id, Suggestion.account_id == account_id)
        .one_or_none()
    )
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return suggestion


@router.get(
    "/accounts/{account_id}/suggestions/{suggestion_id}/approve-options",
    response_model=SuggestionApproveOptionsOut,
)
def get_approve_options(
    account_id: str,
    suggestion_id: str,
    _: AccountMembership = Depends(get_membership),
    db: Session = Depends(get_db),
) -> SuggestionApproveOptionsOut:
    from app.services.approve_options import build_approve_options

    suggestion = (
        db.query(Suggestion)
        .filter(Suggestion.id == suggestion_id, Suggestion.account_id == account_id)
        .one_or_none()
    )
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    account = db.get(InvestmentAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    raw = build_approve_options(db, account, suggestion)
    return SuggestionApproveOptionsOut(
        live_price=raw["live_price"],
        fractional_allowed=raw["fractional_allowed"],
        max_amount_usd=raw["max_amount_usd"],
        default_amount_usd=raw["default_amount_usd"],
        approvable=raw["approvable"],
        block_reason=raw["block_reason"],
        options=[ApproveOptionOut(**o) for o in raw["options"]],
    )


def _latest_order(db: Session, suggestion_id: str) -> Order | None:
    return (
        db.query(Order)
        .filter(Order.suggestion_id == suggestion_id)
        .order_by(Order.created_at.desc())
        .first()
    )


def _fill_hint(order: Order | None) -> str | None:
    if not order:
        return None
    payload = order.execution_payload or {}
    mode = payload.get("hv_dip_submit_mode")
    live = payload.get("approve_live_price")
    if mode == "notional_market":
        return f"Notional ~US$ {order.amount_brl:.2f} ao preço de mercado"
    if mode == "limit_live" and live is not None:
        return f"Limit US$ {order.limit_price:.2f} (vivo ~US$ {float(live):.2f})"
    if order.status == OrderStatus.filled and order.filled_price:
        return f"Executado ~US$ {float(order.filled_price):.2f}"
    if live is not None:
        return f"Cotação ao vivo ~US$ {float(live):.2f}"
    return None


def _approve_out(suggestion: Suggestion, order: Order | None) -> SuggestionApproveOut:
    base = SuggestionOut.model_validate(suggestion)
    live_price = None
    if order:
        live_price = (order.execution_payload or {}).get("approve_live_price")
        if live_price is not None:
            live_price = float(live_price)
    if not order:
        return SuggestionApproveOut(
            **base.model_dump(),
            order_id=None,
            order_status=None,
            order_error=None,
            live_price=live_price,
            fill_hint=None,
        )
    return SuggestionApproveOut(
        **base.model_dump(),
        order_id=order.id,
        order_status=str(order.status.value if hasattr(order.status, "value") else order.status),
        order_error=order.error_message,
        live_price=live_price,
        fill_hint=_fill_hint(order),
    )


def _act(
    account_id: str,
    suggestion_id: str,
    new_status: SuggestionStatus,
    note: str | None,
    membership: AccountMembership,
    db: Session,
    amount_usd: float | None = None,
) -> tuple[Suggestion, Order | None]:
    from app.services.orders import create_order_from_suggestion

    suggestion = (
        db.query(Suggestion)
        .filter(Suggestion.id == suggestion_id, Suggestion.account_id == account_id)
        .one_or_none()
    )
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    retry_order = False
    if suggestion.status == SuggestionStatus.approved and new_status == SuggestionStatus.approved:
        last = _latest_order(db, suggestion.id)
        if last and last.status == OrderStatus.rejected:
            retry_order = True
        else:
            raise HTTPException(status_code=400, detail="Suggestion already approved")
    elif suggestion.status != SuggestionStatus.pending:
        raise HTTPException(status_code=400, detail="Suggestion is not pending")

    expires = suggestion.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        suggestion.status = SuggestionStatus.expired
        db.commit()
        raise HTTPException(status_code=400, detail="Suggestion expired")

    order: Order | None = None
    if not retry_order:
        suggestion.status = new_status
        suggestion.acted_by_user_id = membership.user_id
        suggestion.action_note = note
        suggestion.acted_at = datetime.now(timezone.utc)

    if new_status == SuggestionStatus.approved:
        try:
            order = create_order_from_suggestion(
                db,
                suggestion,
                acted_by_user_id=membership.user_id,
                human_approved=True,
                amount_usd=amount_usd,
            )
        except ValueError as exc:
            db.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    db.commit()
    db.refresh(suggestion)
    if order:
        db.refresh(order)
    return suggestion, order


@router.post(
    "/accounts/{account_id}/suggestions/{suggestion_id}/approve",
    response_model=SuggestionApproveOut,
)
def approve_suggestion(
    account_id: str,
    suggestion_id: str,
    body: SuggestionAction,
    membership: AccountMembership = Depends(
        require_roles(MembershipRole.owner, MembershipRole.operator)
    ),
    db: Session = Depends(get_db),
) -> SuggestionApproveOut:
    suggestion, order = _act(
        account_id,
        suggestion_id,
        SuggestionStatus.approved,
        body.note,
        membership,
        db,
        amount_usd=body.amount_usd,
    )
    return _approve_out(suggestion, order)


@router.post(
    "/accounts/{account_id}/suggestions/{suggestion_id}/reject",
    response_model=SuggestionOut,
)
def reject_suggestion(
    account_id: str,
    suggestion_id: str,
    body: SuggestionAction,
    membership: AccountMembership = Depends(
        require_roles(MembershipRole.owner, MembershipRole.operator)
    ),
    db: Session = Depends(get_db),
) -> Suggestion:
    suggestion, _ = _act(
        account_id, suggestion_id, SuggestionStatus.rejected, body.note, membership, db
    )
    return suggestion
