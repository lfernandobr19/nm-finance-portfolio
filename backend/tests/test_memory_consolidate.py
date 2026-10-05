"""consolidate() is the public entry the research worker calls."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.learn import memory as mem


def test_consolidate_is_idempotent_on_empty(tmp_path: Path, monkeypatch):
    path = tmp_path / "m.db"
    monkeypatch.setattr(mem, "embed", lambda texts, **kw: [[1.0, 0.0] for _ in texts])
    out = mem.consolidate(path=path)
    assert out["merged"] == 0
    assert out["expired"] == 0


def test_consolidate_near_dup_keeps_max_n(tmp_path: Path, monkeypatch):
    """Research calls consolidate every cycle; summing n is how 3652 became millions."""
    path = tmp_path / "m.db"
    monkeypatch.setattr(mem, "embed", lambda texts, **kw: [[1.0, 0.0] for _ in texts])
    mem.write(
        kind="pattern",
        scope="deep_dip:h10",
        text="deep_dip horizonte 10 (n=3652, oos_n=1278)",
        provenance="research:deep_backtest",
        n_support=3652,
        evidence=[{"n": 3652}],
        vector=[1.0, 0.0],
        path=path,
    )
    import sqlite3

    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO memories(id, kind, scope, text, provenance, confidence, evidence, "
        "n_support, created_at, refuted) VALUES "
        "('dup','pattern','deep_dip:h10','quase o mesmo (n=3652)','research:deep_backtest:rerun',"
        "0.5,'[{\"n\":3652}]',3652,'2026-01-01T00:00:00+00:00',0)"
    )
    conn.execute(
        "INSERT INTO memory_emb(memory_id, vec, dim) VALUES ('dup', '[1.0, 0.0]', 2)"
    )
    conn.commit()
    conn.close()
    assert mem.count(path) == 2
    out = mem.consolidate(path=path)
    assert out["merged"] == 1
    assert mem.count(path) == 1
    assert mem.list_recent(path=path, limit=1)[0]["n_support"] == 3652


def test_consolidate_drops_expired(tmp_path: Path, monkeypatch):
    path = tmp_path / "m.db"
    monkeypatch.setattr(mem, "embed", lambda texts, **kw: [[1.0, 0.0] for _ in texts])
    mem.write(
        kind="lesson",
        scope="x",
        text="velha",
        provenance="t-expired",
        valid_until=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        vector=[1.0, 0.0],
        path=path,
    )
    mem.write(
        kind="lesson",
        scope="x",
        text="nova",
        provenance="t",
        vector=[0.0, 1.0],
        path=path,
    )
    out = mem.consolidate(path=path)
    assert out["expired"] == 1
    assert mem.count(path) == 1
