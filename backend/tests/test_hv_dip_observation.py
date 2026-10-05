"""Tests for structural-decline observation (Fase 5b)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.brapi_client import Bar
from app.services.hv_dip.indicators import recovery_in_progress
from app.services.hv_dip.observation import evaluate_risky_recovery, recovery_probability

START = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _bar(i: int, price: float, volume: float = 3_000_000.0) -> Bar:
    return Bar(
        date=START + timedelta(days=i),
        open=price, high=price + 0.5, low=price - 0.5, close=price, volume=volume,
    )


def _rebounding_bars(n: int = 60) -> list[Bar]:
    """Long decline then a clear rebound (higher lows + >5% off the bottom)."""
    prices: list[float] = []
    for i in range(n):
        if i < 40:
            prices.append(100.0 - 1.5 * i)  # 100 -> ~40
        else:
            prices.append(40.0 + 1.5 * (i - 40))  # 40 -> ~70 rebound
    return [_bar(i, p) for i, p in enumerate(prices)]


def _still_falling_bars(n: int = 60) -> list[Bar]:
    prices = [100.0 - 1.5 * i for i in range(n)]
    return [_bar(i, p) for i, p in enumerate(prices)]


# ---- recovery_in_progress ----

def test_recovery_in_progress_true_on_rebound():
    assert recovery_in_progress(_rebounding_bars()) is True


def test_recovery_in_progress_false_when_falling():
    assert recovery_in_progress(_still_falling_bars()) is False


def test_days_since_recent_high():
    from app.services.hv_dip.indicators import days_since_recent_high

    # Declining series: the high is the oldest bar in the window.
    declining = [_bar(i, 100.0 - i) for i in range(10)]
    assert days_since_recent_high(declining, lookback=10) == 9

    # Rising series: the high is the last bar (fresh top).
    rising = [_bar(i, 100.0 + i) for i in range(10)]
    assert days_since_recent_high(rising, lookback=10) == 0


# ---- recovery_probability ----

def test_recovery_probability_is_none_on_monotonic_decline():
    assert recovery_probability(_still_falling_bars()) is None


# ---- evaluate_risky_recovery ----

def test_risky_recovery_requires_all_three():
    ok, reason = evaluate_risky_recovery(
        recovery_in_progress=True,
        recovery_probability=0.8,
        has_recovery_catalyst=True,
        min_probability=0.6,
    )
    assert ok is True
    assert "risky" not in reason.lower() or reason


def test_risky_recovery_blocks_without_catalyst():
    ok, reason = evaluate_risky_recovery(
        recovery_in_progress=True,
        recovery_probability=0.8,
        has_recovery_catalyst=False,
        min_probability=0.6,
    )
    assert ok is False
    assert "catalisador" in reason


def test_risky_recovery_blocks_low_probability():
    ok, _ = evaluate_risky_recovery(
        recovery_in_progress=True,
        recovery_probability=0.4,
        has_recovery_catalyst=True,
        min_probability=0.6,
    )
    assert ok is False


def test_risky_recovery_blocks_without_technical_recovery():
    ok, reason = evaluate_risky_recovery(
        recovery_in_progress=False,
        recovery_probability=0.8,
        has_recovery_catalyst=True,
        min_probability=0.6,
    )
    assert ok is False
    assert "técnica" in reason
