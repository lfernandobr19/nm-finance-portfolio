"""Score A/B/C for swing setups (playbook Option 1)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SetupSignals:
    weekly_bullish: bool
    daily_breakout: bool
    breakout_level: float | None
    atr_pct: float | None
    volume_ratio: float | None
    entry: float
    stop: float
    target: float


@dataclass
class ScoredSetup:
    letter: str  # A | B | C
    numeric_score: float
    r_multiple: float
    reasons: list[dict]
    risk_pct_hint: float  # suggested account risk %


def _r_multiple(entry: float, stop: float, target: float) -> float:
    risk = entry - stop
    if risk <= 0:
        return 0.0
    return (target - entry) / risk


def score_setup(sig: SetupSignals) -> ScoredSetup | None:
    """Return scored setup or None if no tradeable structure."""
    if not sig.weekly_bullish or not sig.daily_breakout:
        return None
    if sig.entry <= 0 or sig.stop <= 0 or sig.target <= 0:
        return None
    if sig.stop >= sig.entry:
        return None

    rr = _r_multiple(sig.entry, sig.stop, sig.target)
    vol = sig.volume_ratio or 0.0
    volume_ok = vol >= 1.2
    volume_strong = vol >= 1.5
    rr_a = rr >= 2.0
    rr_b = rr >= 1.5

    reasons: list[dict] = [
        {
            "rule": "weekly_trend",
            "passed": True,
            "detail": "Close > SMA10 semanal e SMA em alta (evita rebound em queda longa)",
        },
        {
            "rule": "daily_breakout",
            "passed": True,
            "detail": f"Rompimento recente (10 pregões) acima de {sig.breakout_level:.2f}"
            if sig.breakout_level
            else "Rompimento diário recente (10 pregões)",
        },
        {
            "rule": "volume",
            "passed": volume_ok,
            "detail": f"Volume / SMA20 = {vol:.2f}",
        },
        {
            "rule": "r_multiple",
            "passed": rr_b,
            "detail": f"R:R = {rr:.2f}",
        },
        {
            "rule": "atr_pct",
            "passed": (sig.atr_pct or 0) > 0,
            "detail": f"ATR% = {sig.atr_pct:.2f}" if sig.atr_pct is not None else "ATR% n/d",
        },
    ]

    if volume_strong and rr_a:
        return ScoredSetup(
            letter="A",
            numeric_score=90.0,
            r_multiple=rr,
            reasons=reasons,
            risk_pct_hint=1.5,
        )
    if volume_ok and rr_a:
        return ScoredSetup(
            letter="A",
            numeric_score=85.0,
            r_multiple=rr,
            reasons=reasons,
            risk_pct_hint=1.25,
        )
    if volume_ok and rr_b:
        return ScoredSetup(
            letter="B",
            numeric_score=75.0,
            r_multiple=rr,
            reasons=reasons,
            risk_pct_hint=1.0,
        )
    if rr_b or volume_ok:
        return ScoredSetup(
            letter="B",
            numeric_score=68.0,
            r_multiple=rr,
            reasons=reasons,
            risk_pct_hint=0.75,
        )
    # Weak but still a breakout in weekly favor → C (paper only)
    return ScoredSetup(
        letter="C",
        numeric_score=55.0,
        r_multiple=rr,
        reasons=reasons,
        risk_pct_hint=0.0,
    )


def rank_key(scored: ScoredSetup, atr_pct: float | None, volume_ratio: float | None) -> float:
    """Higher is better for Top-N ranking (ATR% + volume + letter)."""
    letter_bonus = {"A": 30.0, "B": 15.0, "C": 0.0}.get(scored.letter, 0.0)
    return letter_bonus + (atr_pct or 0.0) + 5.0 * (volume_ratio or 0.0)
