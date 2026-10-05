"""Cheap, idempotent change predicates: turn the learn loops event-driven.

Each ``*_due`` predicate compares a cheap fingerprint (cache mtimes, row counts,
max timestamps) against the last seen value persisted in
``.cache/fiidesk/change_state.json``. A predicate returns True only when the
underlying data changed since the last successful run, so the worker reacts to
new bars/trades/news instead of polling on a fixed clock.

The companion ``mark_*_done`` helpers commit the *current* fingerprint after a
successful run; without them the predicate would stay True forever (e.g. running
learn does not close positions, so the closed-count would not self-settle).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.models import DayTradeBar, NewsEvent, Position, PositionStatus

logger = logging.getLogger("fiidesk.studies.change")

STATE_PATH = Path(".cache/fiidesk/change_state.json")
SNAPSHOT_PATH = Path(".cache/fiidesk/studies.json")
# Propose (LLM) is expensive and deduplicated against known ids: run at most
# once per this many seconds, regardless of data churn.
PROPOSE_FLOOR_SECONDS = 24 * 60 * 60
# Insight (LLM) generation is best-effort: when the LLM is rate-limited or the
# local model times out, retry after this floor instead of waiting for new bars.
INSIGHT_RETRY_FLOOR_SECONDS = 15 * 60
# Once insights exist, regenerate them at most every this many seconds. The bars
# fingerprint is intentionally NOT used as the "changed" signal here: cache
# mtimes change on every re-fetch, so it is too volatile to gate the expensive
# LLM digest reliably.
INSIGHT_REGEN_FLOOR_SECONDS = 60 * 60


# --------------------------------------------------------------------------- #
# State helpers
# --------------------------------------------------------------------------- #
def _load() -> dict[str, Any]:
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


def _changed(key: str, fp: Any) -> bool:
    return _load().get(key) != fp


def _commit(key: str, fp: Any) -> None:
    state = _load()
    state[key] = fp
    _save(state)


# --------------------------------------------------------------------------- #
# Studies: bars cache changed
# --------------------------------------------------------------------------- #
def _bars_fingerprint() -> dict[str, Any]:
    """Sum of (mtime, count) per cache dir — one cheap, deterministic digest."""
    settings = get_settings()
    out: dict[str, Any] = {}
    for label, raw in (
        ("market", settings.hv_dip_cache_dir),
        ("brapi", settings.swing_cache_dir),
    ):
        d = Path(raw)
        if not d.exists():
            out[label] = {"n": 0, "mtime": 0.0}
            continue
        n = 0
        mtime = 0.0
        for p in d.glob("*.json"):
            try:
                mtime += p.stat().st_mtime
                n += 1
            except OSError:
                continue
        out[label] = {"n": n, "mtime": round(mtime, 3)}
    return out


def _day_trade_max_ts(db: Session) -> str | None:
    try:
        mx = db.query(func.max(DayTradeBar.ts)).scalar()
    except Exception:
        return None
    return mx.isoformat() if mx is not None else None


def studies_fingerprint(db: Session) -> dict[str, Any]:
    return {"bars": _bars_fingerprint(), "day_trade_max_ts": _day_trade_max_ts(db)}


def studies_due(db: Session) -> bool:
    return _changed("studies", studies_fingerprint(db))


def mark_studies_done(db: Session) -> None:
    _commit("studies", studies_fingerprint(db))


# --------------------------------------------------------------------------- #
# Learn: closed-trade counts changed per strategy
# --------------------------------------------------------------------------- #
def _closed_counts(db: Session) -> dict[str, int]:
    rows = (
        db.query(Position.strategy_kind, func.count())
        .filter(Position.status == PositionStatus.closed)
        .group_by(Position.strategy_kind)
        .all()
    )
    out: dict[str, int] = {}
    for kind, n in rows:
        key = getattr(kind, "value", str(kind))
        out[key] = int(n)
    return out


def learn_fingerprint(db: Session) -> dict[str, int]:
    return _closed_counts(db)


def learn_due(db: Session, kind: str) -> bool:
    prev = _load().get("learn", {}).get(kind)
    cur = _closed_counts(db).get(kind, 0)
    return prev != cur


def mark_learn_done(db: Session) -> None:
    state = _load()
    state["learn"] = _closed_counts(db)
    _save(state)


# --------------------------------------------------------------------------- #
# Calibrate: classified news ≥1 session old lacking a resolved outcome
# --------------------------------------------------------------------------- #
def _calibrate_pending(db: Session) -> int:
    """Mirror calibrate_news_outcomes' 20h cutoff so the predicate tracks the
    same "now calibratable" set — not the whole never-ending processed backlog."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=20)
    try:
        n = (
            db.query(func.count())
            .select_from(NewsEvent)
            .filter(NewsEvent.processed_at.is_not(None))
            .filter(NewsEvent.processed_at <= cutoff)
            .filter(NewsEvent.raw["outcome_ret_1d"].is_(None))
            .scalar()
        )
    except Exception:
        return 0
    return int(n or 0)


