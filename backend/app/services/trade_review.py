"""Grounded post-mortem of closed paper trades (LLM never calls the gate)."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.models import NewsEvent, Position, PositionStatus
from app.services.llm_client import chat, cloud_configured, local_configured

logger = logging.getLogger("fiidesk.trade_review")

SYSTEM = (
    "Você revisa um trade JÁ FECHADO. Use APENAS o JSON. Não invente preços. "
    "Retorne JSON: "
    '{"lesson":"uma frase","would_change":"hold|tighter_stop|faster_exit|none",'
    '"confidence":0.0}'
)


class ReviewOut(BaseModel):
    lesson: str = ""
    would_change: str = "none"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


REVIEW_SCHEMA: dict = ReviewOut.model_json_schema()


def _needs_review(pos: Position) -> bool:
    metrics = pos.metrics or {}
    return not isinstance(metrics.get("llm_review"), dict)


def _headlines(db: Session, ticker: str) -> list[str]:
    try:
        rows = (
            db.query(NewsEvent)
            .filter(NewsEvent.ticker == ticker.upper())
            .order_by(NewsEvent.published_at.desc().nullslast())
            .limit(3)
            .all()
        )
    except Exception:
        return []
    return [str(r.title) for r in rows if getattr(r, "title", None)]


def _facts(db: Session, pos: Position) -> dict[str, Any]:
    settings = get_settings()
    kind = pos.strategy_kind.value if hasattr(pos.strategy_kind, "value") else str(pos.strategy_kind)
    reason = pos.exit_reason.value if hasattr(pos.exit_reason, "value") else str(pos.exit_reason or "")
    return {
        "ticker": pos.ticker,
        "kind": kind,
        "entry": float(pos.entry_price),
        "exit": float(pos.exit_price) if pos.exit_price is not None else None,
        "stop": float(pos.stop_price) if pos.stop_price is not None else None,
        "target": float(pos.target_price) if pos.target_price is not None else None,
        "r_multiple": float(pos.r_multiple_realized) if pos.r_multiple_realized is not None else None,
        "reason": reason,
        "hold_days_setting": int(settings.hv_dip_qt_max_hold_days or 3),
        "headlines": _headlines(db, pos.ticker),
    }


def review_closed_positions(db: Session, *, limit: int = 10) -> int:
    """Attach metrics.llm_review on closed positions missing it. Skip if LLM down."""
    if not local_configured() and not cloud_configured():
        logger.info("review_skip unconfigured")
        return 0

    rows = (
        db.query(Position)
        .filter(Position.status == PositionStatus.closed)
        .order_by(Position.closed_at.desc().nullslast())
        .limit(80)
        .all()
    )
    pending = [p for p in rows if _needs_review(p)][:limit]
    if not pending:
        logger.info("review_skip none_closed")
        return 0

    n = 0
    for pos in pending:
        facts = _facts(db, pos)
        try:
            from app.services.learn.memory import prompt_block

            lessons = prompt_block(f"trade {pos.ticker} {facts.get('kind')} {facts.get('reason')}")
            if lessons:
                facts["lessons"] = lessons
        except Exception:
            pass
        res = chat(
            [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
            ],
            json_mode=True,
            temperature=0.0,
            escalate=False,
            json_schema=REVIEW_SCHEMA,
        )
        if not res.content:
            logger.info("review_skip llm_fail %s", pos.ticker)
            continue
        try:
            payload = json.loads(res.content)
        except json.JSONDecodeError:
            start, end = res.content.find("{"), res.content.rfind("}")
            if start < 0 or end <= start:
                continue
            try:
                payload = json.loads(res.content[start : end + 1])
            except json.JSONDecodeError:
                continue
        if not isinstance(payload, dict):
            continue
        metrics = dict(pos.metrics or {})
        metrics["llm_review"] = {
            "lesson": str(payload.get("lesson") or "")[:400],
            "would_change": str(payload.get("would_change") or "none")[:40],
            "confidence": payload.get("confidence"),
            "source": res.source,
            "model": res.model,
        }
        pos.metrics = metrics
        try:
            from app.services.learn.harvest import harvest_trade_review

            harvest_trade_review(pos, metrics["llm_review"])
        except Exception:
            logger.warning("review harvest failed", exc_info=True)
        n += 1
        logger.info("review %s source=%s", pos.ticker, res.source)
    if n:
        db.flush()
    return n


__all__ = ["review_closed_positions"]
