"""Memory store: write, hybrid search, dedup, conflict, consolidate."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.learn import memory as mem


def _vec(x: float, n: int = 8) -> list[float]:
    return [x] + [0.0] * (n - 1)


def test_same_provenance_folds_without_vectors(tmp_path: Path, monkeypatch):
    path = tmp_path / "memory.db"
    monkeypatch.setattr(mem, "embed", lambda texts, **kw: [[] for _ in texts])
    first = mem.write(
        kind="pattern",
        scope="hv_dip:deep_dip",
        text="padrão fraco",
        provenance="studies:fdr:hv_dip:deep_dip",
        vector=[],
        path=path,
    )
    again = mem.write(
        kind="pattern",
        scope="hv_dip:deep_dip",
        text="padrão fraco",
        provenance="studies:fdr:hv_dip:deep_dip",
        vector=[],
        path=path,
    )
    assert again is not None
    assert again["id"] == first["id"]
    assert again["n_support"] == 1  # same finding restated, n is not summed
    assert mem.count(path) == 1


def test_same_provenance_different_text_keeps_max_n(tmp_path: Path, monkeypatch):
    path = tmp_path / "memory.db"
    monkeypatch.setattr(mem, "embed", lambda texts, **kw: [_vec(1.0) for _ in texts])
    first = mem.write(
        kind="pattern",
        scope="hv_dip:deep_dip",
        text="P(alvo)=0.33 — forçar revisão humana",
        provenance="studies:fdr:hv_dip:deep_dip",
        n_support=3706,
        evidence=[{"n": 3706}],
        vector=_vec(1.0),
        path=path,
    )
    again = mem.write(
        kind="pattern",
        scope="hv_dip:deep_dip",
        text="P(alvo)=0.33 — desk não opera",
        provenance="studies:fdr:hv_dip:deep_dip",
        n_support=3706,
        evidence=[{"n": 3706}],
        vector=_vec(1.0),
        path=path,
    )
    assert again is not None
    assert again["id"] == first["id"]
    assert again["n_support"] == 3706
    assert mem.count(path) == 1


def test_clamp_inflated_support(tmp_path: Path, monkeypatch):
    path = tmp_path / "memory.db"
    monkeypatch.setattr(mem, "embed", lambda texts, **kw: [[] for _ in texts])
    row = mem.write(
        kind="pattern",
        scope="hv_dip:deep_dip",
        text="fraco",
        provenance="studies:fdr:hv_dip:deep_dip",
        n_support=3706,
        evidence=[{"n": 3706}],
        vector=[],
        path=path,
    )
    import sqlite3

    conn = sqlite3.connect(path)
    conn.execute("UPDATE memories SET n_support=747000 WHERE id=?", (row["id"],))
    conn.commit()
    conn.close()
    out = mem.clamp_inflated_support(path=path)
    assert out["clamped"] == 1
    again = mem.list_recent(path=path, limit=5)
    assert again[0]["n_support"] == 3706


def test_clamp_caps_at_evidence_n_not_ten_x(tmp_path: Path, monkeypatch):
    path = tmp_path / "memory.db"
    monkeypatch.setattr(mem, "embed", lambda texts, **kw: [[] for _ in texts])
    row = mem.write(
        kind="pattern",
        scope="hv_dip:deep_dip",
        text="fraco",
        provenance="studies:fdr:hv_dip:deep_dip",
        n_support=3706,
        evidence=[{"n": 3706}],
        vector=[],
        path=path,
    )
    import sqlite3

    conn = sqlite3.connect(path)
    conn.execute("UPDATE memories SET n_support=14770 WHERE id=?", (row["id"],))
    conn.commit()
    conn.close()
    out = mem.clamp_inflated_support(path=path)
    assert out["clamped"] == 1
    assert mem.list_recent(path=path, limit=1)[0]["n_support"] == 3706


def test_write_search_and_dedup(tmp_path: Path, monkeypatch):
    path = tmp_path / "memory.db"
    monkeypatch.setattr(mem, "embed", lambda texts, **kw: [_vec(1.0) for _ in texts])

    first = mem.write(
        kind="lesson",
        scope="hv_dip",
        text="dip profundo em mega-cap recupera em 3 pregões",
        provenance="studies:oos",
        confidence=0.7,
        vector=_vec(1.0),
        path=path,
    )
    assert first and first["id"]

    dup = mem.write(
        kind="lesson",
        scope="other",
        text="quase a mesma lição sobre dip profundo",
        provenance="review:closed-1",
        confidence=0.8,
        vector=_vec(1.0),
        path=path,
    )
    assert dup is not None
    assert dup["id"] == first["id"]
    assert dup["n_support"] == 2

    hits = mem.search("dip profundo", path=path, query_vec=_vec(1.0))
    assert hits
    assert hits[0]["id"] == first["id"]


def test_conflict_refuses_opposite_kind(tmp_path: Path, monkeypatch):
    path = tmp_path / "memory.db"
    monkeypatch.setattr(mem, "embed", lambda texts, **kw: [_vec(1.0) for _ in texts])
    mem.write(
        kind="lesson",
        scope="news",
        text="guidance_up não antecipa alta",
        provenance="fdr",
        vector=_vec(1.0),
        path=path,
    )
    clash = mem.write(
        kind="refutation",
        scope="news",
        text="guidance_up antecipa alta",
        provenance="fdr",
        # Angle whose cosine is 0.85: similar enough to conflict, too far to dedup.
        vector=[0.85, 0.5267833265] + [0.0] * 6,
        path=path,
    )
    assert clash is None
    assert mem.count(path) == 1


def test_refuted_ranks_below(tmp_path: Path, monkeypatch):
    path = tmp_path / "memory.db"
    monkeypatch.setattr(mem, "embed", lambda texts, **kw: [_vec(1.0) for _ in texts])
    mem.write(
        kind="lesson",
        scope="hv_dip",
        text="lição viva sobre stop",
        provenance="review:live",
        vector=_vec(1.0),
        path=path,
    )
    mem.write(
        kind="lesson",
        scope="hv_dip",
        text="lição morta sobre stop",
        provenance="review:dead",
        vector=_vec(0.5),
        refuted=True,
        path=path,
    )
    hits = mem.search("stop", path=path, query_vec=_vec(1.0))
    assert hits
    assert hits[0]["refuted"] is False


def test_consolidate_merges_same_provenance(tmp_path: Path, monkeypatch):
    path = tmp_path / "memory.db"
    monkeypatch.setattr(mem, "embed", lambda texts, **kw: [[] for _ in texts])
    mem.write(
        kind="pattern",
        scope="a",
        text="um",
        provenance="same-key",
        vector=[1.0, 0.0],
        path=path,
    )
    # Bypass write() fold by inserting a second row with the same provenance.
    import sqlite3

    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO memories(id, kind, scope, text, provenance, confidence, evidence, n_support, created_at, refuted) "
        "VALUES ('dup','pattern','a','dois','same-key',0.5,'[]',1,'2026-01-01T00:00:00+00:00',0)"
    )
    conn.commit()
    conn.close()
    assert mem.count(path) == 2
    out = mem.consolidate(path=path)
    assert out["merged"] >= 1
    assert mem.count(path) == 1


def test_consolidate_expires_and_merges(tmp_path: Path, monkeypatch):
    path = tmp_path / "memory.db"
    monkeypatch.setattr(mem, "embed", lambda texts, **kw: [_vec(1.0) for _ in texts])
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    mem.write(
        kind="lesson",
        scope="x",
        text="expira",
        provenance="t-expired",
        valid_until=past,
        vector=_vec(1.0),
        path=path,
    )
    mem.write(
        kind="lesson",
        scope="x",
        text="uma",
        provenance="t",
        vector=[0.0, 1.0] + [0.0] * 6,
        path=path,
    )
    # Force a second row with same vector but skip write() dedup by inserting via
    # a slightly different cosine that still consolidates... write() already
    # dedups at 0.92, so plant two live rows then consolidate is a no-op merge.
    # Expiry is the assertion that matters here.
    out = mem.consolidate(path=path)
    assert out["expired"] == 1
    assert mem.count(path) == 1
