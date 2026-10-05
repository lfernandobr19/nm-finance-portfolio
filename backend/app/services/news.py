from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.models import NewsItem

settings = get_settings()

KNOWN_TICKERS = [
    "HGLG11",
    "XPML11",
    "MXRF11",
    "KNRI11",
    "VISC11",
    "BTLG11",
    "XPLG11",
    "R1IN34",
    "L1TC34",
    "A1DC34",
    "S2TA34",
]


def _guess_ticker(title: str) -> str | None:
    upper = title.upper()
    for t in KNOWN_TICKERS:
        if t in upper:
            return t
    return None


def ingest_news(db: Session) -> list[NewsItem]:
    feed = feedparser.parse(settings.news_feed_url)
    created: list[NewsItem] = []
    for entry in feed.entries[:40]:
        title = getattr(entry, "title", "") or ""
        link = getattr(entry, "link", "") or ""
        if not title or not link:
            continue
        exists = db.query(NewsItem).filter(NewsItem.url == link).one_or_none()
        if exists:
            continue
        published_at = None
        if getattr(entry, "published", None):
            try:
                published_at = parsedate_to_datetime(entry.published)
            except (TypeError, ValueError, IndexError):
                published_at = datetime.now(timezone.utc)
        item = NewsItem(
            ticker=_guess_ticker(title),
            title=title[:500],
            url=link[:1000],
            source=getattr(feed.feed, "title", "RSS")[:200],
            published_at=published_at,
        )
        db.add(item)
        created.append(item)
    db.commit()
    return created
