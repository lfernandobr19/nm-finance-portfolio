"""7B proposes new StudyQuery entries (JSON schema, extra=forbid, capped).

The LLM only *formulates questions* — never computes probabilities. Invalid or
extra-key JSON is dropped silently. A low nightly cap protects the Groq budget.
"""

from __future__ import annotations

import json
import logging

from pydantic import ValidationError

from app.services.llm_client import chat, cloud_configured, local_configured
from app.services.studies.models import StudyQuery

logger = logging.getLogger("fiidesk.studies.propose")

PROPOSE_CAP = 5

_SYSTEM = (
    "Você propõe perguntas de estudo quantitativo para um desk de trading. "
    "Cada pergunta vira uma analogia numérica sobre barras OHLC já em cache. "
    "Responda SOMENTE com um objeto JSON {\"queries\": [ ... ]} seguindo o schema. "
    "Não invente probabilidades. Use apenas canais hv_dip, swing ou day_trade e "
    "fingerprints deep_dip, breakout_h1, orb ou vwap_reclaim. Se houver Lições "
    "acumuladas REFUTADAS, não reproponha a mesma pergunta."
)


def propose_queries(
    known_ids: list[str],
    *,
    cap: int = PROPOSE_CAP,
) -> list[StudyQuery]:
    if not (local_configured() or cloud_configured()):
        return []
    schema = StudyQuery.model_json_schema()
    known = set(known_ids)
    user = (
        "IDs já conhecidos: "
        + (", ".join(sorted(known)) if known else "(nenhum)")
        + "\n\nProponha até "
        + str(cap)
        + " perguntas novas de estudo (padrão/tendência/frequência/chance)."
    )
    try:
        from app.services.learn.memory import prompt_block

        lessons = prompt_block("perguntas de estudo refutadas hv_dip swing day_trade")
        if lessons:
            user = lessons + "\n\n" + user
    except Exception:
        pass
    res = chat(
        [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user},
        ],
        json_mode=True,
        json_schema=schema,
        temperature=0.2,
    )
    if not res.content:
        return []
    try:
        data = json.loads(res.content)
    except json.JSONDecodeError:
        logger.info("study propose: non-JSON dropped")
        return []

    if isinstance(data, dict):
        items = data.get("queries")
    elif isinstance(data, list):
        items = data
    else:
        items = None
    if not isinstance(items, list):
        return []

    out: list[StudyQuery] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            q = StudyQuery.model_validate(item)
        except ValidationError as exc:
            logger.info("study propose drop (schema): %s", str(exc.errors()[:1]))
            continue
        if q.id in known or q.id in seen:
            continue
        seen.add(q.id)
        out.append(q)
        if len(out) >= cap:
            break
    return out


__all__ = ["PROPOSE_CAP", "propose_queries"]
