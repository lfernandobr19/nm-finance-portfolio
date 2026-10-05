"""Worker heartbeat + /health/worker Ollama probe (GET /api/ps)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.services import worker_heartbeat as hb
from app.services.worker_heartbeat import probe_ollama, write_heartbeat


class _Resp:
    def __init__(self, payload, status_code=200):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)

    def json(self):
        return self._payload


class _Client:
    payload = {"models": []}
    error = None

    def __init__(self, timeout=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url):
        if self.error:
            raise self.error
        return _Resp(self.payload)


EXPIRES = "2026-09-11T12:42:00+00:00"


def test_probe_warm(monkeypatch):
    _Client.payload = {
        "models": [
            {
                "name": "qwen2.5:7b",
                "model": "qwen2.5:7b",
                "expires_at": EXPIRES,
            }
        ]
    }
    _Client.error = None
    monkeypatch.setattr(hb.httpx, "Client", _Client)
    status, model, expires = probe_ollama()
    assert status == "warm"
    assert model == "qwen2.5:7b"
    assert expires == EXPIRES


def test_probe_cold(monkeypatch):
    _Client.payload = {"models": []}
    _Client.error = None
    monkeypatch.setattr(hb.httpx, "Client", _Client)
    status, _, expires = probe_ollama()
    assert status == "cold"
    assert expires is None


def test_probe_down(monkeypatch):
    _Client.error = httpx.ConnectError("nope")
    monkeypatch.setattr(hb.httpx, "Client", _Client)
    status, _, expires = probe_ollama()
    assert status == "down"
    assert expires is None


def _write_file(path, *, last, db="ok", ollama="warm", expires=None):
    path.write_text(
        json.dumps(
            {
                "last_run_at": last,
                "db": db,
                "ollama": ollama,
                "ollama_model": "qwen2.5:7b",
                "ollama_expires_at": expires,
                "groq_cooldown": False,
                "last_llm_source": "ollama",
            }
        ),
        encoding="utf-8",
    )


def test_health_worker_ok_warm(tmp_path, monkeypatch):
    path = tmp_path / "hb.json"
    now = datetime.now(timezone.utc).isoformat()
    _write_file(path, last=now, ollama="warm", expires=EXPIRES)
    monkeypatch.setattr("app.main.HEARTBEAT_PATH", path)
    client = TestClient(app)
    resp = client.get("/health/worker")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["ollama"] == "warm"
    assert body["groq_cooldown"] is False
    assert body["ollama_expires_at"] == EXPIRES


def test_health_worker_cold_not_503(tmp_path, monkeypatch):
    path = tmp_path / "hb.json"
    now = datetime.now(timezone.utc).isoformat()
    _write_file(path, last=now, ollama="cold")
    monkeypatch.setattr("app.main.HEARTBEAT_PATH", path)
    client = TestClient(app)
    resp = client.get("/health/worker")
    assert resp.status_code == 200
    assert resp.json()["ollama"] == "cold"
    assert resp.json()["ollama_expires_at"] is None


def test_health_worker_stale_503(tmp_path, monkeypatch):
    path = tmp_path / "hb.json"
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    _write_file(path, last=old, ollama="warm")
    monkeypatch.setattr("app.main.HEARTBEAT_PATH", path)
    client = TestClient(app)
    resp = client.get("/health/worker")
    assert resp.status_code == 503
    assert resp.json()["status"] == "stale"


def test_write_heartbeat_includes_ollama(tmp_path, monkeypatch):
    monkeypatch.setattr(hb, "HEARTBEAT_PATH", tmp_path / "hb.json")
    monkeypatch.setattr(hb, "probe_ollama", lambda: ("warm", "qwen2.5:7b", EXPIRES))
    write_heartbeat("ok")
    data = json.loads((tmp_path / "hb.json").read_text(encoding="utf-8"))
    assert data["ollama"] == "warm"
    assert data["db"] == "ok"
    assert data["ollama_expires_at"] == EXPIRES
