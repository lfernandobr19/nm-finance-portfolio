import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.config import get_settings
from app.db import get_db
from app.domain.models import User
from app.schemas import (
    ChangePasswordIn,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    TokenPair,
    UserCreate,
    UserLogin,
    UserOut,
)
from app.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(body: UserCreate, db: Session = Depends(get_db)) -> User:
    exists = db.query(User).filter(User.email == body.email.lower()).one_or_none()
    if exists:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=body.email.lower(),
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenPair)
def login(body: UserLogin, db: Session = Depends(get_db)) -> TokenPair:
    user = db.query(User).filter(User.email == body.email.lower()).one_or_none()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)) -> TokenPair:
    try:
        payload = decode_token(body.refresh_token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid refresh token") from exc
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    user = db.get(User, payload.get("sub"))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User inactive")
    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/password-reset/request")
def password_reset_request(body: PasswordResetRequest, db: Session = Depends(get_db)) -> dict:
    """Generate a 6-digit reset code. No email — code is logged on the server (local Tailscale)."""
    user = db.query(User).filter(User.email == body.email.lower()).one_or_none()
    # Always generic OK to avoid email enumeration
    out: dict = {"ok": True}
    if user and user.is_active:
        code = f"{secrets.randbelow(1_000_000):06d}"
        user.password_reset_code_hash = hash_password(code)
        user.password_reset_expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.password_reset_ttl_minutes
        )
        db.commit()
        logger.warning(
            "PASSWORD_RESET email=%s code=%s expires_in=%sm (check Ravenna api log)",
            user.email,
            code,
            settings.password_reset_ttl_minutes,
        )
        if settings.password_reset_echo:
            out["code"] = code
    return out


@router.post("/password-reset/confirm")
def password_reset_confirm(body: PasswordResetConfirm, db: Session = Depends(get_db)) -> dict:
    user = db.query(User).filter(User.email == body.email.lower()).one_or_none()
    if not user or not user.password_reset_code_hash or not user.password_reset_expires_at:
        raise HTTPException(status_code=400, detail="Invalid or expired reset code")
    expires = user.password_reset_expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invalid or expired reset code")
    if not verify_password(body.code.strip(), user.password_reset_code_hash):
        raise HTTPException(status_code=400, detail="Invalid or expired reset code")
    user.hashed_password = hash_password(body.new_password)
    user.password_reset_code_hash = None
    user.password_reset_expires_at = None
    db.commit()
    return {"ok": True}


@router.post("/change-password")
def change_password(
    body: ChangePasswordIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.hashed_password = hash_password(body.new_password)
    db.commit()
    return {"ok": True}
