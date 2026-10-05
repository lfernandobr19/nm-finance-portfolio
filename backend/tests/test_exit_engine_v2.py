"""Tests for the Quick Target exit engine (hard stop + small target + time-stop)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.hv_dip.exit_engine import (
    add_business_days,
    evaluate_hv_dip_exit,
    extend_time_review,
    quick_target_prices,
)


def _now():
    return datetime(2026, 8, 28, 20, 0, tzinfo=timezone.utc)


def test_quick_target_prices():
    # stop 5%, target_R 1.0 → target = entry + 1*(entry-stop) = entry + 5%.
    stop, target = quick_target_prices(100.0, target_r=1.0, stop_pct=5.0)
    assert stop == 95.0
    assert target == 105.0


def test_quick_target_prices_uses_settings_defaults():
    from app.config import get_settings

    s = get_settings()
    stop, target = quick_target_prices(100.0)
    assert stop == pytest.approx(100.0 * (1 - s.hv_dip_qt_stop_pct / 100), rel=1e-3)


def test_stop_auto_close():
    ev = evaluate_hv_dip_exit(
        {},
        upnl_pct=-5.0,
        mark=94.0,
        entry=100.0,
        stop=95.0,
        target=105.0,
        opened_at=_now() - timedelta(days=2),
        now=_now(),
    )
    assert ev.price_alert == "stop"
    assert ev.auto_close is True


def test_target_auto_close():
    ev = evaluate_hv_dip_exit(
        {},
        upnl_pct=6.0,
        mark=106.0,
        entry=100.0,
        stop=95.0,
        target=105.0,
        opened_at=_now() - timedelta(days=2),
        now=_now(),
    )
    assert ev.price_alert == "target"
    assert ev.auto_close is True


def test_time_stop_auto_close_at_market():
    deadline = _now() - timedelta(hours=1)
    metrics = {"must_review_by": deadline.isoformat()}
    ev = evaluate_hv_dip_exit(
        metrics,
        upnl_pct=-1.0,
        mark=99.0,
        entry=100.0,
        stop=95.0,
        target=105.0,
        opened_at=_now() - timedelta(days=3),
        now=_now(),
        time_stop=True,
    )
    assert ev.price_alert == "time_stop"
    assert ev.auto_close is True
    assert ev.exit_state == "time_stop"


def test_no_time_stop_by_default_even_past_deadline():
    """Frozen calendar deadline is off by default — the desk holds on price."""
    deadline = _now() - timedelta(hours=1)
    metrics = {"must_review_by": deadline.isoformat()}
    ev = evaluate_hv_dip_exit(
        metrics,
        upnl_pct=-1.0,
        mark=99.0,
        entry=100.0,
        stop=95.0,
        target=105.0,
        opened_at=_now() - timedelta(days=3),
        now=_now(),
    )
    assert ev.price_alert is None
    assert ev.auto_close is False
    assert ev.exit_state == "normal"


def test_no_time_stop_before_deadline():
    deadline = _now() + timedelta(days=1)
    metrics = {"must_review_by": deadline.isoformat()}
    ev = evaluate_hv_dip_exit(
        metrics,
        upnl_pct=-1.0,
        mark=99.0,
        entry=100.0,
        stop=95.0,
        target=105.0,
        opened_at=_now() - timedelta(days=1),
        now=_now(),
    )
    assert ev.price_alert is None
    assert ev.auto_close is False


def test_no_trailing_giveback_anymore():
    # The old LATCHED/PROTECT path is gone: a profitable position with no
    # target/stop/time hit produces no alert even after a giveback.
    metrics = {"peak_unrealized_pct": 10.0, "latched_5": True}
    ev = evaluate_hv_dip_exit(
        metrics,
        upnl_pct=4.0,
        mark=104.0,
        entry=100.0,
        stop=95.0,
        target=200.0,
        opened_at=_now() - timedelta(days=5),
        now=_now(),
    )
    assert ev.price_alert is None
    assert ev.auto_close is False


def test_add_business_days_skips_weekend():
    fri = datetime(2026, 9, 4, 20, 0, tzinfo=timezone.utc)  # Friday
    assert add_business_days(fri, 3) == datetime(2026, 9, 9, 20, 0, tzinfo=timezone.utc)


def test_extend_review_once():
    base = _now() + timedelta(days=1)
    m = extend_time_review({"must_review_by": base.isoformat()})
    assert "time_review_extended_until" in m
    with pytest.raises(ValueError):
        extend_time_review(m)
