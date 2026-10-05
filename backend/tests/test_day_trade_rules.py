"""Unit tests for day trade rules."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.day_trade.bars import IntradayBar
from app.services.day_trade.rules.opening_range_break import evaluate_opening_range_break
from app.services.day_trade.rules.vwap_reclaim import evaluate_vwap_reclaim

_BASE = datetime(2026, 1, 15, 14, 30, tzinfo=timezone.utc)


def _bar(minute: int, o: float, h: float, l: float, c: float, v: float = 1000) -> IntradayBar:
    return IntradayBar(
        ts=_BASE + timedelta(minutes=minute * 5),
        open=o,
        high=h,
        low=l,
        close=c,
        volume=v,
    )


def test_opening_range_break_long() -> None:
    bars = [
        _bar(0, 10, 10.5, 9.8, 10.2, 1000),
        _bar(1, 10.2, 10.6, 10.0, 10.4, 1000),
        _bar(2, 10.4, 10.7, 10.2, 10.5, 1000),
        _bar(3, 10.6, 11.0, 10.6, 10.9, 2000),
    ]
    signal = evaluate_opening_range_break(bars)
    assert signal is not None
    assert signal.side == "long"
    assert signal.rule_id == "opening_range_break"
    assert signal.entry_price == 10.9


def test_opening_range_break_needs_volume() -> None:
    bars = [
        _bar(0, 10, 10.5, 9.8, 10.2, 1000),
        _bar(1, 10.2, 10.6, 10.0, 10.4, 1000),
        _bar(2, 10.4, 10.7, 10.2, 10.5, 1000),
        _bar(3, 10.6, 11.0, 10.6, 10.9, 500),
    ]
    assert evaluate_opening_range_break(bars) is None


def test_vwap_reclaim_long() -> None:
    bars = [
        _bar(0, 100, 101, 99, 99.5, 1000),
        _bar(1, 99.5, 100, 98.5, 99.0, 1000),
        _bar(2, 99.0, 100.5, 98.8, 100.2, 1500),
    ]
    signal = evaluate_vwap_reclaim(bars)
    assert signal is not None
    assert signal.side == "long"
    assert signal.rule_id == "vwap_reclaim"
