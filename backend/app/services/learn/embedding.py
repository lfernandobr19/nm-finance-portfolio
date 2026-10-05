"""Ollama embeddings with batch input and optional dimension truncation.

The official ``/api/embed`` endpoint accepts ``input`` as a list of strings and
an optional ``dimensions`` field. Cosine search here is pure Python, so cutting
768 → 256 is a ~3× cheaper query. If the model ignores ``dimensions`` the
client truncates and renormalizes.
"""

from __future__ import annotations

import math
from typing import Sequence

import httpx

from app.config import get_settings

DEFAULT_MODEL = "nomic-embed-text"
DEFAULT_DIMS = 256


def _ollama_base() -> str:
    settings = get_settings()
    raw = (getattr(settings, "llm_local_base", None) or "http://127.0.0.1:11434").rstrip("/")
    if raw.endswith("/v1"):
        raw = raw[:-3]
    return raw.rstrip("/")


def _model() -> str:
    settings = get_settings()
    return getattr(settings, "learn_embedding_model", None) or DEFAULT_MODEL


def _dims() -> int:
    settings = get_settings()
    return int(getattr(settings, "learn_embedding_dims", None) or DEFAULT_DIMS)


def _renorm(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm <= 0:
        return vec
    return [x / norm for x in vec]


def _fit_dims(vec: list[float], dims: int) -> list[float]:
    if dims <= 0 or len(vec) == dims:
        return vec
    if len(vec) > dims:
        return _renorm(vec[:dims])
    return vec


def embed(
    texts: Sequence[str],
    *,
    model: str | None = None,
    dimensions: int | None = None,
    timeout: float = 30.0,
    client: httpx.Client | None = None,
) -> list[list[float]]:
    """Embed one or many strings. Returns one vector per input, same order."""
    if not texts:
        return []
    dims = int(dimensions if dimensions is not None else _dims())
    settings = get_settings()
    payload = {
        "model": model or _model(),
        "input": list(texts),
        "dimensions": dims,
        # Context7 / Ollama /api/embed: keep the embedder warm like the 7B chat.
        "keep_alive": getattr(settings, "llm_local_keep_alive", None) or "30m",
    }
    url = f"{_ollama_base()}/api/embed"
    own = client is None
    http = client or httpx.Client(timeout=timeout)
    try:
        resp = http.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    finally:
        if own:
            http.close()
    raw = data.get("embeddings") or data.get("embedding")
    if raw is None:
        return []
    if raw and isinstance(raw[0], (int, float)):
        vectors = [list(map(float, raw))]
    else:
        vectors = [list(map(float, v)) for v in raw]
    return [_fit_dims(v, dims) for v in vectors]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(n))
    na = math.sqrt(sum(a[i] * a[i] for i in range(n)))
    nb = math.sqrt(sum(b[i] * b[i] for i in range(n)))
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)


__all__ = ["DEFAULT_MODEL", "DEFAULT_DIMS", "embed", "cosine"]
