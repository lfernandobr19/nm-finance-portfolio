"""Phase 1 debug: proposals are persisted and computed (not display-only)."""

from __future__ import annotations

import json

from app.services.studies import runner
from app.services.studies.models import StudyQuery


def _q(**kw):
    base = dict(
        id="base",
        label="base",
        channel="hv_dip",
        fingerprint="deep_dip",
        horizon=10,
        metric="p_higher",
        target_r=2.0,
        params={},
    )
    base.update(kw)
    return StudyQuery(**base)


def _patch_runner(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "SNAPSHOT_PATH", tmp_path / "studies.json")
    monkeypatch.setattr(runner, "EXTRA_PATH", tmp_path / "extra.json")
    monkeypatch.setattr(runner, "write_guards", lambda guards: None)
    monkeypatch.setattr(runner, "catalog_queries", lambda: [_q()])
    monkeypatch.setattr(runner, "_hv_dip_bars", lambda: {})
    monkeypatch.setattr(runner, "_swing_bars", lambda: {})
    monkeypatch.setattr(runner, "_day_trade_sessions", lambda db: [])
    return tmp_path / "extra.json"


def test_run_studies_persists_proposal(monkeypatch, tmp_path):
    extra_path = _patch_runner(monkeypatch, tmp_path)
    proposed = _q(id="new_q", label="nova pergunta")
    monkeypatch.setattr(runner, "propose_queries", lambda known_ids: [proposed])

    snap = runner.run_studies(object(), propose=True)

    # proposal appears in the snapshot queries (for display)
    assert "new_q" in {q["id"] for q in snap["queries"]}
    # proposal is persisted for future computation
    saved = json.loads(extra_path.read_text(encoding="utf-8"))
    assert [q["id"] for q in saved] == ["new_q"]


def test_persisted_proposal_is_computed_next_run(monkeypatch, tmp_path):
    _patch_runner(monkeypatch, tmp_path)
    monkeypatch.setattr(runner, "propose_queries", lambda known_ids: [])

    # First run: no extra queries yet.
    snap1 = runner.run_studies(object(), propose=False)
    assert "new_q" not in {q["id"] for q in snap1["queries"]}

    # Manually persist a proposal as if a prior run proposed it.
    runner._save_extra_queries([_q(id="new_q", label="nova pergunta")])
    snap2 = runner.run_studies(object(), propose=False)
    # Now it is part of the computed queries (it would produce results/guards).
    assert "new_q" in {q["id"] for q in snap2["queries"]}


def test_extra_queries_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "EXTRA_PATH", tmp_path / "extra.json")
    qs = [_q(id="a"), _q(id="b", channel="swing", fingerprint="breakout_h1")]
    runner._save_extra_queries(qs)
    loaded = runner._load_extra_queries()
    assert [q.id for q in loaded] == ["a", "b"]


def test_extra_queries_corrupt_file_returns_empty(monkeypatch, tmp_path):
    p = tmp_path / "extra.json"
    monkeypatch.setattr(runner, "EXTRA_PATH", p)
    p.write_text("not json", encoding="utf-8")
    assert runner._load_extra_queries() == []


def test_insights_preserved_on_llm_failure(monkeypatch, tmp_path):
    _patch_runner(monkeypatch, tmp_path)
    monkeypatch.setattr(runner, "propose_queries", lambda known_ids: [])
    # Pre-existing insights in the snapshot (as a prior successful run left them).
    prev = [{"ticker": "UNIVERSE", "kind": "universe", "text": "dip recupera", "channel": "hv_dip"}]
    (tmp_path / "studies.json").write_text(
        json.dumps({"results": [{"query_id": "x"}], "insights": prev}), encoding="utf-8"
    )

    # LLM fails -> generate_insights returns [].
    monkeypatch.setattr(runner, "generate_insights", lambda db, results=None: [])

    snap = runner.run_studies(object(), propose=False, insights=True)
    assert len(snap["insights"]) == 1
    assert snap["insights"][0]["ticker"] == "UNIVERSE"
    assert snap["insights"][0]["text"] == "dip recupera"


def test_insights_not_generated_when_off(monkeypatch, tmp_path):
    _patch_runner(monkeypatch, tmp_path)
    monkeypatch.setattr(runner, "propose_queries", lambda known_ids: [])
    prev = [{"ticker": "UNIVERSE", "kind": "universe", "text": "dip recupera", "channel": "hv_dip"}]
    (tmp_path / "studies.json").write_text(
        json.dumps({"results": [{"query_id": "x"}], "insights": prev}), encoding="utf-8"
    )

    called = {"n": 0}
    def _gen(db, results=None):
        called["n"] += 1
        return [{"ticker": "AAPL", "kind": "ticker", "text": "novo", "channel": "hv_dip"}]
    monkeypatch.setattr(runner, "generate_insights", _gen)

    snap = runner.run_studies(object(), propose=False, insights=False)
    assert called["n"] == 0  # no LLM call
    assert len(snap["insights"]) == 1
    assert snap["insights"][0]["ticker"] == "UNIVERSE"  # previous insights kept


def test_run_studies_harvests_guards_and_insights(monkeypatch, tmp_path):
    _patch_runner(monkeypatch, tmp_path)
    monkeypatch.setattr(runner, "propose_queries", lambda known_ids: [])
    harvested = {"guards": None, "insights": None}

    def _guards(guards, **kw):
        harvested["guards"] = guards
        return 0

    def _insights(insights, **kw):
        harvested["insights"] = insights
        return 0

    monkeypatch.setattr("app.services.learn.harvest.harvest_guards", _guards)
    monkeypatch.setattr("app.services.learn.harvest.harvest_insights", _insights)
    runner.run_studies(object(), propose=False, insights=False)
    assert harvested["guards"] == {}
    assert harvested["insights"] is not None
