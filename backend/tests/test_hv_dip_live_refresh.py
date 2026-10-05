"""Tests for hv_dip live refresh of pending suggestions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.brapi_client import Bar
from app.services.hv_dip.engine import build_hv_dip_setup
from app.services.hv_dip.indicators import dip_pct_from_high
from app.services.hv_dip.live_refresh import recompute_live_dip


def _bars(closes: list[float]) -> list[Bar]:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    out: list[Bar] = []
    for i, c in enumerate(closes):
        out.append(
            Bar(
                date=base + timedelta(days=i),
                open=c,
                high=c * 1.02,
                low=c * 0.98,
                close=c,
                volume=3_000_000.0,
            )
        )
    return out


def _recovering_dip_closes() -> list[float]:
    """Sub-$20 recovery setup: decline 12 -> 7, rally 7 -> 11, fresh 11 -> 9.5 dip."""
    closes: list[float] = []
    for i in range(50):
        closes.append(12.0 - 5.0 * (i + 1) / 50)
    for j in range(30):
        closes.append(7.0 + 4.0 * (j + 1) / 30)
    for k in range(10):
        closes.append(11.0 - 1.5 * (k + 1) / 10)
    return closes


def test_recompute_live_dip_drops_when_price_recovers():
    bars = _bars([100.0] * 9 + [90.0])
    dip_stale = dip_pct_from_high(bars, 10)
    assert dip_stale is not None and dip_stale >= 9.0
    dip_live = recompute_live_dip(bars, 96.0, 10)
    assert dip_live is not None and dip_live < 6.0


def test_recompute_live_dip_keeps_valid_dip():
    bars = _bars([100.0] * 9 + [88.0])
    dip_live = recompute_live_dip(bars, 88.5, 10)
    assert dip_live is not None and dip_live >= 10.0


def test_build_hv_dip_setup_with_live_price_updates_entry():
    closes = _recovering_dip_closes()
    bars = _bars(closes)
    stale = build_hv_dip_setup("TEST", bars, min_dip_pct=3.0)
    assert stale is not None
    assert stale["entry"] == 9.5
    live = build_hv_dip_setup("TEST", bars, last_price=9.0, min_dip_pct=3.0)
    assert live is not None
    assert live["entry"] == 9.0
    assert live["dip_pct"] >= 12.0


def test_build_hv_dip_setup_invalid_when_dip_too_small_live():
    closes = _recovering_dip_closes()  # entry 9.5, dip ~14%
    bars = _bars(closes)
    # Live price recovers toward the recent high, shrinking the dip below 6%.
    assert build_hv_dip_setup("TEST", bars, last_price=10.7, min_dip_pct=6.0) is None
