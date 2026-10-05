"""Which news event types have demonstrated an edge — measured, not assumed.

The shipped whitelist (``partnership, guidance_up, upgrade, m_and_a, contract,
product_launch``) was chosen because those words *sound* bullish. On the labelled
sample ``guidance_up`` lands at 28.9% against a 39.9% base rate: it is worse than
taking any bullish headline at all.

Roughly a dozen event types are tested at once, so an uncorrected "this one looks
good" is expected to appear by chance. Each type is therefore tested against the
observed base rate with an exact binomial and the family is passed through
Benjamini-Hochberg before anything is allowed to influence trading.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.domain.models import NewsEvent
from app.services.llm_calibrate import HORIZONS
from app.services.stats import benjamini_hochberg, binomial_test_greater

logger = logging.getLogger("fiidesk.learn.news_whitelist")

_PATH = Path(".cache/fiidesk/news_whitelist.json")

# A type needs its own sample before it can earn a place.
MIN_TYPE_N = 20
# The family floor is not "enough to estimate a base rate" but "enough for the
# per-type tests to have any power". The sample splits across roughly a dozen
# types, so a few hundred rows leaves every type at n≈30 and nothing can be
# distinguished from noise.
MIN_TOTAL_N = 800
FDR_ALPHA = 0.10


def _load() -> dict[str, Any]:
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _outcome_at(raw: dict[str, Any], horizon: int) -> bool | None:
    value = raw.get(f"outcome_ok_{horizon}d")
    return None if value is None else bool(value)


def _best_horizon(rows: list[tuple[dict[str, Any], str]]) -> int | None:
    """Longest horizon with enough labelled outcomes to judge.

    Prefers 14 days because that is what the strategy holds, and falls back only
    when the corpus is too young for it to have landed.
    """
    for horizon in sorted(HORIZONS, reverse=True):
        n = sum(1 for raw, _ in rows if _outcome_at(raw, horizon) is not None)
        if n >= MIN_TOTAL_N:
            return horizon
    return None


def compute_whitelist(
    db: Session,
    *,
    alpha: float = FDR_ALPHA,
    min_type_n: int = MIN_TYPE_N,
    confidence_min: float = 0.7,
) -> dict[str, Any]:
    """Event types that beat the bullish base rate and survive FDR correction."""
    events = (
        db.query(NewsEvent)
        .filter(NewsEvent.sentiment == "bullish")
        .filter(NewsEvent.confidence >= confidence_min)
        .all()
    )
    rows = [
        (dict(ev.raw or {}), str(ev.event_type or "other"))
        for ev in events
    ]
    horizon = _best_horizon(rows)
    if horizon is None:
        return {
            "status": "insufficient_data",
            "allowed": [],
            "horizon": None,
            "n": sum(1 for raw, _ in rows if _outcome_at(raw, 1) is not None),
            "ts": datetime.now(timezone.utc).isoformat(),
        }

    graded = [(t, _outcome_at(raw, horizon)) for raw, t in rows]
    graded = [(t, ok) for t, ok in graded if ok is not None]
    total_n = len(graded)
    total_hits = sum(1 for _, ok in graded if ok)
    base_rate = total_hits / total_n if total_n else 0.0

    by_type: dict[str, list[bool]] = {}
    for t, ok in graded:
        by_type.setdefault(t, []).append(ok)

    testable = [(t, v) for t, v in by_type.items() if len(v) >= min_type_n]
    p_values = [
        binomial_test_greater(sum(1 for x in v if x), len(v), base_rate)
        for _, v in testable
    ]
    mask = benjamini_hochberg(p_values, alpha=alpha)

    types: list[dict[str, Any]] = []
    allowed: list[str] = []
    for (t, v), p, survived in zip(testable, p_values, mask):
        hits = sum(1 for x in v if x)
        types.append({
            "event_type": t,
            "n": len(v),
            "hits": hits,
            "hit_rate": round(hits / len(v), 4),
            "p_value": round(p, 6),
            "allowed": bool(survived),
        })
        if survived:
            allowed.append(t)
    types.sort(key=lambda x: -x["hit_rate"])

    return {
        "status": "ok",
        "allowed": sorted(allowed),
        "horizon": horizon,
        "base_rate": round(base_rate, 4),
        "n": total_n,
        "alpha": alpha,
        "n_tested": len(testable),
        "types": types,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


def refresh_whitelist(db: Session, **kwargs: Any) -> dict[str, Any]:
    report = compute_whitelist(db, **kwargs)
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info(
        "news whitelist status=%s horizon=%s allowed=%s base=%s n=%s",
        report.get("status"),
        report.get("horizon"),
        report.get("allowed"),
        report.get("base_rate"),
        report.get("n"),
    )
    return report


def read_whitelist() -> dict[str, Any]:
    return _load()


def allowed_event_types() -> set[str] | None:
    """Types cleared to act as catalysts, or ``None`` to apply no filter.

    ``None`` when nothing has been demonstrated yet — either too little data or
    no type surviving correction. Blocking every catalyst in that case would
    stop the loop that produces the very evidence needed to decide, which is the
    opposite of learning.
    """
    report = _load()
    allowed = report.get("allowed") or []
    if report.get("status") != "ok" or not allowed:
        return None
    return {str(t) for t in allowed}


__all__ = [
    "MIN_TYPE_N",
    "MIN_TOTAL_N",
    "FDR_ALPHA",
    "compute_whitelist",
    "refresh_whitelist",
    "read_whitelist",
    "allowed_event_types",
]
