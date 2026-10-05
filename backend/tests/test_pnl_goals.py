"""P&L goals: daily 7% target and stretch scorecard helpers."""

from datetime import datetime, timedelta, timezone

from app.services.positions import _period_day_count, _period_start


def test_period_day_count_at_least_one():
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    assert _period_day_count(start) == 1


def test_period_day_count_week():
    start = _period_start("week")
    n = _period_day_count(start)
    assert n >= 1
    assert n <= 7


def test_daily_target_math():
    equity = 100.0
    daily_pct = 7.0
    days = 3
    target = round(equity * (daily_pct / 100.0) * days, 2)
    assert target == 21.0
    progress = round(14.0 / target * 100.0, 1)
    assert progress == 66.7
