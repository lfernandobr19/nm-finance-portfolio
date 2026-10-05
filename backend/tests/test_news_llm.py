"""News classifier cascade: skip no-ticker, escalate Groq, keep 7B on 429."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from app.domain.models import NewsEvent
from app.services import news_llm as nl
from app.services.llm_client import LlmResult


def _ev(title: str, related: str = "", ticker: str | None = None) -> NewsEvent:
    return NewsEvent(
        title=title,
        url=f"https://example.test/{title[:20]}",
        source="finnhub",
        raw={"related": related},
        ticker=ticker,
    )


def _db(events: list[NewsEvent]) -> MagicMock:
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = events
    return db


def test_no_ticker_skips_http(monkeypatch):
    calls: list = []
    monkeypatch.setattr(nl, "chat", lambda *a, **k: calls.append(1) or None)
    monkeypatch.setattr(nl, "local_configured", lambda: True)
    monkeypatch.setattr(nl, "cloud_configured", lambda: True)
    ev = _ev("Market rally continues worldwide")
    n = nl.classify_pending(_db([ev]))
    assert n == 1
    assert calls == []
    assert ev.event_type == "other"
    assert ev.processed_at is not None
    assert ev.raw.get("classifier_source") == "skip"


def test_low_confidence_escalates_then_keeps_local_on_429(monkeypatch):
    monkeypatch.setattr(nl, "local_configured", lambda: True)
    monkeypatch.setattr(nl, "cloud_configured", lambda: True)
    monkeypatch.setattr(nl, "_open_usd_tickers", lambda db: {"NIO"})
    calls: list[dict] = []

    def _chat(messages, json_mode=False, temperature=0.0, escalate=False, cloud_only=False, **kwargs):
        calls.append({"cloud_only": cloud_only, "escalate": escalate})
        if cloud_only:
            return LlmResult(content=None, source="fail", status=429, model="groq", escalated=True)
        payload = {
            "ticker": "NIO",
            "event_type": "product_launch",
            "sentiment": "bullish",
            "confidence": 0.4,
            "catalyst_strength": "medium",
            "impact_score": 40,
        }
        return LlmResult(content=json.dumps(payload), source="ollama", status=200, model="qwen2.5:7b")

    monkeypatch.setattr(nl, "chat", _chat)
    ev = _ev("NIO launches new battery", related="NIO")
    n = nl.classify_pending(_db([ev]))
    assert n == 1
    assert any(c["cloud_only"] for c in calls)
    assert ev.confidence == 0.4
    assert ev.raw.get("classifier_source") == "ollama"
    assert ev.raw.get("escalated") is True
    assert ev.ticker == "NIO"


def test_high_confidence_does_not_call_groq(monkeypatch):
    monkeypatch.setattr(nl, "local_configured", lambda: True)
    monkeypatch.setattr(nl, "cloud_configured", lambda: True)
    monkeypatch.setattr(nl, "_open_usd_tickers", lambda db: set())
    calls: list[dict] = []

    def _chat(messages, json_mode=False, temperature=0.0, escalate=False, cloud_only=False, **kwargs):
        calls.append({"cloud_only": cloud_only})
        payload = {
            "ticker": "AAPL",
            "event_type": "earnings",
            "sentiment": "bullish",
            "confidence": 0.9,
            "catalyst_strength": "low",
            "impact_score": 55,
        }
        return LlmResult(content=json.dumps(payload), source="ollama", status=200, model="qwen2.5:7b")

    monkeypatch.setattr(nl, "chat", _chat)
    ev = _ev("AAPL beats estimates", related="AAPL")
    nl.classify_pending(_db([ev]))
    assert calls == [{"cloud_only": False}]
    assert ev.raw.get("escalated") is False
    assert ev.raw.get("prompt_version") == "classify_v1"
