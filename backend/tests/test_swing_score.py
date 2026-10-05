"""Unit tests for swing A/B/C scoring and revised trend/breakout rules."""

from datetime import datetime, timedelta, timezone

from app.services.brapi_client import Bar
from app.services.swing.indicators import (
    daily_breakout_long,
    derive_weekly,
    sma,
    trend_context_allows_long,
    weekly_trend_bullish,
)
from app.services.swing.score import SetupSignals, score_setup
from app.services.swing.universe import SWING_UNIVERSE


def _bars(n: int, *, close_slope: float = 0.0, breakout: bool = False) -> list[Bar]:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    out: list[Bar] = []
    price = 100.0
    for i in range(n):
        price = 100.0 + close_slope * i
        high = price + 1
        low = price - 1
        vol = 1_000_000.0
        if breakout and i == n - 1:
            price = price + 5
            high = price + 1
            low = price - 1
            vol = 3_000_000.0
        out.append(
            Bar(
                date=start + timedelta(days=i),
                open=price,
                high=high,
                low=low,
                close=price,
                volume=vol,
            )
        )
    return out


def _downtrend_then_bounce(n: int = 90) -> list[Bar]:
    """Long decline then a short bounce — should NOT pass weekly+context filters."""
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    out: list[Bar] = []
    price = 150.0
    for i in range(n):
        if i < n - 8:
            price = 150.0 - 0.7 * i
        else:
            price = price + 1.5  # late bounce
        out.append(
            Bar(
                date=start + timedelta(days=i),
                open=price,
                high=price + 1,
                low=price - 1,
                close=price,
                volume=1_000_000.0,
            )
        )
    return out


def test_universe_size():
    assert 28 <= len(SWING_UNIVERSE) <= 35
    assert "IVVB11" in SWING_UNIVERSE
    assert "AAPL34" in SWING_UNIVERSE


def test_sma_and_weekly_trend_rising():
    bars = _bars(90, close_slope=0.2)
    weekly = derive_weekly(bars)
    assert len(weekly) >= 12
    assert weekly_trend_bullish(weekly, 10) is True
    assert sma([1, 2, 3, 4], 2) == 3.5


def test_weekly_trend_rejects_dead_cat_bounce():
    bars = _downtrend_then_bounce()
    weekly = derive_weekly(bars)
    assert weekly_trend_bullish(weekly, 10) is False


def test_daily_breakout_uses_recent_window():
    bars = _bars(40, close_slope=0.1, breakout=True)
    ok, level = daily_breakout_long(bars, 10)
    assert ok is True
    assert level is not None
    assert bars[-1].close > level


def test_context_rejects_lower_range_dump():
    bars = _downtrend_then_bounce()
    weekly = derive_weekly(bars)
    ok, detail = trend_context_allows_long(bars, weekly)
    assert ok is False
    assert "baixa" in detail.lower() or "faixa" in detail.lower()


def test_context_allows_upper_range_continuation():
    bars = _bars(90, close_slope=0.25)
    weekly = derive_weekly(bars)
    ok, detail = trend_context_allows_long(bars, weekly)
    assert ok is True


def test_score_a_strong():
    scored = score_setup(
        SetupSignals(
            weekly_bullish=True,
            daily_breakout=True,
            breakout_level=100.0,
            atr_pct=2.5,
            volume_ratio=1.8,
            entry=110.0,
            stop=105.0,
            target=120.0,
        )
    )
    assert scored is not None
    assert scored.letter == "A"
    assert scored.r_multiple == 2.0


def test_score_b_weaker_rr():
    scored = score_setup(
        SetupSignals(
            weekly_bullish=True,
            daily_breakout=True,
            breakout_level=100.0,
            atr_pct=2.0,
            volume_ratio=1.3,
            entry=110.0,
            stop=105.0,
            target=117.5,
        )
    )
    assert scored is not None
    assert scored.letter == "B"


def test_score_c_weak_volume():
    scored = score_setup(
        SetupSignals(
            weekly_bullish=True,
            daily_breakout=True,
            breakout_level=100.0,
            atr_pct=1.0,
            volume_ratio=0.8,
            entry=110.0,
            stop=105.0,
            target=112.0,
        )
    )
    assert scored is not None
    assert scored.letter == "C"


def test_score_none_without_trend():
    assert (
        score_setup(
            SetupSignals(
                weekly_bullish=False,
                daily_breakout=True,
                breakout_level=100.0,
                atr_pct=2.0,
                volume_ratio=1.5,
                entry=110.0,
                stop=105.0,
                target=120.0,
            )
        )
        is None
    )
