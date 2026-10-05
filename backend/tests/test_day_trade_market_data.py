"""Tests for DXLink candle parsing (NaN filter)."""

import math

from app.services.tastytrade_market_data import candle_to_bar


def test_candle_to_bar_rejects_nan():
    assert candle_to_bar({"time": 1_700_000_000_000, "open": float("nan"), "high": 1, "low": 1, "close": 1}) is None


def test_candle_to_bar_rejects_zero():
    assert candle_to_bar({"time": 1_700_000_000_000, "open": 0, "high": 1, "low": 1, "close": 1}) is None


def test_candle_to_bar_accepts_valid():
    bar = candle_to_bar(
        {
            "time": 1_700_000_000_000,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1000,
        }
    )
    assert bar is not None
    assert math.isclose(bar.close, 100.5)
