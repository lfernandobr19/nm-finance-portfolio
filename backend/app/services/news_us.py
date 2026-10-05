"""Finnhub US news ingestion → NewsEvent (dedup by URL)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from uuid import uuid4

from app.config import get_settings
from app.domain.models import NewsEvent
from app.services.hv_dip.universe import hv_dip_tickers

logger = logging.getLogger("fiidesk.news_us")
settings = get_settings()

# Cap on general-market articles per run (LLM classifier filters the rest).
_GENERAL_LIMIT = 50
# Company-news watchlist: mega caps + high-vol names (bounded subset of universe).
_COMPANY_NEWS_N = 40


def _parse_dt(value: int | float | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(int(value), tz=timezone.utc)
        except (OSError, ValueError, OverflowError):
            return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _related_tickers(related: str | None) -> list[str]:
    if not related:
        return []
    return [t.strip().upper() for t in str(related).split(",") if t.strip()]


def _fetch_general_news(client: httpx.Client, token: str) -> list[dict]:
    url = f"{settings.finnhub_base_url.rstrip('/')}/news"
    resp = client.get(url, params={"category": "general", "token": token})
    if resp.status_code >= 400:
        logger.warning("Finnhub news HTTP %s", resp.status_code)
        return []
    data = resp.json()
    return (data or [])[:_GENERAL_LIMIT]


def _fetch_company_news(client: httpx.Client, token: str, symbol: str, days: int = 2) -> list[dict]:
    to = datetime.now(timezone.utc)
    frm = to - timedelta(days=days)
    url = f"{settings.finnhub_base_url.rstrip('/')}/company-news"
    resp = client.get(
        url,
        params={
            "symbol": symbol,
            "from": frm.strftime("%Y-%m-%d"),
            "to": to.strftime("%Y-%m-%d"),
            "token": token,
        },
    )
    if resp.status_code >= 400:
        return []
    return resp.json() or []


def ingest_news_us(db: Session) -> int:
    """Fetch Finnhub general + company news and persist deduped NewsEvent rows.

    Returns the number of newly inserted rows. Dedup is enforced both locally
    (same URL appearing across overlapping general/company feeds in one batch)
    and at the DB level via ON CONFLICT DO NOTHING (concurrent worker runs).

    Classification (event_type/sentiment/confidence) is applied later by
    `news_llm.classify_pending`.
    """
    if not settings.news_us_enabled:
        return 0
    token = (settings.finnhub_api_key or "").strip()
    if not token:
        logger.info("Finnhub key missing — skip US news ingest")
        return 0

    articles: list[dict] = []
    with httpx.Client(timeout=30.0) as client:
        try:
            articles.extend(_fetch_general_news(client, token))
        except Exception:
            logger.exception("Finnhub general news failed")
        for sym in hv_dip_tickers()[:_COMPANY_NEWS_N]:
            try:
                articles.extend(_fetch_company_news(client, token, sym))
            except Exception:
                logger.exception("company-news failed for %s", sym)

    seen: set[str] = set()
    rows: list[dict] = []
    for art in articles:
        url = (art.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        title = (art.get("headline") or art.get("title") or "").strip()[:500]
        if not title:
            continue
        related = _related_tickers(art.get("related"))
        ticker = related[0] if related else None
        rows.append(
            {
                "id": str(uuid4()),
                "ticker": ticker,
                "title": title,
                "url": url[:1000],
                "source": str(art.get("source") or "finnhub")[:200],
                "event_type": None,
                "sentiment": None,
                "confidence": None,
                "impact_score": None,
                "catalyst_strength": None,
                "published_at": _parse_dt(art.get("datetime") or art.get("published")),
                "processed_at": None,
                "used_in_suggestion": False,
                "raw": dict(art),
            }
        )

    if not rows:
        logger.info("US news ingested=0 (fetched %d)", len(articles))
        return 0

    stmt = pg_insert(NewsEvent).values(rows).on_conflict_do_nothing(index_elements=["url"])
    db.execute(stmt)
    db.commit()
    logger.info("US news ingested=%d (fetched %d)", len(rows), len(articles))
    return len(rows)
