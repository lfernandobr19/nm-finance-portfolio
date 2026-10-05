"""Structural-decline observation (Fase 5b): risky-recovery decision logic.

A falling-knife large-cap is never rejected outright: it enters an `observing`
state. The system watches for a confluence of (1) technical recovery,
(2) statistical recovery probability, and (3) a recovery/restructuring news
catalyst. Only when all three align does it emit a "risky recovery A" auto-buy.
"""

from __future__ import annotations

from app.services.brapi_client import Bar
from app.services.hv_dip.indicators import recovery_rate


def recovery_probability(
    daily: list[Bar], *, window: int = 84, swing_pct: float = 8.0
) -> float | None:
    """Prior confidence that a similar dip recovers — historical recovery rate."""
    return recovery_rate(daily, window=window, swing_pct=swing_pct)


def evaluate_risky_recovery(
    *,
    recovery_in_progress: bool,
    recovery_probability: float | None,
    has_recovery_catalyst: bool,
    min_probability: float,
) -> tuple[bool, str]:
    """Decide whether a structural decline qualifies as a 'risky recovery A' buy.

    Returns (decision, reason). All three conditions must hold.
    """
    if not recovery_in_progress:
        return False, "sem recuperação técnica confirmada"
    if recovery_probability is None or recovery_probability < min_probability:
        return (
            False,
            f"probabilidade de recuperação insuficiente ({recovery_probability})",
        )
    if not has_recovery_catalyst:
        return False, "sem catalisador de recuperação (notícia)"
    return True, "recuperação técnica + probabilidade + catalisador de reestruturação"
