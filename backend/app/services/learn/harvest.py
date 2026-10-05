"""Conservative memory writes from loops that already passed a statistical gate.

The store is only as honest as its inputs. These helpers refuse anything that
has not already survived FDR, OOS confirmation, a closed-trade review, or a
grounded insight with evidence. Dedup/conflict live in ``memory.write``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.services.learn import memory as mem
from app.services.studies.apply import DEFAULT_FLOOR, OOS_FLOOR

logger = logging.getLogger("fiidesk.learn.harvest")

STAT_FLOOR = DEFAULT_FLOOR


def _safe_write(**kwargs: Any) -> dict[str, Any] | None:
    """Write a lesson; never raise into a trading/research loop."""
    try:
        return mem.write(**kwargs)
    except Exception:
        logger.exception("memory harvest write failed")
        return None


def harvest_guards(
    guards: dict[str, Any] | None,
    *,
    path: Path | None = None,
) -> int:
    """Persist FDR+OOS suppressed guards as refuted patterns."""
    written = 0
    for key, guard in (guards or {}).items():
        if not isinstance(guard, dict) or not guard.get("force_review"):
            continue
        n = int(guard.get("n") or 0)
        if n < STAT_FLOOR:
            continue
        reason = str(guard.get("reason") or "padrão fraco após FDR")
        p_recover = guard.get("p_recover")
        row = _safe_write(
            kind="pattern",
            scope=str(key),
            text=f"Padrão {key} fraco: {reason}",
            provenance=f"studies:fdr:{key}",
            confidence=0.7,
            n_support=n,
            refuted=True,
            evidence=[
                {
                    "key": key,
                    "p_recover": p_recover,
                    "p_value": guard.get("p_value"),
                    "n": n,
                    "oos_p_recover": guard.get("oos_p_recover"),
                    "oos_n": guard.get("oos_n"),
                }
            ],
            path=path,
        )
        if row:
            written += 1
    return written


def harvest_trade_review(
    pos: Any,
    review: dict[str, Any] | None,
    *,
    path: Path | None = None,
) -> dict[str, Any] | None:
    """Persist the lesson of one closed trade. Provenance is the position id."""
    review = review or {}
    lesson = str(review.get("lesson") or "").strip()
    if not lesson:
        return None
    try:
        confidence = float(review.get("confidence") or 0.4)
    except (TypeError, ValueError):
        confidence = 0.4
    ticker = str(getattr(pos, "ticker", "") or "UNKNOWN")
    kind = getattr(pos, "strategy_kind", None)
    kind_s = kind.value if hasattr(kind, "value") else str(kind or "")
    change = str(review.get("would_change") or "none")
    text = f"{ticker} ({kind_s}): {lesson}"
    if change and change != "none":
        text += f" Ajuste sugerido: {change}."
    return _safe_write(
        kind="trade_review",
        scope=ticker,
        text=text[:500],
        provenance=f"position:{getattr(pos, 'id', '')}",
        confidence=max(0.0, min(1.0, confidence)),
        evidence=[
            {
                "position_id": str(getattr(pos, "id", "")),
                "r_multiple": getattr(pos, "r_multiple_realized", None),
                "reason": str(getattr(pos, "exit_reason", "") or ""),
                "would_change": change,
            }
        ],
        path=path,
    )


def harvest_news(
    report: dict[str, Any] | None,
    *,
    path: Path | None = None,
) -> int:
    """Write only event types that survived FDR. A miss is not a refutation."""
    report = report or {}
    if report.get("status") != "ok":
        return 0
    written = 0
    horizon = report.get("horizon")
    base = report.get("base_rate")
    for item in report.get("types") or []:
        if not isinstance(item, dict) or not item.get("allowed"):
            continue
        n = int(item.get("n") or 0)
        if n < STAT_FLOOR:
            continue
        event_type = str(item.get("event_type") or "")
        if not event_type:
            continue
        row = _safe_write(
            kind="news",
            scope=event_type,
            text=(
                f"{event_type} sobreviveu ao FDR no horizonte {horizon}d: "
                f"hit_rate={item.get('hit_rate')} vs base {base} "
                f"(n={n}, p={item.get('p_value')})."
            ),
            provenance=f"news:fdr:{event_type}:{horizon}d",
            confidence=0.65,
            n_support=n,
            evidence=[{**item, "horizon": horizon, "base_rate": base}],
            path=path,
        )
        if row:
            written += 1
    return written


def harvest_insights(
    insights: list[Any] | None,
    *,
    path: Path | None = None,
) -> int:
    """Persist grounded insights only — text without evidence is dropped."""
    written = 0
    for item in insights or []:
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        evidence = item.get("evidence") or []
        if not text or not evidence:
            continue
        try:
            confidence = float(item.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < 0.4:
            continue
        channel = str(item.get("channel") or "hv_dip")
        ticker = str(item.get("ticker") or "UNIVERSE")
        row = _safe_write(
            kind="pattern",
            scope=f"{channel}:{ticker}",
            text=text[:500],
            provenance=f"insight:{channel}:{ticker}",
            confidence=max(0.0, min(1.0, confidence)),
            evidence=list(evidence)[:8],
            path=path,
        )
        if row:
            written += 1
    return written


def harvest_deep_findings(
    findings: list[dict[str, Any]] | None,
    *,
    path: Path | None = None,
) -> int:
    """Observational memories from a horizon/metric sweep. Never promotes params."""
    written = 0
    for item in findings or []:
        n = int(item.get("n") or 0)
        oos_n = int(item.get("oos_n") or 0)
        if n < STAT_FLOOR or oos_n < OOS_FLOOR:
            continue
        fingerprint = str(item.get("fingerprint") or item.get("query_id") or "unknown")
        horizon = item.get("horizon")
        text = (
            f"{fingerprint} horizonte {horizon}: "
            f"P(alvo)={item.get('p_higher')} recovery={item.get('recovery')} "
            f"gap_hit={item.get('gap_hit')} (n={n}, oos_n={oos_n}, "
            f"oos_p={item.get('oos_p_higher')})."
        )
        row = _safe_write(
            kind="pattern",
            scope=f"{fingerprint}:h{horizon}",
            text=text,
            provenance="research:deep_backtest",
            confidence=0.55,
            n_support=n,
            evidence=[item],
            path=path,
        )
        if row:
            written += 1
    return written


__all__ = [
    "STAT_FLOOR",
    "harvest_guards",
    "harvest_trade_review",
    "harvest_news",
    "harvest_insights",
    "harvest_deep_findings",
]
