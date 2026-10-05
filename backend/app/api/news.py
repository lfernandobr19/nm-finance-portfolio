from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_membership
from app.db import get_db
from app.domain.models import AccountMembership, NewsEvent, NewsItem, User
from app.schemas import DeviceTokenIn, NewsEventOut, NewsOut
from app.services.notify import register_device_token

router = APIRouter(tags=["news"])


@router.get("/accounts/{account_id}/news", response_model=list[NewsOut])
def list_news(
    account_id: str,
    ticker: str | None = Query(default=None),
    _: AccountMembership = Depends(get_membership),
    db: Session = Depends(get_db),
) -> list[NewsItem]:
    q = db.query(NewsItem)
    if ticker:
        q = q.filter(NewsItem.ticker == ticker.upper())
    return q.order_by(NewsItem.published_at.desc().nullslast(), NewsItem.created_at.desc()).limit(50).all()


@router.get("/accounts/{account_id}/news-events", response_model=list[NewsEventOut])
def list_news_events(
    account_id: str,
    ticker: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    sentiment: str | None = Query(default=None),
    _: AccountMembership = Depends(get_membership),
    db: Session = Depends(get_db),
) -> list[NewsEventOut]:
    """LLM-classified catalyst feed (event_type/sentiment/confidence/impact)."""
    q = db.query(NewsEvent)
    if ticker:
        q = q.filter(NewsEvent.ticker == ticker.upper())
    if event_type:
        q = q.filter(NewsEvent.event_type == event_type.lower())
    if sentiment:
        q = q.filter(NewsEvent.sentiment == sentiment.lower())
    return (
        q.order_by(NewsEvent.published_at.desc().nullslast(), NewsEvent.created_at.desc())
        .limit(200)
        .all()
    )


@router.post("/devices", status_code=201)
def register_device(
    body: DeviceTokenIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    register_device_token(db, user_id=user.id, token=body.token, platform=body.platform)
    return {"ok": True}
