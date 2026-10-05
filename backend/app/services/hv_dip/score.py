"""Score High-Vol Dip setups A/B/C (mean-reversion, deep dip, quality aware)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings


@dataclass
class HvDipSignals:
    dip_pct: float
    atr_pct: float | None
    volume_ratio: float | None
    entry: float
    stop: float
    target: float
    review_required: bool = False
    review_reason: str | None = None
    recovery_rate: float | None = None
    quality_tier: str = "mid"
    is_fresh_high: bool = False
    # Threshold in force for this evaluation. None falls back to settings so the
    # engine and the scorer can never disagree when the learn loop tunes it.
    min_recovery_rate: float | None = None


@dataclass
class HvDipScored:
    letter: str
    numeric_score: float
    r_multiple: float
    reasons: list[dict[str, Any]] = field(default_factory=list)


def score_hv_dip(sig: HvDipSignals) -> HvDipScored | None:
    risk = sig.entry - sig.stop
    if risk <= 0:
        return None
    reward = sig.target - sig.entry
    r_mult = reward / risk if risk else 0.0

    settings = get_settings()
    dip = float(sig.dip_pct or 0.0)
    atr = sig.atr_pct or 0.0
    volr = sig.volume_ratio or 0.0
    tier = sig.quality_tier or "mid"
    recovery = sig.recovery_rate
    min_recovery = float(
        sig.min_recovery_rate
        if sig.min_recovery_rate is not None
        else (settings.hv_dip_min_recovery_rate or 0.6)
    )
    quality_bonus = (
        float(settings.hv_dip_quality_bonus or 5.0)
        if tier in ("mega", "large")
        else 0.0
    )

    atr_ok = atr >= 2.5
    vol_ok = volr >= 1.0
    # A name that historically recovers from similar dips is a genuine
    # mean-reversion candidate; no history (None) is treated neutrally here
    # because the engine enforces the recovery requirement upstream.
    recovery_ok = recovery is None or recovery >= min_recovery

    reasons: list[dict[str, Any]] = [
        {
            "rule": "dip_depth",
            "passed": dip >= 6.0,
            "detail": f"Dip {dip:.1f}% vs máxima recente",
        },
        {
            "rule": "volume",
            "passed": bool(vol_ok),
            "detail": f"Vol/SMA20={sig.volume_ratio}",
        },
        {
            "rule": "atr",
            "passed": bool(atr_ok),
            "detail": f"ATR%={sig.atr_pct}",
        },
        {
            "rule": "quality",
            "passed": tier in ("mega", "large"),
            "detail": f"{tier}-cap",
        },
        {
            "rule": "recovery",
            "passed": bool(recovery_ok),
            "detail": (
                f"recovery_rate={recovery:.2f}"
                if recovery is not None
                else "recovery_rate=na"
            ),
        },
    ]

    if sig.review_required:
        letter = "C"
        score = 55.0
        reasons.append(
            {
                "rule": "review",
                "passed": False,
                "detail": sig.review_reason or "Review humana obrigatória",
            }
        )
    elif recovery_ok and dip >= 8.0 and atr_ok and vol_ok and r_mult >= 1.5:
        letter = "A"
        # Continuous deep-dip weighting: bigger dips score higher.
        score = 88.0 + min(dip, 25.0) * 0.5 + quality_bonus
    elif recovery_ok and dip >= 6.0:
        letter = "B"
        score = 72.0 + min(dip, 15.0) * 0.6 + quality_bonus
    else:
        letter = "C"
        score = 58.0 + quality_bonus

    if sig.is_fresh_high:
        score -= 8.0
        reasons.append(
            {
                "rule": "fresh_high",
                "passed": False,
                "detail": "Topo novo de ~4 meses (evitar comprar em alta)",
            }
        )

    return HvDipScored(
        letter=letter,
        numeric_score=round(min(max(score, 0.0), 99.0), 1),
        r_multiple=round(r_mult, 2),
        reasons=reasons,
    )


def rank_key(scored: HvDipScored, atr_pct: float | None, dip_pct: float) -> float:
    letter_bonus = {"A": 30.0, "B": 15.0, "C": 0.0}.get(scored.letter, 0.0)
    return letter_bonus + (atr_pct or 0.0) * 2.0 + dip_pct
