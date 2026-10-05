"""Tests for the new desktop intelligence endpoints (read-only surfaces)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.schemas import (
    DayTradeRegimeOut,
    DayTradeStateOut,
    HvDipConfigHistoryOut,
    HvDipConfigOut,
    HvDipObservationOut,
    NewsEventOut,
)

NOW = datetime.now(timezone.utc)


def test_hv_dip_observation_from_attributes():
    row = SimpleNamespace(
        ticker="INTC",
        status="observing",
        recovery_probability=0.6123456,
        recovery_in_progress=True,
        active_catalyst=False,
        last_decision="observing",
        note="queda estrutural",
        first_seen_at=NOW,
        last_evaluated_at=NOW,
        updated_at=NOW,
    )
    out = HvDipObservationOut.model_validate(row)
    assert out.ticker == "INTC"
    assert out.model_dump()["recovery_probability"] == 0.6123  # rounded to 4 dp
    assert out.recovery_in_progress is True
    assert out.active_catalyst is False


def test_hv_dip_observation_nulls():
    out = HvDipObservationOut.model_validate(
        SimpleNamespace(
            ticker="AMD",
            status="observing",
            recovery_probability=None,
            recovery_in_progress=False,
            active_catalyst=False,
            last_decision=None,
            note=None,
            first_seen_at=None,
            last_evaluated_at=None,
            updated_at=None,
        )
    )
    assert out.recovery_probability is None
    assert out.note is None


def test_hv_dip_config_from_attributes():
    row = SimpleNamespace(
        version=3,
        is_active=True,
        params={"dip_pct": 10.0},
        origin="auto",
        validation={"oos_n": 40},
        activated_at=NOW,
        created_at=NOW,
    )
    out = HvDipConfigOut.model_validate(row)
    assert out.version == 3
    assert out.origin == "auto"
    assert out.params == {"dip_pct": 10.0}


def test_hv_dip_config_history_from_attributes():
    row = SimpleNamespace(
        version=2,
        params={"dip_pct": 8.0},
        origin="manual",
        reason="rollback to v2",
        validation={},
        created_at=NOW,
    )
    out = HvDipConfigHistoryOut.model_validate(row)
    assert out.version == 2
    assert out.reason == "rollback to v2"


def test_news_event_rounding():
    row = SimpleNamespace(
        id="e1",
        ticker="NVDA",
        title="guidance up",
        url="https://example.com",
        source="finnhub",
        event_type="guidance_up",
        sentiment="bullish",
        confidence=0.87654,
        impact_score=70.1234,
        catalyst_strength="high",
        published_at=NOW,
        processed_at=NOW,
        used_in_suggestion=False,
    )
    out = NewsEventOut.model_validate(row)
    dump = out.model_dump()
    assert out.event_type == "guidance_up"
    assert out.sentiment == "bullish"
    assert dump["confidence"] == 0.8765
    assert dump["impact_score"] == 70.1234


def test_day_trade_state_defaults():
    out = DayTradeStateOut()
    assert out.circuit_breaker_tripped == []
    assert out.regimes == []


def test_day_trade_regime_slope_rounding():
    out = DayTradeRegimeOut(ticker="AAPL", regime="trend", slope=0.123456)
    assert out.regime == "trend"
    assert out.model_dump()["slope"] == 0.1235
