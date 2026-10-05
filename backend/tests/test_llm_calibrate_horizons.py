"""News ruler: multi-horizon returns, ATR-scaled neutral band, no look-ahead."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from app.services.brapi_client import Bar
from app.services.llm_calibrate import (
    HORIZONS,
    PRIMARY_HORIZON,
    atr_pct_at,
    forward_returns,
    neutral_band,
    outcome_ok,
    session_return_after,
)

PUB = datetime(2026, 9, 10, 18, 0, tzinfo=timezone.utc)
START = datetime(2026, 9, 10, tzinfo=timezone.utc)


def _bar(day_offset: int, close: float, *, high=None, low=None) -> Bar:
    dt = START + timedelta(days=day_offset)
    return Bar(
        date=dt,
        open=close,
        high=close if high is None else high,
        low=close if low is None else low,
        close=close,
        volume=1e6,
    )


def _series(closes: list[float], *, span: float = 0.0) -> list[Bar]:
    """Bar 0 sits on the publish day; the rest follow it."""
    return [
        _bar(i, c, high=c * (1 + span), low=c * (1 - span))
        for i, c in enumerate(closes)
    ]


def test_returns_are_anchored_on_the_publish_day_close():
    bars = _series([100.0] + [101.0, 102.0, 103.0])
    rets = forward_returns(bars, PUB, horizons=(1, 2, 3))
    assert rets[1] == pytest.approx(0.01)
    assert rets[2] == pytest.approx(0.02)
    assert rets[3] == pytest.approx(0.03)


def test_horizon_beyond_history_stays_none():
    """A two-day-old event must not be scored as if fourteen days had passed."""
    bars = _series([100.0, 101.0, 102.0])
    rets = forward_returns(bars, PUB)
    assert rets[1] == pytest.approx(0.01)
    assert rets[5] is None
    assert rets[14] is None


def test_default_horizons_cover_the_hold_period():
    assert HORIZONS == (1, 5, 14)
    assert PRIMARY_HORIZON == 14  # hv_dip_max_hold_days


def test_session_return_after_is_the_one_day_slice():
    bars = _series([10.0, 10.1])
    assert session_return_after(bars, PUB) == pytest.approx(0.01)


def test_one_day_and_fourteen_day_can_disagree():
    """The whole point of the fix: a pop that fades is not a good bullish call."""
    closes = [100.0, 108.0] + [100.0] * 4 + [92.0] * 9
    rets = forward_returns(_series(closes), PUB)
    assert rets[1] > 0
    assert rets[14] < 0
    assert outcome_ok("bullish", rets[1]) is True
    assert outcome_ok("bullish", rets[14]) is False


def test_atr_uses_only_bars_available_at_publish_time():
    """A band built from the move it judges would excuse every call."""
    history = [
        _bar(-i, 100.0, high=102.0, low=98.0) for i in range(20, 0, -1)
    ]
    on_pub = [_bar(0, 100.0, high=102.0, low=98.0)]
    future_shock = [_bar(i, 100.0, high=200.0, low=10.0) for i in range(1, 15)]

    calm = atr_pct_at(history + on_pub, PUB)
    with_shock = atr_pct_at(history + on_pub + future_shock, PUB)
    assert calm == pytest.approx(with_shock)
    assert calm == pytest.approx(0.04, abs=1e-3)


def test_atr_is_none_without_enough_history():
    assert atr_pct_at(_series([100.0, 101.0]), PUB) is None
    assert atr_pct_at([], PUB) is None


def test_neutral_band_scales_with_volatility_and_time():
    tight = neutral_band(0.01, 1, mult=0.5)
    volatile = neutral_band(0.04, 1, mult=0.5)
    assert volatile > tight

    short = neutral_band(0.04, 1, mult=0.5)
    long = neutral_band(0.04, 14, mult=0.5)
    # sqrt scaling, not linear: dispersion grows with the root of time.
    assert long == pytest.approx(short * math.sqrt(14))
    assert long < short * 14


def test_neutral_band_falls_back_when_atr_is_unknown():
    assert neutral_band(None, 1) > 0
    assert neutral_band(0.0, 1) > 0


def test_neutral_is_judged_against_the_band_not_a_flat_percent():
    band = neutral_band(0.04, 14, mult=0.5)  # ~7.5% for a high-vol name
    # A 3% drift over two weeks in a name that swings 4% a day is unremarkable.
    assert outcome_ok("neutral", 0.03, band=band) is True
    # Under the old flat 1% rule the same call was scored wrong.
    assert outcome_ok("neutral", 0.03, band=0.01) is False
    # A move well past the band is still a miss.
    assert outcome_ok("neutral", 0.30, band=band) is False


def test_directional_labels_ignore_the_band():
    assert outcome_ok("bullish", 0.001, band=0.5) is True
    assert outcome_ok("bearish", 0.02, band=0.5) is False


def test_unjudgeable_inputs_return_none():
    assert outcome_ok("bullish", None) is None
    assert outcome_ok(None, 0.05) is None
    assert forward_returns([], PUB)[1] is None
    assert forward_returns(_series([100.0]), None)[1] is None
