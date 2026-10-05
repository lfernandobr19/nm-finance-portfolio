"""Phase 2 debug: insight digest is correct; LLM output validated + capped."""

from __future__ import annotations

import json
import types
from types import SimpleNamespace

from app.services.studies import insight
from app.services.studies.models import StudyResult


def _bar(close: float, **kw):
    return SimpleNamespace(close=close, high=kw.get("high", close), low=kw.get("low", close),
                           open=kw.get("open", close), date=kw.get("date"), volume=0.0)


def _universe_result(**kw):
    base = dict(query_id="deep_dip", label="dip", channel="hv_dip",
                fingerprint="deep_dip", ticker="UNIVERSE", n=3700,
                p_higher=0.33, p_stop_first=0.47)
    base.update(kw)
    return StudyResult(**base)


def test_price_stats(monkeypatch):
    bars = [_bar(100.0), _bar(99.0), _bar(98.0), _bar(101.0), _bar(102.0)]
    s = insight._price_stats(bars)
    assert s["bars"] == 5
    assert s["close"] == 102.0
    assert s["max_drawdown_pct"] < 0
    assert "above_sma20" in s


def test_price_stats_empty():
    assert insight._price_stats([]) == {}


def test_build_universe_digest(monkeypatch):
    monkeypatch.setattr(insight, "_universe_news_stats", lambda db: {"total": 9, "classified": 4})
    res = insight.build_universe_digest(object(), [_universe_result()])
    assert res["news"] == {"total": 9, "classified": 4}
    assert res["patterns"][0]["n"] == 3700
    assert res["patterns"][0]["p_higher"] == 0.33


def test_build_ticker_digest(monkeypatch):
    monkeypatch.setattr(insight, "_ticker_news_stats", lambda db, t: {"bullish": 2})
    fake = types.SimpleNamespace()
    fake.fetch_daily_bars = lambda t: [_bar(10.0), _bar(11.0)]
    monkeypatch.setattr("app.services.market_data.MarketDataClient", lambda: fake)
    res = insight.build_ticker_digest(
        object(), "AMD", [_universe_result(ticker="AMD", p_higher=0.4, vs_universe=0.07)]
    )
    assert res["ticker"] == "AMD"
    assert res["price"]["close"] == 11.0
    assert res["news"] == {"bullish": 2}
    assert res["patterns"][0]["vs_universe"] == 0.07


def _patch_llm(monkeypatch, content):
    monkeypatch.setattr(insight, "local_configured", lambda: True)
    monkeypatch.setattr(insight, "cloud_configured", lambda: False)
    monkeypatch.setattr(insight, "_universe_news_stats", lambda db: {})
    monkeypatch.setattr(
        insight, "chat", lambda *a, **kw: types.SimpleNamespace(content=content)
    )


def test_not_configured_returns_empty(monkeypatch):
    monkeypatch.setattr(insight, "local_configured", lambda: False)
    monkeypatch.setattr(insight, "cloud_configured", lambda: False)
    assert insight.generate_insights(object(), results=[_universe_result()]) == []


def test_valid_insight_accepted(monkeypatch):
    payload = json.dumps({"insights": [{
        "ticker": "UNIVERSE", "kind": "universe",
        "text": "Deep dip persegue o alvo em 33% dos casos.",
        "evidence": [{"fact": "P(alvo)", "value": "0.33"}],
        "confidence": 0.8, "channel": "hv_dip",
    }]})
    _patch_llm(monkeypatch, payload)
    out = insight.generate_insights(object(), results=[_universe_result()])
    assert len(out) == 1
    assert out[0].kind == "universe"
    assert out[0].evidence[0].fact == "P(alvo)"


def test_extra_key_rejected(monkeypatch):
    payload = json.dumps({"insights": [{
        "ticker": "UNIVERSE", "kind": "universe", "text": "x",
        "evidence": [], "confidence": 0.8, "channel": "hv_dip",
        "hallucinated_probability": 0.99,
    }]})
    _patch_llm(monkeypatch, payload)
    assert insight.generate_insights(object(), results=[_universe_result()]) == []


def test_loose_llm_typing_is_coerced(monkeypatch):
    # Real Groq output: null ticker, numeric evidence values, string confidence.
    payload = json.dumps({"insights": [{
        "ticker": None, "kind": "universe",
        "text": "Deep dip persegue o alvo em 33% dos casos.",
        "evidence": [{"fact": "P(alvo)", "value": 0.667}],
        "confidence": "0.8", "channel": "hv_dip",
    }]})
    _patch_llm(monkeypatch, payload)
    out = insight.generate_insights(object(), results=[_universe_result()])
    assert len(out) == 1
    assert out[0].ticker == "UNIVERSE"
    assert out[0].evidence[0].value == "0.667"
    assert out[0].confidence == 0.8


def test_invalid_json_dropped(monkeypatch):
    _patch_llm(monkeypatch, "nope")
    assert insight.generate_insights(object(), results=[_universe_result()]) == []


def test_capped(monkeypatch):
    items = [{
        "ticker": "UNIVERSE", "kind": "universe", "text": f"i{i}",
        "evidence": [], "confidence": 0.5, "channel": "hv_dip",
    } for i in range(20)]
    _patch_llm(monkeypatch, json.dumps({"insights": items}))
    out = insight.generate_insights(object(), results=[_universe_result()])
    assert len(out) == insight.INSIGHT_CAP
