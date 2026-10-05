"""LLM classifier for US news events → structured JSON catalyst."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.models import NewsEvent, Position, PositionStatus
from app.services.llm_client import chat, local_configured, cloud_configured
from app.services.hv_dip.universe import HV_DIP_UNIVERSE

logger = logging.getLogger("fiidesk.news_llm")

PROMPT_VERSION = "classify_v1"

_EVENT_TYPES = [
    "partnership",
    "guidance_up",
    "guidance_down",
    "upgrade",
    "downgrade",
    "m_and_a",
    "contract",
    "product_launch",
    "earnings",
    "litigation",
    "regulation",
    "buyback",
    "restructuring",
    "new_leadership",
    "turnaround",
    "other",
]

RECOVERY_EVENT_TYPES = {
    "restructuring",
    "guidance_up",
    "buyback",
    "new_leadership",
    "turnaround",
}

SYSTEM = (
    "Você classifica notícias de ações dos EUA para um sistema de trading. "
    "Retorne APENAS JSON válido, sem markdown, no formato exato:\n"
    '{"ticker":"SYMBOL","event_type":"partnership","sentiment":"bullish",'
    '"confidence":0.85,"catalyst_strength":"high","impact_score":70}\n'
    "Regras: use apenas a notícia fornecida; não invente ticker, evento ou números. "
    "ticker é o símbolo US em maiúsculas quando identificável (senão string vazia). "
    "event_type deve ser um de: "
    + ", ".join(_EVENT_TYPES)
    + ". sentiment é bullish, bearish ou neutral. confidence entre 0 e 1. "
    "impact_score entre 0 e 100 (impacto esperado no preço)."
)

_TICKER_TOKEN = re.compile(r"\b([A-Z]{1,5})\b")
_UNIVERSE = {t.upper() for t in HV_DIP_UNIVERSE}


class ClassifyOut(BaseModel):
    ticker: str = ""
    event_type: str = "other"
    sentiment: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    catalyst_strength: str | None = None
    impact_score: float = Field(default=0.0, ge=0.0, le=100.0)


CLASSIFY_SCHEMA: dict = ClassifyOut.model_json_schema()


def _parse_json(content: str) -> dict | None:
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def _event_type_valid(value: str | None) -> bool:
    return bool(value) and value.strip().lower() in _EVENT_TYPES


def _related_tickers(raw: dict, ev: NewsEvent) -> list[str]:
    related = [
        t.strip().upper()
        for t in str((raw or {}).get("related") or "").split(",")
        if t.strip()
    ]
    if ev.ticker:
        related.append(ev.ticker.upper())
    return list(dict.fromkeys(related))


def tickers_in_title(title: str) -> list[str]:
    found = [m.group(1) for m in _TICKER_TOKEN.finditer((title or "").upper())]
    return [t for t in found if t in _UNIVERSE]


def resolve_candidate_tickers(ev: NewsEvent) -> list[str]:
    raw = ev.raw or {}
    related = _related_tickers(raw, ev)
    from_title = tickers_in_title(ev.title or "")
    return list(dict.fromkeys([*related, *from_title]))


def _open_usd_tickers(db: Session) -> set[str]:
    try:
        rows = (
            db.query(Position.ticker)
            .filter(Position.status == PositionStatus.open)
            .all()
        )
    except Exception:
        return set()
    out: set[str] = set()
    for row in rows:
        ticker = row[0] if isinstance(row, tuple) else getattr(row, "ticker", None)
        if ticker:
            out.add(str(ticker).upper())
    return out


def _should_escalate(result: dict, open_tickers: set[str]) -> bool:
    settings = get_settings()
    if not settings.llm_cloud_on_escalate:
        return False
    try:
        confidence = float(result.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    catalyst = str(result.get("catalyst_strength") or "").strip().lower()
    ticker = str(result.get("ticker") or "").strip().upper()
    if confidence < 0.7:
        return True
    if catalyst == "high":
        return True
    if ticker and ticker in open_tickers:
        return True
    return False


def _classify_title(
    title: str,
    related: list[str],
    source: str,
    *,
    escalate: bool = False,
    cloud_only: bool = False,
):
    messages = [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": json.dumps(
                {"headline": title, "related": related, "source": source},
                ensure_ascii=False,
            ),
        },
    ]
    res = chat(
        messages,
        json_mode=True,
        temperature=0.0,
        escalate=escalate,
        cloud_only=cloud_only,
        json_schema=CLASSIFY_SCHEMA,
    )
    parsed = _parse_json(res.content or "") if res.content else None
    return parsed, res


def _stamp_raw(ev: NewsEvent, *, source: str, model: str, escalated: bool) -> None:
    raw = dict(ev.raw or {})
    raw["classifier_source"] = source
    raw["classifier_model"] = model
    raw["escalated"] = bool(escalated)
    raw["prompt_version"] = PROMPT_VERSION
    ev.raw = raw


def _apply_classification(ev: NewsEvent, result: dict, related: list[str]) -> None:
    event_type = str(result.get("event_type") or "").strip().lower()
    sentiment = str(result.get("sentiment") or "").strip().lower()
    try:
        confidence = float(result.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    try:
        impact_score = float(result.get("impact_score") or 0)
    except (TypeError, ValueError):
        impact_score = 0.0
    catalyst = str(result.get("catalyst_strength") or "").strip().lower()
    ticker = str(result.get("ticker") or "").strip().upper()
    if not ticker:
        ticker = related[0] if related else (ev.ticker or "")
    ev.event_type = event_type if _event_type_valid(event_type) else "other"
    ev.sentiment = sentiment if sentiment in {"bullish", "bearish", "neutral"} else None
    ev.confidence = min(1.0, max(0.0, confidence))
    ev.impact_score = min(100.0, max(0.0, impact_score))
    ev.catalyst_strength = catalyst if catalyst in {"high", "medium", "low"} else None
    ev.ticker = ticker or None


def classify_pending(db: Session, *, limit: int | None = None) -> int:
    """Classify unprocessed NewsEvents with the LLM and persist structured fields."""
    settings = get_settings()
    if not local_configured() and not cloud_configured():
        logger.info("LLM unconfigured — skip news classification")
        return 0

    cap = int(limit if limit is not None else settings.news_classify_limit or 20)
    pending = (
        db.query(NewsEvent)
        .filter(NewsEvent.processed_at.is_(None))
        .order_by(NewsEvent.published_at.desc().nullslast(), NewsEvent.created_at.desc())
        .limit(cap)
        .all()
    )
    now = datetime.now(timezone.utc)
    classified = 0
    open_tickers = _open_usd_tickers(db)
    for ev in pending:
        related = resolve_candidate_tickers(ev)
        if not related:
            logger.info("news_skip no_ticker")
            ev.event_type = "other"
            ev.processed_at = now
            _stamp_raw(ev, source="skip", model="", escalated=False)
            classified += 1
            continue

        parsed, res = _classify_title(ev.title, related, ev.source, escalate=False)
        if parsed is None:
            continue
        if not parsed.get("ticker"):
            parsed["ticker"] = related[0]
        need_cloud = _should_escalate(parsed, open_tickers)
        if need_cloud:
            parsed2, res2 = _classify_title(
                ev.title, related, ev.source, cloud_only=True
            )
            if parsed2 is not None:
                parsed, res = parsed2, res2
            else:
                res.escalated = True
        _apply_classification(ev, parsed, related)
        _stamp_raw(
            ev,
            source=res.source,
            model=res.model,
            escalated=bool(need_cloud or res.escalated),
        )
        ev.processed_at = now
        classified += 1

    if classified:
        db.commit()
    logger.info("news classified=%d prompt=%s", classified, PROMPT_VERSION)
    return classified


def active_bullish_events(db: Session, ticker: str, *, hours: int | None = None) -> list[NewsEvent]:
    """Bullish catalyst events for a ticker within the configured window.

    Restricted to event types that have actually beaten the bullish base rate
    under FDR correction, when that has been established. Bullish sentiment plus
    a confidence threshold was the whole gate before, and on the labelled sample
    that gate hits 39.9% — the type is where the signal lives.
    """
    from app.services.learn.news_whitelist import allowed_event_types

    settings = get_settings()
    window_hours = hours if hours is not None else int(settings.news_window_hours)
    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    q = (
        db.query(NewsEvent)
        .filter(NewsEvent.ticker == ticker.upper())
        .filter(NewsEvent.sentiment == "bullish")
        .filter(NewsEvent.confidence >= float(settings.news_confidence_min))
    )
    allowed = allowed_event_types()
    if allowed:
        q = q.filter(NewsEvent.event_type.in_(sorted(allowed)))
    if since is not None:
        q = q.filter(
            (NewsEvent.published_at.is_(None)) | (NewsEvent.published_at >= since)
        )
    return q.order_by(NewsEvent.published_at.desc().nullslast()).all()


def active_recovery_events(db: Session, ticker: str, *, hours: int | None = None) -> list[NewsEvent]:
    """Bullish recovery/restructuring events (turnaround catalysts) in the window."""
    settings = get_settings()
    window_hours = hours if hours is not None else int(settings.news_window_hours)
    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    q = (
        db.query(NewsEvent)
        .filter(NewsEvent.ticker == ticker.upper())
        .filter(NewsEvent.sentiment == "bullish")
        .filter(NewsEvent.event_type.in_(RECOVERY_EVENT_TYPES))
        .filter(NewsEvent.confidence >= float(settings.news_confidence_min))
    )
    if since is not None:
        q = q.filter(
            (NewsEvent.published_at.is_(None)) | (NewsEvent.published_at >= since)
        )
    return q.order_by(NewsEvent.published_at.desc().nullslast()).all()
