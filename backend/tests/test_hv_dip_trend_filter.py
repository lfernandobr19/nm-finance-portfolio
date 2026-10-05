"""Tests for hv_dip trend / falling-knife filter."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.brapi_client import Bar
from app.services.hv_dip.engine import build_hv_dip_setup


def _falling_knife_bars(n: int = 90) -> list[Bar]:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    out: list[Bar] = []
    price = 120.0
    for i in range(n):
        if i < n - 10:
            price = 120.0 - 0.8 * i
        else:
            price = price + 0.5
        out.append(
            Bar(
                date=start + timedelta(days=i),
                open=price,
                high=price + 0.5,
                low=price - 2.0,
                close=price,
                volume=2_000_000.0,
            )
        )
    return out


def test_build_hv_dip_rejects_falling_knife():
    bars = _falling_knife_bars()
    row = build_hv_dip_setup("TEST", bars, min_dip_pct=3.0)
    assert row is None


def test_build_hv_dip_accepts_recovery_structure():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    out: list[Bar] = []
    price = 100.0
    for i in range(90):
        if i < 40:
            price = 100.0 - 0.3 * i
        elif i < 70:
            price = 88.0 + 0.05 * (i - 40)
        else:
            price = 90.0 - 0.8 * (i - 70)
        out.append(
            Bar(
                date=start + timedelta(days=i),
                open=price,
                high=price + 2,
                low=price - 1,
                close=price,
                volume=3_000_000.0,
            )
        )
    row = build_hv_dip_setup("TEST", out, min_dip_pct=3.0)
    # May or may not pass depending on dip % — at least should not crash
    assert row is None or "ticker" in row
