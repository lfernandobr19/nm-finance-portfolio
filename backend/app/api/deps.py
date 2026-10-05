from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_db
from app.domain.models import AccountMembership, InvestmentAccount, MembershipRole, User
from app.security import decode_token

bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_token(creds.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
    user = db.get(User, payload.get("sub"))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive")
    return user


def get_membership(
    account_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AccountMembership:
    membership = (
        db.query(AccountMembership)
        .filter(AccountMembership.account_id == account_id, AccountMembership.user_id == user.id)
        .one_or_none()
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to account")
    return membership


def require_roles(*roles: MembershipRole):
    def _dep(membership: AccountMembership = Depends(get_membership)) -> AccountMembership:
        if membership.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return membership

    return _dep


def get_account(account_id: str, db: Session = Depends(get_db)) -> InvestmentAccount:
    account = db.get(InvestmentAccount, account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return account
