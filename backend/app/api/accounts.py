import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_membership, require_roles
from app.config import get_settings
from app.db import get_db
from app.domain.models import (
    AccountCurrency,
    AccountMembership,
    AccountRule,
    DayTradeSignal,
    ExecutionMode,
    HvDipObservation,
    Invite,
    InvestmentAccount,
    MembershipRole,
    Order,
    Position,
    Suggestion,
    User,
    WatchlistItem,
)
from app.schemas import (
    AccountCreate,
    AccountOut,
    AccountUpdate,
    InviteAccept,
    InviteCreate,
    InviteOut,
    MembershipOut,
    RuleOut,
    RuleUpdate,
)

router = APIRouter(prefix="/accounts", tags=["accounts"])
settings = get_settings()


def _account_out(account: InvestmentAccount, role: MembershipRole | None) -> AccountOut:
    currency = getattr(account, "currency", None)
    currency_val = currency.value if hasattr(currency, "value") else str(currency or "BRL")
    return AccountOut(
        id=account.id,
        name=account.name,
        owner_user_id=account.owner_user_id,
        target_capital=account.target_capital,
        auto_approve_enabled=account.auto_approve_enabled,
        auto_approve_min_score=account.auto_approve_min_score,
        daily_auto_approve_limit=account.daily_auto_approve_limit,
        max_ticket_brl=account.max_ticket_brl,
        broker_code=getattr(account, "broker_code", None) or "inter",
        execution_mode=(
            account.execution_mode.value
            if hasattr(getattr(account, "execution_mode", None), "value")
            else str(getattr(account, "execution_mode", "paper") or "paper")
        ),
        order_type=getattr(account, "order_type", None) or "limit",
        swing_max_positions=getattr(account, "swing_max_positions", 5) or 5,
        swing_cash_floor_pct=getattr(account, "swing_cash_floor_pct", 20.0) or 20.0,
        swing_risk_pct_a=getattr(account, "swing_risk_pct_a", 1.5) or 1.5,
        swing_risk_pct_b=getattr(account, "swing_risk_pct_b", 1.0) or 1.0,
        swing_equity_brl=getattr(account, "swing_equity_brl", 10000.0) or 10000.0,
        cash_brl=getattr(account, "cash_brl", None)
        if getattr(account, "cash_brl", None) is not None
        else (getattr(account, "swing_equity_brl", 10000.0) or 10000.0),
        currency=currency_val,
        cash_usd=float(getattr(account, "cash_usd", None) or 0),
        hv_dip_max_positions=int(getattr(account, "hv_dip_max_positions", 4) or 4),
        hv_dip_cash_floor_pct=float(getattr(account, "hv_dip_cash_floor_pct", 30.0) or 30.0),
        hv_dip_max_ticker_pct=float(getattr(account, "hv_dip_max_ticker_pct", 80.0) or 80.0),
        hv_dip_equity_usd=float(getattr(account, "hv_dip_equity_usd", 100.0) or 100.0),
        automation_paused=bool(getattr(account, "automation_paused", False) or False),
        created_at=account.created_at,
        my_role=role,
    )


