"""Tests for news catalyst integration (score bonus + gap filter)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from app.services.brapi_client import Bar
from app.services.hv_dip.engine import _apply_catalysts, mark_thesis_skips
from app.services.hv_dip.score import HvDipScored


def _scored(letter="C", numeric_score=58.0) -> HvDipScored:
    return HvDipScored(
        letter=letter,
        numeric_score=numeric_score,
        r_multiple=1.5,
        reasons=[],
    )


def _event(ticker="AMZN", event_type="partnership", published=None):
    ev = MagicMock()
    ev.ticker = ticker
    ev.event_type = event_type
    ev.sentiment = "bullish"
    ev.confidence = 0.9
    ev.impact_score = 75.0
    ev.title = "Amazon NVIDIA partnership"
    ev.url = "https://example.com/news"
    ev.published_at = published
    return ev


def _bars(close_before_news=100.0) -> list[Bar]:
    now = datetime.now(timezone.utc)
    return [
        Bar(date=now - timedelta(days=2), open=99.0, high=101.0, low=98.0, close=close_before_news, volume=1_000_000),
        Bar(date=now - timedelta(days=1), open=101.0, high=105.0, low=100.0, close=104.0, volume=1_200_000),
    ]


def test_apply_catalysts_bumps_score_and_letter(monkeypatch):
    ev = _event()
    monkeypatch.setattr("app.services.hv_dip.engine._catalyst", lambda db, t: ev)
    scored = _scored(letter="C", numeric_score=58.0)
    candidates = [
        {
            "ticker": "AMZN",
            "rank": 10.0,
            "entry": 102.0,
            "review_required": False,
            "review_reason": None,
            "scored": scored,
        }
    ]
    bars_map = {"AMZN": _bars(close_before_news=100.0)}
    _apply_catalysts(MagicMock(), candidates, bars_map)

    row = candidates[0]
    assert row["rank"] > 10.0
    assert scored.numeric_score > 58.0
    assert scored.letter == "B"  # C bumped to B on catalyst
    assert row["catalyst"]["event_type"] == "partnership"
    assert not row["review_required"]


def test_apply_catalysts_gap_filter_skips_the_setup(monkeypatch):
    ev = _event(published=datetime.now(timezone.utc) - timedelta(hours=1))
    monkeypatch.setattr("app.services.hv_dip.engine._catalyst", lambda db, t: ev)
    scored = _scored(letter="A", numeric_score=90.0)
    candidates = [
        {
            "ticker": "NVDA",
            "rank": 50.0,
            # entry +12% above pre-news close → gap above 5% threshold
            "entry": 112.0,
            "review_required": False,
            "review_reason": None,
            "scored": scored,
        }
    ]
    # pre-news close = 100.0 (last bar before published_at)
    bars_map = {"NVDA": _bars(close_before_news=100.0)}
    _apply_catalysts(MagicMock(), candidates, bars_map)

    row = candidates[0]
    assert row.get("skip_reason") == "news_gap"
    assert not row["review_required"]


def test_apply_catalysts_no_catalyst_leaves_row_unchanged(monkeypatch):
    monkeypatch.setattr("app.services.hv_dip.engine._catalyst", lambda db, t: None)
    scored = _scored(letter="B", numeric_score=72.0)
    candidates = [
        {
            "ticker": "AAPL",
            "rank": 30.0,
            "entry": 150.0,
            "review_required": False,
            "review_reason": None,
            "scored": scored,
        }
    ]
    _apply_catalysts(MagicMock(), candidates, {"AAPL": _bars()})
    row = candidates[0]
    assert "catalyst" not in row
    assert row["rank"] == 30.0
    assert scored.numeric_score == 72.0


def test_52w_without_catalyst_is_skipped():
    rows = [{"ticker": "X", "is_52w_low": True, "catalyst": None}]
    mark_thesis_skips(rows)
    assert rows[0]["skip_reason"] == "low_52w"


def test_52w_with_catalyst_is_not_skipped():
    rows = [{"ticker": "X", "is_52w_low": True, "catalyst": {"event_type": "product_launch"}}]
    mark_thesis_skips(rows)
    assert "skip_reason" not in rows[0]
