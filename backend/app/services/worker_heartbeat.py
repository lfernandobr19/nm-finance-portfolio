"""Worker heartbeat on disk. ARQ and the legacy runner share this file.

Ollama status comes from GET /api/ps (Context7), never from the API request path.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger("fiidesk.heartbeat")

HEARTBEAT_PATH = Path(".cache/fiidesk/worker_heartbeat.json")


def _ollama_native_base(local_base: str) -> str:
    raw = (local_base or "").rstrip("/")
    if raw.endswith("/v1"):
        raw = raw[: -len("/v1")]
    return raw or "http://127.0.0.1:11434"


def _matching_model(models: list[Any], wanted: str) -> dict[str, Any] | None:
    needle = (wanted or "").strip().lower()
    if not needle:
        return None
    for item in models:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("model") or "").lower()
        if name == needle or name.startswith(needle + ":") or needle.startswith(name):
            return item
    return None


def probe_ollama() -> tuple[str, str | None, str | None]:
    """Return (warm|cold|down, model_name, expires_at ISO or None). Timeout 1s."""
    settings = get_settings()
    model = (settings.llm_local_model or "").strip() or None
    base = _ollama_native_base(settings.llm_local_base)
    url = base.rstrip("/") + "/api/ps"
    try:
        with httpx.Client(timeout=1.0) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.info("ollama probe down: %s", exc)
        return "down", model, None
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        models = []
    match = _matching_model(models, model) if model else None
    if match:
        raw_exp = match.get("expires_at")
        expires = str(raw_exp) if raw_exp else None
        return "warm", model, expires
    return "cold", model, None


def write_heartbeat(db_status: str) -> None:
    try:
        from app.services.llm_client import groq_in_cooldown, last_llm_source

        ollama, ollama_model, expires_at = probe_ollama()
        payload = {
            "last_run_at": datetime.now(timezone.utc).isoformat(),
            "db": db_status,
            "ollama": ollama,
            "ollama_model": ollama_model,
            "ollama_expires_at": expires_at,
            "groq_cooldown": bool(groq_in_cooldown()),
            "last_llm_source": last_llm_source(),
        }
        HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT_PATH.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        logger.exception("Failed to write worker heartbeat")


def read_heartbeat() -> dict[str, Any] | None:
    if not HEARTBEAT_PATH.exists():
        return None
    try:
        data = json.loads(HEARTBEAT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None