@router.post("", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
def create_account(
    body: AccountCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AccountOut:
    account = InvestmentAccount(
        name=body.name,
        owner_user_id=user.id,
        target_capital=body.target_capital,
        max_ticket_brl=body.max_ticket_brl,
        auto_approve_enabled=False,
        cash_brl=10000.0,
        swing_equity_brl=10000.0,
        currency=AccountCurrency.BRL,
    )
    db.add(account)
    db.flush()
    db.add(
        AccountMembership(user_id=user.id, account_id=account.id, role=MembershipRole.owner)
    )
    db.add(
        AccountRule(
            account_id=account.id,
            version=1,
            is_active=True,
            allowed_sectors=[],
            excluded_tickers=[],
            allowed_asset_classes=["fii", "bdr_reit"],
            prefer_monthly_dividends=True,
            min_effective_yield=8.0,
            min_dividend_yield=8.0,
        )
    )
    db.commit()
    db.refresh(account)
    return _account_out(account, MembershipRole.owner)


@router.post("/ensure-nm-usd", response_model=AccountOut)
def ensure_nm_usd_account(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AccountOut:
    """Idempotent seed: NM Finance USD paper account for current user.

    Looks for ANY USD account owned by the user (tastytrade paper/live).
    Only creates a new paper account when the user has none at all. This
    prevents a duplicate tastytrade account from being recreated.
    """
    existing = (
        db.query(InvestmentAccount)
        .join(AccountMembership, AccountMembership.account_id == InvestmentAccount.id)
        .filter(
            AccountMembership.user_id == user.id,
            InvestmentAccount.currency == AccountCurrency.USD,
        )
        .order_by(InvestmentAccount.created_at.asc())
        .first()
    )
    if existing:
        mem = (
            db.query(AccountMembership)
            .filter(
                AccountMembership.user_id == user.id,
                AccountMembership.account_id == existing.id,
            )
            .one()
        )
        return _account_out(existing, mem.role)

    account = InvestmentAccount(
        name="NM USD Paper",
        owner_user_id=user.id,
        target_capital=100.0,
        max_ticket_brl=100.0,
        auto_approve_enabled=False,
        broker_code="tastytrade",
        execution_mode=ExecutionMode.paper,
        currency=AccountCurrency.USD,
        cash_brl=0.0,
        cash_usd=100.0,
        hv_dip_equity_usd=100.0,
        hv_dip_max_positions=4,
        hv_dip_cash_floor_pct=30.0,
        hv_dip_max_ticker_pct=80.0,
        swing_equity_brl=0.0,
    )
    db.add(account)
    db.flush()
    db.add(
        AccountMembership(user_id=user.id, account_id=account.id, role=MembershipRole.owner)
    )
    db.add(
        AccountRule(
            account_id=account.id,
            version=1,
            is_active=True,
            allowed_sectors=[],
            excluded_tickers=[],
            allowed_asset_classes=["us_equity"],
            prefer_monthly_dividends=False,
            min_effective_yield=0.0,
            min_dividend_yield=0.0,
            score_threshold=50.0,
        )
    )
    db.commit()
    db.refresh(account)
    return _account_out(account, MembershipRole.owner)


@router.get("", response_model=list[AccountOut])
def list_accounts(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AccountOut]:
    rows = (
        db.query(InvestmentAccount, AccountMembership)
        .join(AccountMembership, AccountMembership.account_id == InvestmentAccount.id)
        .filter(AccountMembership.user_id == user.id)
        .all()
    )
    return [_account_out(acc, mem.role) for acc, mem in rows]


@router.get("/{account_id}", response_model=AccountOut)
def get_account_detail(
    account_id: str,
    membership: AccountMembership = Depends(get_membership),
    db: Session = Depends(get_db),
) -> AccountOut:
    account = db.get(InvestmentAccount, account_id)
    assert account is not None
    return _account_out(account, membership.role)


@router.patch("/{account_id}", response_model=AccountOut)
def update_account(
    account_id: str,
    body: AccountUpdate,
    membership: AccountMembership = Depends(require_roles(MembershipRole.owner)),
    db: Session = Depends(get_db),
) -> AccountOut:
    from app.domain.models import ExecutionMode

    account = db.get(InvestmentAccount, account_id)
    assert account is not None
    data = body.model_dump(exclude_unset=True)
    if "execution_mode" in data and data["execution_mode"] is not None:
        try:
            data["execution_mode"] = ExecutionMode(data["execution_mode"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="execution_mode must be paper or live") from exc
    if "currency" in data and data["currency"] is not None:
        try:
            data["currency"] = AccountCurrency(str(data["currency"]).upper())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="currency must be BRL or USD") from exc
    for key, value in data.items():
        setattr(account, key, value)
    db.commit()
    db.refresh(account)
    return _account_out(account, membership.role)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    account_id: str,
    _membership: AccountMembership = Depends(require_roles(MembershipRole.owner)),
    db: Session = Depends(get_db),
) -> None:
    """Delete an account and all of its data (owner only, irreversible).

    Children are deleted explicitly (order matters due to FK constraints):
    positions → orders → day-trade signals → suggestions → watchlist →
    observations → invites → rules → memberships → account.
    """
    account = db.get(InvestmentAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    for model in (
        Position,
        Order,
        DayTradeSignal,
        Suggestion,
        WatchlistItem,
        HvDipObservation,
        Invite,
        AccountRule,
        AccountMembership,
    ):
        db.query(model).filter(model.account_id == account_id).delete(
            synchronize_session=False
        )
    db.delete(account)
    db.commit()


@router.get("/{account_id}/members", response_model=list[MembershipOut])
def list_members(
    account_id: str,
    _: AccountMembership = Depends(get_membership),
    db: Session = Depends(get_db),
) -> list[MembershipOut]:
    rows = (
        db.query(AccountMembership, User)
        .join(User, User.id == AccountMembership.user_id)
        .filter(AccountMembership.account_id == account_id)
        .all()
    )
    return [
        MembershipOut(
            id=m.id,
            user_id=m.user_id,
            account_id=m.account_id,
            role=m.role,
            email=u.email,
            full_name=u.full_name,
        )
        for m, u in rows
    ]


@router.post("/{account_id}/invites", response_model=InviteOut, status_code=status.HTTP_201_CREATED)
def create_invite(
    account_id: str,
    body: InviteCreate,
    membership: AccountMembership = Depends(require_roles(MembershipRole.owner)),
    db: Session = Depends(get_db),
) -> Invite:
    if body.role == MembershipRole.owner:
        raise HTTPException(status_code=400, detail="Cannot invite as owner")
    invite = Invite(
        account_id=account_id,
        code=secrets.token_urlsafe(12),
        role=body.role,
        created_by_user_id=membership.user_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.invite_ttl_days),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite


@router.get("/{account_id}/invites", response_model=list[InviteOut])
def list_invites(
    account_id: str,
    _: AccountMembership = Depends(require_roles(MembershipRole.owner)),
    db: Session = Depends(get_db),
) -> list[Invite]:
    return (
        db.query(Invite)
        .filter(Invite.account_id == account_id, Invite.accepted_at.is_(None))
        .order_by(Invite.expires_at.desc())
        .all()
    )


@router.post("/invites/accept", response_model=MembershipOut)
def accept_invite(
    body: InviteAccept,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MembershipOut:
    invite = db.query(Invite).filter(Invite.code == body.code).one_or_none()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.accepted_at is not None:
        raise HTTPException(status_code=400, detail="Invite already used")
    expires = invite.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invite expired")
    existing = (
        db.query(AccountMembership)
        .filter(
            AccountMembership.account_id == invite.account_id,
            AccountMembership.user_id == user.id,
        )
        .one_or_none()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Already a member")
    membership = AccountMembership(
        user_id=user.id, account_id=invite.account_id, role=invite.role
    )
    invite.accepted_at = datetime.now(timezone.utc)
    invite.accepted_by_user_id = user.id
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return MembershipOut(
        id=membership.id,
        user_id=membership.user_id,
        account_id=membership.account_id,
        role=membership.role,
        email=user.email,
        full_name=user.full_name,
    )


@router.delete("/{account_id}/members/{member_user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    account_id: str,
    member_user_id: str,
    membership: AccountMembership = Depends(require_roles(MembershipRole.owner)),
    db: Session = Depends(get_db),
) -> None:
    account = db.get(InvestmentAccount, account_id)
    assert account is not None
    if member_user_id == account.owner_user_id:
        raise HTTPException(status_code=400, detail="Cannot remove account owner")
    target = (
        db.query(AccountMembership)
        .filter(
            AccountMembership.account_id == account_id,
            AccountMembership.user_id == member_user_id,
        )
        .one_or_none()
    )
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")
    db.delete(target)
    db.commit()


@router.get("/{account_id}/rules", response_model=RuleOut)
def get_active_rules(
    account_id: str,
    _: AccountMembership = Depends(get_membership),
    db: Session = Depends(get_db),
) -> AccountRule:
    rule = (
        db.query(AccountRule)
        .filter(AccountRule.account_id == account_id, AccountRule.is_active.is_(True))
        .order_by(AccountRule.version.desc())
        .first()
    )
    if not rule:
        raise HTTPException(status_code=404, detail="No active rules")
    return rule


@router.put("/{account_id}/rules", response_model=RuleOut)
def update_rules(
    account_id: str,
    body: RuleUpdate,
    _: AccountMembership = Depends(require_roles(MembershipRole.owner)),
    db: Session = Depends(get_db),
) -> AccountRule:
    current = (
        db.query(AccountRule)
        .filter(AccountRule.account_id == account_id, AccountRule.is_active.is_(True))
        .order_by(AccountRule.version.desc())
        .first()
    )
    if current:
        current.is_active = False
        next_version = current.version + 1
        base = {
            "min_dividend_yield": current.min_dividend_yield,
            "min_effective_yield": getattr(current, "min_effective_yield", current.min_dividend_yield),
            "max_p_vp": current.max_p_vp,
            "min_avg_volume": current.min_avg_volume,
            "allowed_sectors": list(current.allowed_sectors or []),
            "excluded_tickers": list(current.excluded_tickers or []),
            "allowed_asset_classes": list(
                getattr(current, "allowed_asset_classes", None) or ["fii", "bdr_reit"]
            ),
            "prefer_monthly_dividends": getattr(current, "prefer_monthly_dividends", True),
            "score_threshold": current.score_threshold,
        }
    else:
        next_version = 1
        base = {
            "min_dividend_yield": 8.0,
            "min_effective_yield": 8.0,
            "max_p_vp": 1.05,
            "min_avg_volume": 500_000.0,
            "allowed_sectors": [],
            "excluded_tickers": [],
            "allowed_asset_classes": ["fii", "bdr_reit"],
            "prefer_monthly_dividends": True,
            "score_threshold": 70.0,
        }
    updates = body.model_dump(exclude_unset=True)
    # Legacy alias: min_dividend_yield mirrors min_effective_yield when only one is set
    if "min_effective_yield" in updates and "min_dividend_yield" not in updates:
        updates["min_dividend_yield"] = updates["min_effective_yield"]
    elif "min_dividend_yield" in updates and "min_effective_yield" not in updates:
        updates["min_effective_yield"] = updates["min_dividend_yield"]
    base.update(updates)
    rule = AccountRule(account_id=account_id, version=next_version, is_active=True, **base)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule
