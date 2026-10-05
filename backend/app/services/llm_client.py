"""Shared OpenAI-compatible chat client (Ollama local-first, Groq escalate).

Context7 (Ollama /v1/chat/completions): ``json_object`` maps to JSON mode;
``json_schema`` passes the raw schema (local only). Groq always gets
``json_object``. Local POSTs send ``keep_alive`` (default 30m) so the 7B
stays loaded between classify/pulse. HTTP 429 is a skip — never Retry/backoff
storm (ARQ max_tries=1).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger("fiidesk.llm_client")

_groq_429_until: float = 0.0


@dataclass
class LlmResult:
    content: str | None
    source: str  # ollama | groq | fail
    status: int
    model: str
    attempts: int = 1
    escalated: bool = False


_last_source: str | None = None


def last_llm_source() -> str | None:
    return _last_source


def _remember(result: LlmResult) -> LlmResult:
    global _last_source
    _last_source = result.source
    return result


def groq_in_cooldown(*, now: float | None = None) -> bool:
    return (now or time.time()) < _groq_429_until


def mark_groq_429(*, now: float | None = None) -> None:
    global _groq_429_until
    settings = get_settings()
    wait = int(settings.llm_groq_429_cooldown_seconds or 900)
    _groq_429_until = (now or time.time()) + wait
    logger.info("llm source=groq status=429 cooldown=%ss", wait)


def reset_groq_cooldown() -> None:
    global _groq_429_until
    _groq_429_until = 0.0


def local_configured() -> bool:
    settings = get_settings()
    return bool((settings.llm_local_base or "").strip() and (settings.llm_local_model or "").strip())


def cloud_configured() -> bool:
    settings = get_settings()
    return bool((settings.llm_api_key or "").strip() and (settings.llm_api_base or "").strip())


def _post(
    *,
    base: str,
    key: str,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    json_mode: bool,
    timeout: float,
    json_schema: dict[str, Any] | None = None,
    keep_alive: str | None = None,
) -> tuple[int, str | None]:
    url = base.rstrip("/") + "/chat/completions"
    body: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "messages": messages,
        "stream": False,
    }
    if json_schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"schema": json_schema},
        }
    elif json_mode:
        body["response_format"] = {"type": "json_object"}
    if keep_alive:
        body["keep_alive"] = keep_alive
    headers = {
        "Authorization": f"Bearer {key or 'ollama'}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, json=body, headers=headers)
        if resp.status_code >= 400:
            logger.warning("llm source=fail status=%s body=%s", resp.status_code, resp.text[:300])
            return resp.status_code, None
        data = resp.json()
        content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
        return resp.status_code, (content or "").strip() or None


def _try_local(
    messages: list[dict[str, str]],
    *,
    temperature: float,
    json_mode: bool,
    json_schema: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> LlmResult:
    settings = get_settings()
    timeout = float(timeout if timeout is not None else settings.llm_timeout_seconds or 45.0)
    model = settings.llm_local_model
    try:
        status, content = _post(
            base=settings.llm_local_base,
            key=settings.llm_local_key or "ollama",
            model=model,
            messages=messages,
            temperature=temperature,
            json_mode=json_mode,
            timeout=timeout,
            json_schema=json_schema,
            keep_alive=(settings.llm_local_keep_alive or "").strip() or None,
        )
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        logger.warning("llm source=ollama fail: %s", exc)
        return LlmResult(content=None, source="fail", status=0, model=model)
    source = "ollama" if content else "fail"
    logger.info("llm source=%s status=%s model=%s", source if content else "fail", status, model)
    return LlmResult(content=content, source=source if content else "fail", status=status, model=model)


def _try_cloud(
    messages: list[dict[str, str]],
    *,
    temperature: float,
    json_mode: bool,
    timeout: float | None = None,
) -> LlmResult:
    settings = get_settings()
    model = settings.llm_model
    if groq_in_cooldown():
        logger.info("llm source=groq status=cooldown")
        return LlmResult(content=None, source="fail", status=429, model=model)
    timeout = float(timeout if timeout is not None else settings.llm_timeout_seconds or 45.0)
    try:
        status, content = _post(
            base=settings.llm_api_base,
            key=settings.llm_api_key,
            model=model,
            messages=messages,
            temperature=temperature,
            json_mode=json_mode,
            timeout=timeout,
            json_schema=None,
        )
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        logger.warning("llm source=groq fail: %s", exc)
        return LlmResult(content=None, source="fail", status=0, model=model)
    if status == 429:
        mark_groq_429()
        return LlmResult(content=None, source="fail", status=429, model=model)
    source = "groq" if content else "fail"
    logger.info("llm source=%s status=%s model=%s", source if content else "fail", status, model)
    return LlmResult(content=content, source=source if content else "fail", status=status, model=model)


def chat(
    messages: list[dict[str, str]],
    *,
    json_mode: bool = False,
    temperature: float = 0.0,
    escalate: bool = False,
    cloud_only: bool = False,
    json_schema: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> LlmResult:
    """Local-first chat. ``cloud_only`` hits Groq once (no extra local call).

    ``json_schema`` is sent only to Ollama. Groq always uses ``json_object``.
    ``timeout`` overrides the global ``llm_timeout_seconds`` for large prompts
    (e.g. insight digests) without slowing every other LLM call.
    """
    settings = get_settings()
    prefer_local = bool(settings.llm_prefer_local)
    attempts = 0

    if cloud_only:
        if not cloud_configured():
            return _remember(LlmResult(content=None, source="fail", status=0, model="", attempts=0))
        attempts += 1
        cloud_res = _try_cloud(messages, temperature=temperature, json_mode=json_mode, timeout=timeout)
        cloud_res.attempts = attempts
        cloud_res.escalated = True
        return _remember(cloud_res)

    local_res: LlmResult | None = None

    if prefer_local and local_configured():
        attempts += 1
        local_res = _try_local(
            messages, temperature=temperature, json_mode=json_mode, json_schema=json_schema, timeout=timeout
        )
        if local_res.content and not escalate:
            local_res.attempts = attempts
            return _remember(local_res)
        if local_res.content and escalate and cloud_configured() and settings.llm_cloud_on_escalate:
            attempts += 1
            cloud_res = _try_cloud(messages, temperature=temperature, json_mode=json_mode, timeout=timeout)
            if cloud_res.content:
                cloud_res.attempts = attempts
                cloud_res.escalated = True
                return _remember(cloud_res)
            local_res.attempts = attempts
            local_res.escalated = True
            return _remember(local_res)
        if local_res.content:
            local_res.attempts = attempts
            return _remember(local_res)

    if cloud_configured():
        attempts += 1
        cloud_res = _try_cloud(messages, temperature=temperature, json_mode=json_mode, timeout=timeout)
        cloud_res.attempts = attempts
        return _remember(cloud_res)

    if not prefer_local and local_configured():
        attempts += 1
        local_res = _try_local(
            messages, temperature=temperature, json_mode=json_mode, json_schema=json_schema, timeout=timeout
        )
        local_res.attempts = attempts
        return _remember(local_res)

    logger.info("llm source=fail status=unconfigured")
    return _remember(LlmResult(content=None, source="fail", status=0, model="", attempts=attempts))


__all__ = [
    "LlmResult",
    "chat",
    "cloud_configured",
    "groq_in_cooldown",
    "local_configured",
    "mark_groq_429",
    "last_llm_source",
    "reset_groq_cooldown",
]