def calibrate_fingerprint(db: Session) -> int:
    return _calibrate_pending(db)


def calibrate_due(db: Session) -> bool:
    return _changed("calibrate", _calibrate_pending(db))


def mark_calibrate_done(db: Session) -> None:
    _commit("calibrate", _calibrate_pending(db))


# --------------------------------------------------------------------------- #
# Review: closed positions missing metrics.llm_review
# --------------------------------------------------------------------------- #
def _review_pending(db: Session) -> int:
    try:
        n = (
            db.query(func.count())
            .select_from(Position)
            .filter(Position.status == PositionStatus.closed)
            .filter(Position.metrics["llm_review"].is_(None))
            .scalar()
        )
    except Exception:
        return 0
    return int(n or 0)


def review_fingerprint(db: Session) -> int:
    return _review_pending(db)


def review_due(db: Session) -> bool:
    return _changed("review", _review_pending(db))


def mark_review_done(db: Session) -> None:
    _commit("review", _review_pending(db))


# --------------------------------------------------------------------------- #
# Propose: time-floor (LLM cost gate)
# --------------------------------------------------------------------------- #
def propose_due() -> bool:
    last = _load().get("propose_ts")
    if not isinstance(last, (int, float)):
        return True
    return (time.time() - float(last)) >= PROPOSE_FLOOR_SECONDS


def mark_propose_done() -> None:
    _commit("propose_ts", time.time())


# --------------------------------------------------------------------------- #
# Insights: purely time-gated (retry floor when empty, regen floor when present)
# --------------------------------------------------------------------------- #
def insights_due(db: Session) -> bool:
    """True when insight generation should run.

    Time-gated only: retry after ``INSIGHT_RETRY_FLOOR_SECONDS`` when the
    snapshot has results but no insights yet, and regenerate after
    ``INSIGHT_REGEN_FLOOR_SECONDS`` when insights already exist. (``db`` is
    unused — kept for a stable call signature.)
    """
    try:
        data = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict) or not data.get("results"):
        return False
    last = _load().get("insights_attempt_ts")
    now = time.time()
    if not isinstance(last, (int, float)):
        return True  # never attempted
    floor = (
        INSIGHT_REGEN_FLOOR_SECONDS
        if data.get("insights")
        else INSIGHT_RETRY_FLOOR_SECONDS
    )
    return now - float(last) >= floor


def mark_insights_attempted(db: Session) -> None:
    """Record the timestamp of an insight attempt (success or failure), so the
    next ``insights_due`` respects the retry/regen floors."""
    state = _load()
    state["insights_attempt_ts"] = time.time()
    state.pop("insights_fp", None)
    _save(state)


__all__ = [
    "STATE_PATH",
    "PROPOSE_FLOOR_SECONDS",
    "INSIGHT_RETRY_FLOOR_SECONDS",
    "INSIGHT_REGEN_FLOOR_SECONDS",
    "studies_fingerprint",
    "studies_due",
    "mark_studies_done",
    "learn_fingerprint",
    "learn_due",
    "mark_learn_done",
    "calibrate_fingerprint",
    "calibrate_due",
    "mark_calibrate_done",
    "review_fingerprint",
    "review_due",
    "mark_review_done",
    "propose_due",
    "mark_propose_done",
    "insights_due",
    "mark_insights_attempted",
]
