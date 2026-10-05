"""Tests for hv_dip mean-reversion / quality / fresh-high alignment (Fase 5)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.brapi_client import Bar
from app.services.hv_dip.engine import build_hv_dip_setup
from app.services.hv_dip.indicators import (
    is_fresh_high,
    quality_tier,
    recovery_rate,
)
from app.services.hv_dip.score import HvDipSignals, score_hv_dip

START = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _bar(i: int, price: float, volume: float = 3_000_000.0) -> Bar:
    return Bar(
        date=START + timedelta(days=i),
        open=price,
        high=price + 0.5,
        low=price - 0.5,
        close=price,
        volume=volume,
    )


def _oscillator_bars(n: int = 90) -> list[Bar]:
    """Repeating 10 -> 9.2 -> 10 cycle (8% dips that always recover), then a final
    10 -> 8.2 decline as the current dip."""
    out: list[Bar] = []
    for i in range(n):
        if i >= n - 10:
            price = 10.0 - 0.2 * (i - (n - 10))
        else:
            phase = i % 10
            if phase < 5:
                price = 10.0 - 0.2 * phase
            else:
                price = 9.2 + 0.2 * (phase - 5)
        out.append(_bar(i, price))
    return out


def _rising_bars(n: int = 100) -> list[Bar]:
    out: list[Bar] = []
    price = 5.0
    for i in range(n):
        price += 0.05
        out.append(_bar(i, price))
    return out


def _fresh_high_then_dip_bars(n: int = 90) -> list[Bar]:
    """Prior ~10, then a new 4-month high (~11.5) and an immediate dip."""
    out: list[Bar] = []
    for i in range(n):
        if i < 80:
            price = 10.0 + 0.05 * (i % 4)
        elif i < 85:
            price = 10.0 + 0.3 * (i - 79)
        else:
            price = 11.5 - 0.3 * (i - 84)
        out.append(_bar(i, price))
    return out


def _recovering_dip_bars(n: int = 90) -> list[Bar]:
    """Deep decline 12 -> 7 (older trough), rally 7 -> 11, then a fresh 11 -> 9.5 dip.

    Satisfies both gates at once: the recent 11 -> 9.5 dip lands inside the
    lookback window (dip gate), and the recent trough (~9) sits above the older
    trough (~7), so `higher_lows_recent` / `recovery_in_progress` confirm recovery.
    """
    out: list[Bar] = []
    for i in range(50):  # decline 12 -> 7
        px = 12.0 - 5.0 * (i + 1) / 50
        out.append(_bar(i, px))
    for j in range(30):  # rally 7 -> 11
        px = 7.0 + 4.0 * (j + 1) / 30
        out.append(_bar(50 + j, px))
    for k in range(10):  # fresh dip 11 -> 9.5
        px = 11.0 - 1.5 * (k + 1) / 10
        out.append(_bar(80 + k, px))
    return out


# ---- recovery_rate (mean-reversion) ----

def test_recovery_rate_oscillator_recovers():
    rate = recovery_rate(_oscillator_bars(), window=84, swing_pct=8.0)
    assert rate is not None
    assert rate >= 0.8


def test_recovery_rate_only_rises_is_none():
    rate = recovery_rate(_rising_bars(), window=84, swing_pct=8.0)
    assert rate is None


# ---- quality tier ----

def test_quality_tier_buckets():
    args = dict(min_dollar_volume=20_000_000.0, mega_dollar_volume=200_000_000.0)
    assert quality_tier(500_000_000.0, price=100.0, **args) == "mega"
    assert quality_tier(50_000_000.0, price=100.0, **args) == "large"
    assert quality_tier(5_000_000.0, price=100.0, **args) == "micro"
    assert quality_tier(None, price=100.0, **args) == "mid"
    # Liquid sub-$5 is a large-cap, not a penny stock (e.g. LCID).
    assert quality_tier(500_000_000.0, price=3.0, **args) == "mega"
    assert quality_tier(50_000_000.0, price=3.0, **args) == "large"
    # Sub-$5 AND illiquid is the real penny-stock rejection.
    assert quality_tier(5_000_000.0, price=3.0, **args) == "micro"
    assert quality_tier(None, price=3.0, **args) == "micro"


# ---- fresh high (avoid new tops) ----

def test_is_fresh_high_true():
    bars = _fresh_high_then_dip_bars()
    assert is_fresh_high(bars, window=84, recent_lookback=10) is True


def test_is_fresh_high_false_when_below_prior_high():
    bars = _oscillator_bars()
    assert is_fresh_high(bars, window=84, recent_lookback=10) is False


# ---- scoring: deep dip + quality + recovery ----

def test_score_deep_dip_mega_is_strong_a():
    scored = score_hv_dip(
        HvDipSignals(
            dip_pct=25.0,
            atr_pct=5.0,
            volume_ratio=2.0,
            entry=100.0,
            stop=88.0,
            target=124.0,
            recovery_rate=0.9,
            quality_tier="mega",
        )
    )
    assert scored is not None
    assert scored.letter == "A"
    assert scored.numeric_score >= 95.0


def test_score_quality_bonus_prefers_mega():
    base = dict(
        dip_pct=12.0, atr_pct=4.0, volume_ratio=1.2,
        entry=100.0, stop=88.0, target=124.0, recovery_rate=0.8,
    )
    mid = score_hv_dip(HvDipSignals(quality_tier="mid", **base))
    mega = score_hv_dip(HvDipSignals(quality_tier="mega", **base))
    assert mid is not None and mega is not None
    assert mega.numeric_score > mid.numeric_score


def test_score_low_recovery_demotes_to_c():
    scored = score_hv_dip(
        HvDipSignals(
            dip_pct=15.0,
            atr_pct=5.0,
            volume_ratio=1.5,
            entry=90.0,
            stop=80.0,
            target=110.0,
            recovery_rate=0.3,
            quality_tier="large",
        )
    )
    assert scored is not None
    assert scored.letter == "C"


# ---- engine: quality rejection + recovery gate ----

def test_build_rejects_micro_cap():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    out: list[Bar] = []
    for i in range(90):
        if i < 80:
            price = 10.0 + 0.05 * (i % 4)
        else:
            price = 10.0 - 0.15 * (i - 79)
        out.append(
            Bar(
                date=start + timedelta(days=i),
                open=price, high=price + 0.1, low=price - 0.1,
                close=price, volume=1_000.0,
            )
        )
    row = build_hv_dip_setup("TEST", out, min_dip_pct=3.0)
    assert row is None  # micro liquidity rejected


def test_build_fresh_high_without_recovery_rejected():
    """A fresh top followed by an immediate fall has no recovery confirmation,
    so the hard recovery gate rejects it (the old 'review' path is gone)."""
    bars = _fresh_high_then_dip_bars()
    row = build_hv_dip_setup("TEST", bars, min_dip_pct=3.0)
    assert row is None


def test_build_recovering_dip_accepted():
    """A dip with a higher-low recovery structure passes the hard gate."""
    bars = _recovering_dip_bars()
    row = build_hv_dip_setup("TEST", bars, min_dip_pct=3.0)
    assert row is not None
    # The hard recovery gate was satisfied via the rebound signal.
    assert row["recovery_in_progress"] is True
    assert row["higher_lows_recent"] is True


def test_build_deep_dip_quick_target():
    """Quick Target: the target is small and fixed (target_R × risk), regardless
    of dip depth — the old "deeper dip → bigger recovery target" is gone."""
    from app.config import get_settings

    bars = _recovering_dip_bars()
    row = build_hv_dip_setup("TEST", bars, min_dip_pct=3.0)
    assert row is not None
    entry = float(row["entry"])
    s = get_settings()
    expected_target = round(entry + s.hv_dip_qt_target_r * (entry - row["stop"]), 2)
    assert row["target"] == pytest.approx(expected_target)
    # Small target: ~entry × (1 + target_R × stop_pct/100), not a 24–50% gap.
    assert row["target"] <= entry * 1.10
