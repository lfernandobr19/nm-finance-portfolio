"""LLM client: Ollama local-first, Groq 429 never retried."""

from __future__ import annotations

import json

from app.config import Settings
from app.services import llm_client as lc
from app.services.llm_client import LlmResult, chat, reset_groq_cooldown


def _settings(**kw) -> Settings:
    base = dict(
        llm_prefer_local=True,
        llm_cloud_on_escalate=True,
        llm_local_base="http://127.0.0.1:11434/v1",
        llm_local_model="qwen2.5:7b",
        llm_local_key="ollama",
        llm_api_key="gsk_test",
        llm_api_base="https://api.groq.com/openai/v1",
        llm_model="openai/gpt-oss-120b",
        llm_timeout_seconds=5.0,
        llm_groq_429_cooldown_seconds=900,
    )
    base.update(kw)
    return Settings(**base)


def test_ollama_200_json(monkeypatch):
    reset_groq_cooldown()
    monkeypatch.setattr(lc, "get_settings", lambda: _settings())
    posts: list[str] = []

    def _post(**kw):
        posts.append(kw["base"])
        assert kw["json_mode"] is True
        assert kw.get("json_schema") is None
        body = {"ticker": "XYZ", "event_type": "other", "sentiment": "neutral", "confidence": 0.9}
        return 200, json.dumps(body)

    monkeypatch.setattr(lc, "_post", _post)
    res = chat([{"role": "user", "content": "x"}], json_mode=True)
    assert res.source == "ollama"
    assert res.status == 200
    assert res.content
    assert posts == ["http://127.0.0.1:11434/v1"]


def test_ollama_down_falls_back_to_groq(monkeypatch):
    reset_groq_cooldown()
    monkeypatch.setattr(lc, "get_settings", lambda: _settings())
    posts: list[str] = []

    def _post(**kw):
        posts.append(kw["base"])
        if "11434" in kw["base"]:
            return 500, None
        return 200, "ok from groq"

    monkeypatch.setattr(lc, "_post", _post)
    res = chat([{"role": "user", "content": "x"}])
    assert res.source == "groq"
    assert res.content == "ok from groq"
    assert len(posts) == 2


def test_groq_429_does_not_retry(monkeypatch):
    reset_groq_cooldown()
    monkeypatch.setattr(lc, "get_settings", lambda: _settings())
    posts: list[int] = []

    def _post(**kw):
        posts.append(1)
        if "11434" in kw["base"]:
            return 500, None
        return 429, None

    monkeypatch.setattr(lc, "_post", _post)
    first = chat([{"role": "user", "content": "x"}])
    second = chat([{"role": "user", "content": "x"}])
    assert first.status == 429
    assert second.status == 429
    # local + groq once, then cooldown skips groq (only local)
    assert len(posts) == 3


def test_ollama_sends_json_schema(monkeypatch):
    reset_groq_cooldown()
    monkeypatch.setattr(lc, "get_settings", lambda: _settings())
    captured: dict = {}

    def _post(**kw):
        captured.update(kw)
        return 200, '{"ok": true}'

    monkeypatch.setattr(lc, "_post", _post)
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    res = chat(
        [{"role": "user", "content": "x"}],
        json_mode=True,
        json_schema=schema,
    )
    assert res.source == "ollama"
    assert captured["json_schema"] == schema
    assert "11434" in captured["base"]


def test_cloud_only_never_sends_json_schema(monkeypatch):
    reset_groq_cooldown()
    monkeypatch.setattr(lc, "get_settings", lambda: _settings())
    captured: dict = {}

    def _post(**kw):
        captured.update(kw)
        return 200, '{"ok": true}'

    monkeypatch.setattr(lc, "_post", _post)
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    res = chat(
        [{"role": "user", "content": "x"}],
        json_mode=True,
        json_schema=schema,
        cloud_only=True,
    )
    assert res.source == "groq"
    assert captured.get("json_schema") is None
    assert "groq" in captured["base"]


def test_post_body_json_schema_vs_json_object(monkeypatch):
    captured: dict = {}

    class _Resp:
        status_code = 200
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": "{}"}}]}

    class _Client:
        def __init__(self, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json=None, headers=None):
            captured["body"] = json
            return _Resp()

    monkeypatch.setattr(lc.httpx, "Client", _Client)
    schema = {"type": "object", "properties": {"ticker": {"type": "string"}}}
    lc._post(
        base="http://127.0.0.1:11434/v1",
        key="ollama",
        model="qwen2.5:7b",
        messages=[{"role": "user", "content": "x"}],
        temperature=0.0,
        json_mode=True,
        timeout=5.0,
        keep_alive="30m",
        json_schema=schema,
    )
    fmt = captured["body"]["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["schema"] == schema
    assert captured["body"]["keep_alive"] == "30m"

    lc._post(
        base="https://api.groq.com/openai/v1",
        key="gsk",
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": "x"}],
        temperature=0.0,
        json_mode=True,
        timeout=5.0,
        json_schema=None,
    )
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert "keep_alive" not in captured["body"]


def test_local_post_sends_keep_alive(monkeypatch):
    captured: dict = {}

    class _Resp:
        status_code = 200
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": "{}"}}]}

    class _Client:
        def __init__(self, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json=None, headers=None):
            captured["body"] = json
            return _Resp()

    monkeypatch.setattr(lc.httpx, "Client", _Client)
    lc._post(
        base="http://127.0.0.1:11434/v1",
        key="ollama",
        model="qwen2.5:7b",
        messages=[{"role": "user", "content": "x"}],
        temperature=0.0,
        json_mode=True,
        timeout=5.0,
        keep_alive="30m",
    )
    assert captured["body"]["keep_alive"] == "30m"


def test_try_local_passes_keep_alive(monkeypatch):
    reset_groq_cooldown()
    monkeypatch.setattr(lc, "get_settings", lambda: _settings())
    captured: dict = {}

    def _post(**kw):
        captured.update(kw)
        return 200, '{"ok": true}'

    monkeypatch.setattr(lc, "_post", _post)
    chat([{"role": "user", "content": "x"}], json_mode=True)
    assert captured.get("keep_alive") == "30m"
    assert lc.last_llm_source() == "ollama"


def test_cloud_only_omits_keep_alive(monkeypatch):
    reset_groq_cooldown()
    monkeypatch.setattr(lc, "get_settings", lambda: _settings())
    captured: dict = {}

    def _post(**kw):
        captured.update(kw)
        return 200, '{"ok": true}'

    monkeypatch.setattr(lc, "_post", _post)
    chat([{"role": "user", "content": "x"}], json_mode=True, cloud_only=True)
    assert captured.get("keep_alive") is None
    assert "groq" in captured["base"]
