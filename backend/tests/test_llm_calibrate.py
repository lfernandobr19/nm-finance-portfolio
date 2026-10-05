"""News LLM calibration against next-session return."""

from datetime import datetime, timezone

import pytest

from app.services.brapi_client import Bar
from app.services.llm_calibrate import outcome_ok, session_return_after


def _bar(day: str, close: float) -> Bar:
    dt = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
    return Bar(date=dt, open=close, high=close, low=close, close=close, volume=1e6)


def test_bullish_plus_one_pct_is_ok():
    bars = [_bar("2026-09-10", 10.0), _bar("2026-09-11", 10.1)]
    pub = datetime(2026, 9, 10, 18, 0, tzinfo=timezone.utc)
    ret = session_return_after(bars, pub)
    assert ret == pytest.approx(0.01)
    assert outcome_ok("bullish", ret) is True


def test_bearish_positive_return_is_not_ok():
    assert outcome_ok("bearish", 0.02) is False
