"""Phase 1 debug: change predicates are idempotent and fire only on data change."""

from __future__ import annotations

from app.services.studies import change as ch


def _patch_state(monkeypatch, tmp_path):
    monkeypatch.setattr(ch, "STATE_PATH", tmp_path / "change_state.json")
    return tmp_path / "change_state.json"


def test_propose_due_idempotent(monkeypatch, tmp_path):
    _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(ch.time, "time", lambda: 1000.0)
    assert ch.propose_due() is True
    ch.mark_propose_done()
    assert ch.propose_due() is False


def test_propose_due_after_floor(monkeypatch, tmp_path):
    _patch_state(monkeypatch, tmp_path)
    now = {"t": 1000.0}
    monkeypatch.setattr(ch.time, "time", lambda: now["t"])
    ch.mark_propose_done()
    assert ch.propose_due() is False
    now["t"] = 1000.0 + ch.PROPOSE_FLOOR_SECONDS + 1
    assert ch.propose_due() is True


def test_learn_due_and_mark(monkeypatch, tmp_path):
    _patch_state(monkeypatch, tmp_path)
    counts = {"hv_dip": 0}
    monkeypatch.setattr(ch, "_closed_counts", lambda db: dict(counts))
    db = object()
    assert ch.learn_due(db, "hv_dip") is True
    ch.mark_learn_done(db)
    assert ch.learn_due(db, "hv_dip") is False
    counts["hv_dip"] = 3
    assert ch.learn_due(db, "hv_dip") is True
    # other kinds not affected by the hv_dip count change
    assert ch.learn_due(db, "swing") is True  # still unmarked


def test_studies_due_and_mark(monkeypatch, tmp_path):
    _patch_state(monkeypatch, tmp_path)
    fp = {"bars": {"market": {"n": 1, "mtime": 1.0}}, "day_trade_max_ts": None}
    monkeypatch.setattr(ch, "studies_fingerprint", lambda db: dict(fp))
    db = object()
    assert ch.studies_due(db) is True
    ch.mark_studies_done(db)
    assert ch.studies_due(db) is False
    fp["bars"]["market"]["n"] = 2
    assert ch.studies_due(db) is True


def test_calibrate_and_review_idempotent(monkeypatch, tmp_path):
    _patch_state(monkeypatch, tmp_path)
    pending = {"c": 0, "r": 0}
    monkeypatch.setattr(ch, "_calibrate_pending", lambda db: pending["c"])
    monkeypatch.setattr(ch, "_review_pending", lambda db: pending["r"])
    db = object()
    assert ch.calibrate_due(db) is True
    assert ch.review_due(db) is True
    ch.mark_calibrate_done(db)
    ch.mark_review_done(db)
    assert ch.calibrate_due(db) is False
    assert ch.review_due(db) is False
    pending["c"] = 5
    pending["r"] = 2
    assert ch.calibrate_due(db) is True
    assert ch.review_due(db) is True


def test_insights_due_retry_floor(monkeypatch, tmp_path):
    _patch_state(monkeypatch, tmp_path)
    snap = tmp_path / "studies.json"
    monkeypatch.setattr(ch, "SNAPSHOT_PATH", snap)
    now = {"t": 1000.0}
    monkeypatch.setattr(ch.time, "time", lambda: now["t"])
    db = object()

    snap.write_text('{"results": [{"query_id": "x"}], "insights": []}', encoding="utf-8")
    assert ch.insights_due(db) is True  # never attempted
    ch.mark_insights_attempted(db)
    assert ch.insights_due(db) is False
    now["t"] = 1000.0 + ch.INSIGHT_RETRY_FLOOR_SECONDS + 1
    assert ch.insights_due(db) is True


def test_insights_due_regen_floor(monkeypatch, tmp_path):
    _patch_state(monkeypatch, tmp_path)
    snap = tmp_path / "studies.json"
    monkeypatch.setattr(ch, "SNAPSHOT_PATH", snap)
    now = {"t": 1000.0}
    monkeypatch.setattr(ch.time, "time", lambda: now["t"])
    db = object()

    snap.write_text('{"results": [{"query_id": "x"}], "insights": [{"kind": "universe"}]}', encoding="utf-8")
    assert ch.insights_due(db) is True  # never attempted
    ch.mark_insights_attempted(db)
    assert ch.insights_due(db) is False  # within regen floor
    # the shorter retry floor must NOT apply once insights exist
    now["t"] = 1000.0 + ch.INSIGHT_RETRY_FLOOR_SECONDS + 1
    assert ch.insights_due(db) is False  # still within regen floor
    now["t"] = 1000.0 + ch.INSIGHT_REGEN_FLOOR_SECONDS + 1
    assert ch.insights_due(db) is True  # regen floor passed


def test_insights_due_no_results(monkeypatch, tmp_path):
    _patch_state(monkeypatch, tmp_path)
    snap = tmp_path / "studies.json"
    monkeypatch.setattr(ch, "SNAPSHOT_PATH", snap)
    db = object()
    snap.write_text('{"results": [], "insights": []}', encoding="utf-8")
    assert ch.insights_due(db) is False
    snap.write_text("not json", encoding="utf-8")
    assert ch.insights_due(db) is False
