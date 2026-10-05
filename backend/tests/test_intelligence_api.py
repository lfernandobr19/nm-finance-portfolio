"""GET /intelligence/pulse — read-only snapshot (FastAPI TestClient)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.main import app
from app.services import intelligence as intel


def _auth_user():
    return SimpleNamespace(id="u1", email="t@example.com", is_active=True)


def test_pulse_route_registered():
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/v1/intelligence/pulse" in paths


def test_pulse_401_without_token():
    client = TestClient(app)
    resp = client.get("/api/v1/intelligence/pulse")
    assert resp.status_code == 401


def test_pulse_available_false_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(intel, "STATUS_PATH", tmp_path / "missing.json")
    ran = MagicMock()
    monkeypatch.setattr(intel, "run_intelligence_pulse", ran)
    app.dependency_overrides[get_current_user] = _auth_user
    try:
        client = TestClient(app)
        resp = client.get("/api/v1/intelligence/pulse")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["n_closed_usd"] == 0
    assert body["recent_reviews"] == []
    ran.assert_not_called()


def test_pulse_available_false_with_swing_h1(tmp_path, monkeypatch):
    path = tmp_path / "intelligence.json"
    path.write_text(
        json.dumps(
            {
                "available": False,
                "hv_dip_auto_buy_enabled": False,
                "swing_h1": {"h1_ok": 3, "h1_skip": 1, "h1_fail": 2},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(intel, "STATUS_PATH", path)
    ran = MagicMock()
    monkeypatch.setattr(intel, "run_intelligence_pulse", ran)
    app.dependency_overrides[get_current_user] = _auth_user
    try:
        client = TestClient(app)
        resp = client.get("/api/v1/intelligence/pulse")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["swing_h1"]["h1_ok"] == 3
    assert body["swing_h1"]["h1_fail"] == 2
    ran.assert_not_called()


def test_pulse_200_from_disk(tmp_path, monkeypatch):
    path = tmp_path / "intelligence.json"
    path.write_text(
        json.dumps(
            {
                "available": True,
                "ts": "2026-09-11T06:00:00+00:00",
                "n_closed_usd": 0,
                "reviews_n": 1,
                "learn": {"hv_dip": {"status": "no_data", "n": 0}},
                "calibration": {"n_labeled": 45, "hit_rate": 0.27, "brier": 0.4},
                "hv_dip_auto_buy_enabled": False,
                "recent_reviews": [
                    {
                        "ticker": "VALE3",
                        "lesson": "stop hit",
                        "would_change": "none",
                        "confidence": 0.7,
                        "source": "ollama",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(intel, "STATUS_PATH", path)
    ran = MagicMock()
    monkeypatch.setattr(intel, "run_intelligence_pulse", ran)
    app.dependency_overrides[get_current_user] = _auth_user
    try:
        client = TestClient(app)
        resp = client.get("/api/v1/intelligence/pulse")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["learn"]["hv_dip"]["status"] == "no_data"
    assert body["recent_reviews"][0]["ticker"] == "VALE3"
    assert body["hv_dip_auto_buy_enabled"] is False
    ran.assert_not_called()


def test_pulse_200_includes_studies(tmp_path, monkeypatch):
    path = tmp_path / "intelligence.json"
    path.write_text(
        json.dumps(
            {
                "available": True,
                "hv_dip_auto_buy_enabled": False,
                "studies": {
                    "ts": "2026-09-11T06:00:00+00:00",
                    "queries": [
                        {
                            "id": "deep_dip",
                            "label": "dip",
                            "channel": "hv_dip",
                            "fingerprint": "deep_dip",
                            "horizon": 10,
                            "metric": "p_higher",
                            "target_r": 2.0,
                            "params": {},
                        }
                    ],
                    "results": [
                        {
                            "query_id": "deep_dip",
                            "ticker": "UNIVERSE",
                            "n": 40,
                            "p_higher": 0.35,
                            "p_stop_first": 0.65,
                        }
                    ],
                    "guards": {},
                    "decisions": [],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(intel, "STATUS_PATH", path)
    ran = MagicMock()
    monkeypatch.setattr(intel, "run_intelligence_pulse", ran)
    app.dependency_overrides[get_current_user] = _auth_user
    try:
        client = TestClient(app)
        resp = client.get("/api/v1/intelligence/pulse")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["studies"]["results"][0]["n"] == 40
    assert body["studies"]["results"][0]["p_higher"] == 0.35
    ran.assert_not_called()


def test_pulse_overlay_last_llm_keeps_prompt_last_source(tmp_path, monkeypatch):
    path = tmp_path / "intelligence.json"
    path.write_text(
        json.dumps(
            {
                "available": True,
                "last_source": "classify_v1",
                "hv_dip_auto_buy_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(intel, "STATUS_PATH", path)
    monkeypatch.setattr(
        "app.api.intelligence.read_heartbeat",
        lambda: {
            "ollama": "warm",
            "groq_cooldown": False,
            "last_llm_source": "ollama",
            "ollama_expires_at": "2026-09-11T12:42:00+00:00",
        },
    )
    ran = MagicMock()
    monkeypatch.setattr(intel, "run_intelligence_pulse", ran)
    app.dependency_overrides[get_current_user] = _auth_user
    try:
        client = TestClient(app)
        resp = client.get("/api/v1/intelligence/pulse")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["last_source"] == "classify_v1"
    assert body["last_llm_source"] == "ollama"
    assert body["ollama_expires_at"] == "2026-09-11T12:42:00+00:00"
    assert body["last_source"] != body["last_llm_source"]
    ran.assert_not_called()
