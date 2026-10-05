"""Insight prompt carries memory; live 7B must cite a stored lesson."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.services.llm_client import local_configured
from app.services.studies import insight
from app.services.studies.models import StudyResult


def _universe(**kw) -> StudyResult:
    base = dict(
        query_id="deep_dip",
        label="dip",
        channel="hv_dip",
        fingerprint="deep_dip",
        ticker="UNIVERSE",
        n=3652,
        p_higher=0.33,
        p_stop_first=0.47,
    )
    base.update(kw)
    return StudyResult(**base)


def test_generate_insights_injects_memory_into_the_prompt(monkeypatch):
    captured: dict = {}

    def _chat(messages, **kw):
        captured["messages"] = messages
        return SimpleNamespace(
            content=json.dumps(
                {
                    "insights": [
                        {
                            "ticker": "UNIVERSE",
                            "kind": "universe",
                            "text": "O dip continua fraco; a lição FDR manda forçar revisão.",
                            "evidence": [
                                {"fact": "P(alvo)", "value": "0.33"},
                                {"fact": "memória", "value": "padrão hv_dip:deep_dip fraco"},
                            ],
                            "confidence": 0.7,
                            "channel": "hv_dip",
                        }
                    ]
                }
            )
        )

    monkeypatch.setattr(insight, "local_configured", lambda: True)
    monkeypatch.setattr(insight, "cloud_configured", lambda: False)
    monkeypatch.setattr(insight, "_universe_news_stats", lambda db: {})
    monkeypatch.setattr(insight, "_pick_tickers", lambda results, n: [])
    monkeypatch.setattr(
        "app.services.learn.memory.prompt_block",
        lambda q, **kw: (
            "Lições acumuladas (não contradiga as REFUTADAS):\n"
            "- [REFUTADA pattern/hv_dip:deep_dip] Padrão hv_dip:deep_dip fraco após FDR"
        ),
    )
    monkeypatch.setattr(insight, "chat", _chat)

    out = insight.generate_insights(object(), results=[_universe()])
    user = captured["messages"][1]["content"]
    assert "REFUTADA" in user
    assert "hv_dip:deep_dip" in user
    assert out and "FDR" in out[0].text


def _ollama_up() -> bool:
    try:
        with httpx.Client(timeout=2.0) as client:
            resp = client.get("http://127.0.0.1:11434/api/ps")
            return resp.status_code == 200
    except httpx.HTTPError:
        return False


@pytest.mark.skipif(not local_configured() or not _ollama_up(), reason="Ollama local down")
def test_live_7b_cites_a_stored_lesson():
    from app.services.learn.memory import prompt_block
    from app.services.llm_client import chat
    from app.services.studies.models import Insight

    mem_path = Path(".cache/fiidesk/memory.db")
    lessons = prompt_block("hv_dip deep_dip fraco FDR", path=mem_path if mem_path.exists() else None)
    if "fraca" not in lessons.lower() and "fdr" not in lessons.lower():
        pytest.skip("memory has no FDR dip lesson yet")

    digest = {
        "universe": {
            "patterns": [
                {
                    "fingerprint": "deep_dip",
                    "label": "dip",
                    "n": 3652,
                    "p_higher": 0.33,
                    "p_stop_first": 0.47,
                }
            ],
            "news": {},
        },
        "tickers": [],
    }
    user = (
        lessons
        + "\n\n"
        + json.dumps(digest, ensure_ascii=False)
        + "\n\nEscreva UM insight curto do universo."
    )
    res = chat(
        [
            {"role": "system", "content": insight._SYSTEM},
            {"role": "user", "content": user},
        ],
        json_mode=True,
        temperature=0.2,
        timeout=300.0,
        escalate=False,
    )
    assert res.content, f"7B returned empty (source={res.source} status={res.status})"
    data = json.loads(res.content)
    items = data.get("insights") if isinstance(data, dict) else None
    assert isinstance(items, list) and items, f"no insights in {res.content[:400]}"
    parsed = [Insight.model_validate(item) for item in items if isinstance(item, dict)]
    blob = " ".join(
        [ins.text for ins in parsed]
        + [f"{e.fact} {e.value}" for ins in parsed for e in ins.evidence]
    ).lower()
    cited = any(
        token in blob
        for token in ("fdr", "refut", "fraca", "forçar revisão", "forcar revisao", "memória", "memoria")
    )
    assert cited, f"insight did not cite the lesson: {blob[:400]}"
