"""Optional grounded LLM summary. Uses only injected facts — no free browsing."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.services.llm_client import chat, cloud_configured, local_configured

logger = logging.getLogger(__name__)

SYSTEM = (
    "Você resume oportunidades de FII/BDR para um investidor brasileiro. "
    "Use APENAS os dados JSON fornecidos. Não invente números, notícias ou fatos. "
    "Responda em português, em 2 a 4 frases objetivas."
)


def generate_llm_summary(
    *,
    ticker: str,
    metrics: dict[str, Any],
    reasons: list[dict[str, Any]],
    price_explanation: str,
    news_titles: list[str] | None = None,
) -> str | None:
    if not local_configured() and not cloud_configured():
        return None

    payload_facts = {
        "ticker": ticker,
        "metrics": metrics,
        "reasons": reasons,
        "price_explanation": price_explanation,
        "news_titles": (news_titles or [])[:5],
    }
    messages = [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": "Resuma com grounding estrito neste JSON:\n"
            + json.dumps(payload_facts, ensure_ascii=False),
        },
    ]
    res = chat(messages, json_mode=False, temperature=0.2, escalate=False)
    if not res.content:
        return None
    return res.content.strip() or None
