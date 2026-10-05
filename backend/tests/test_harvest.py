"""Harvest writes only what already passed a gate; thin samples are dropped."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.services.learn import harvest as har
from app.services.learn import memory as mem


def _vec(x: float, n: int = 8) -> list[float]:
    return [x] + [0.0] * (n - 1)


def _embed(tmp_path: Path, monkeypatch):
    path = tmp_path / "memory.db"
    monkeypatch.setattr(mem, "embed", lambda texts, **kw: [_vec(0.4) for _ in texts])
    return path


def test_harvest_guards_writes_fdr_survivors_only(tmp_path, monkeypatch):
    path = _embed(tmp_path, monkeypatch)
    n = har.harvest_guards(
        {
            "hv_dip:deep_dip": {
                "force_review": True,
                "p_recover": 0.28,
                "p_value": 0.001,
                "n": 80,
                "oos_p_recover": 0.22,
                "oos_n": 24,
                "reason": "fraca após FDR",
            },
            "thin:pattern": {"force_review": True, "n": 8, "reason": "n baixo"},
            "hold:pattern": {"force_review": False, "n": 80},
        },
        path=path,
    )
    assert n == 1
    hits = mem.search("deep_dip", path=path, query_vec=_vec(0.4))
    assert hits
    assert hits[0]["refuted"] is True
    assert hits[0]["kind"] == "pattern"


def test_harvest_trade_review_needs_a_lesson(tmp_path, monkeypatch):
    path = _embed(tmp_path, monkeypatch)
    pos = SimpleNamespace(
        id="p1",
        ticker="SOFI",
        strategy_kind=SimpleNamespace(value="hv_dip"),
        r_multiple_realized=-1.0,
        exit_reason=SimpleNamespace(value="stop"),
    )
    assert har.harvest_trade_review(pos, {"lesson": "", "confidence": 0.9}, path=path) is None
    row = har.harvest_trade_review(
        pos,
        {"lesson": "stop bateu no mesmo pregão", "would_change": "tighter_stop", "confidence": 0.8},
        path=path,
    )
    assert row is not None
    assert row["kind"] == "trade_review"
    assert "SOFI" in row["text"]
    assert row["provenance"] == "position:p1"


def test_harvest_news_writes_allowed_only(tmp_path, monkeypatch):
    path = _embed(tmp_path, monkeypatch)
    n = har.harvest_news(
        {
            "status": "ok",
            "horizon": 14,
            "base_rate": 0.36,
            "types": [
                {"event_type": "regulation", "n": 40, "hit_rate": 0.62, "p_value": 0.01, "allowed": True},
                {"event_type": "guidance_up", "n": 80, "hit_rate": 0.18, "p_value": 0.9, "allowed": False},
            ],
        },
        path=path,
    )
    assert n == 1
    assert mem.count(path) == 1
    assert har.harvest_news({"status": "insufficient_data", "types": []}, path=path) == 0


def test_harvest_insights_require_evidence(tmp_path, monkeypatch):
    path = _embed(tmp_path, monkeypatch)
    assert har.harvest_insights(
        [{"text": "frase solta", "confidence": 0.9, "channel": "hv_dip", "ticker": "UNIVERSE"}],
        path=path,
    ) == 0
    n = har.harvest_insights(
        [
            {
                "text": "P(alvo) do dip é 0.33",
                "confidence": 0.7,
                "channel": "hv_dip",
                "ticker": "UNIVERSE",
                "evidence": [{"fact": "P(alvo)", "value": "0.33 (n=80)"}],
            }
        ],
        path=path,
    )
    assert n == 1


def test_harvest_deep_findings_need_floor_and_oos(tmp_path, monkeypatch):
    path = _embed(tmp_path, monkeypatch)
    thin = har.harvest_deep_findings(
        [{"fingerprint": "deep_dip", "horizon": 10, "n": 8, "oos_n": 2, "p_higher": 0.4}],
        path=path,
    )
    assert thin == 0
    n = har.harvest_deep_findings(
        [
            {
                "fingerprint": "deep_dip",
                "horizon": 20,
                "n": 80,
                "oos_n": 24,
                "p_higher": 0.41,
                "recovery": 0.55,
                "gap_hit": 0.2,
                "oos_p_higher": 0.38,
            }
        ],
        path=path,
    )
    assert n == 1
