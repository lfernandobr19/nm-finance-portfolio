"""Notification content: _factors and notify_order_filled gating (no DB/network)."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.notify import _factors, notify_order_filled


def _sug(catalyst=None, *, score=82.0, letter="A", dip=6.2):
    metrics = {"dip_pct": dip}
    if catalyst is not None:
        metrics["catalyst"] = catalyst
    return SimpleNamespace(
        metrics=metrics,
        swing_score_letter=letter,
        score=score,
    )


def test_factors_with_catalyst():
    s = _sug(
        catalyst={
            "event_type": "partnership",
            "sentiment": "bullish",
            "confidence": 0.88,
            "impact_score": 70,
        }
    )
    text = _factors(s)
    assert "parceria" in text
    assert "bullish" in text
    assert "88%" in text
    assert "score 82" in text
    assert "dip 6.2%" in text


def test_factors_without_catalyst():
    text = _factors(_sug(catalyst=None))
    assert "parceria" not in text
    assert "score 82" in text
    assert "dip 6.2%" in text


def test_factors_handles_missing_metrics():
    s = SimpleNamespace(metrics=None, swing_score_letter=None, score=None)
    assert _factors(s) == ""


def test_notify_order_filled_skips_manual_order():
    order = SimpleNamespace(
        acted_by_user_id="user-1",
        quantity=2.0,
        filled_price=10.0,
        limit_price=10.0,
        suggestion_id="s1",
        account_id="a1",
        ticker="TSLA",
    )
    assert notify_order_filled(None, order, SimpleNamespace(id="p1")) == 0
