"""Phase 2 debug: 7B proposals — extra key dropped, valid enters, capped, JSON invalid dropped."""

from __future__ import annotations

import json
import types

from app.services.studies.models import StudyQuery
from app.services.studies.propose import PROPOSE_CAP, propose_queries


def _patch_llm(monkeypatch, content: str):
    monkeypatch.setattr("app.services.studies.propose.local_configured", lambda: True)
    monkeypatch.setattr("app.services.studies.propose.cloud_configured", lambda: False)
    monkeypatch.setattr(
        "app.services.studies.propose.chat",
        lambda *a, **kw: types.SimpleNamespace(content=content),
    )


def test_valid_proposal_enters(monkeypatch):
    payload = json.dumps(
        {
            "queries": [
                {
                    "id": "trend_slope",
                    "label": "Tendência a favor persegue alvo?",
                    "channel": "swing",
                    "fingerprint": "breakout_h1",
                    "horizon": 12,
                    "metric": "p_higher",
                    "target_r": 2.0,
                    "params": {"lookback": 10},
                }
            ]
        }
    )
    _patch_llm(monkeypatch, payload)
    out = propose_queries([])
    assert [q.id for q in out] == ["trend_slope"]


def test_extra_key_dropped(monkeypatch):
    payload = json.dumps(
        {
            "queries": [
                {
                    "id": "sneaky",
                    "label": "x",
                    "channel": "swing",
                    "fingerprint": "breakout_h1",
                    "horizon": 10,
                    "metric": "p_higher",
                    "target_r": 2.0,
                    "params": {},
                    "hallucinated_probability": 0.99,  # extra key must be rejected
                }
            ]
        }
    )
    _patch_llm(monkeypatch, payload)
    out = propose_queries([])
    assert out == []


def test_invalid_json_dropped(monkeypatch):
    _patch_llm(monkeypatch, "not json at all")
    assert propose_queries([]) == []


def test_capped(monkeypatch):
    queries = [
        {
            "id": f"q{i}",
            "label": "x",
            "channel": "swing",
            "fingerprint": "breakout_h1",
            "horizon": 10,
            "metric": "p_higher",
            "target_r": 2.0,
            "params": {},
        }
        for i in range(20)
    ]
    _patch_llm(monkeypatch, json.dumps({"queries": queries}))
    out = propose_queries([])
    assert len(out) == PROPOSE_CAP


def test_known_ids_not_reproposed(monkeypatch):
    payload = json.dumps(
        {
            "queries": [
                {
                    "id": "known",
                    "label": "x",
                    "channel": "swing",
                    "fingerprint": "breakout_h1",
                    "horizon": 10,
                    "metric": "p_higher",
                    "target_r": 2.0,
                    "params": {},
                }
            ]
        }
    )
    _patch_llm(monkeypatch, payload)
    assert propose_queries(["known"]) == []


def test_proposal_is_a_studyquery():
    q = StudyQuery(id="a", label="b", channel="hv_dip", fingerprint="deep_dip")
    assert q.model_validate(q.model_dump()).id == "a"
