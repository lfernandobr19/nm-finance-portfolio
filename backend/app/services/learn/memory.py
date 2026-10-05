"""Evolving memory: SQLite + FTS5 + embeddings, conservative writes, hybrid search.

Lessons are written only after they have a provenance (FDR/OOS/resolved
forecast). Retrieval is hybrid (cosine + FTS5) because that combination
consistently beats vectors alone on long-memory recall.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from app.config import get_settings
from app.services.learn.embedding import cosine, embed

logger = logging.getLogger("fiidesk.learn.memory")

DEFAULT_PATH = Path(".cache/fiidesk/memory.db")
DEDUP_COSINE = 0.92
CONFLICT_COSINE = 0.80


def _path() -> Path:
    settings = get_settings()
    raw = getattr(settings, "learn_memory_path", None)
    return Path(raw) if raw else DEFAULT_PATH


def _connect(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or _path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            scope TEXT NOT NULL,
            text TEXT NOT NULL,
            provenance TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.5,
            evidence TEXT NOT NULL DEFAULT '[]',
            n_support INTEGER NOT NULL DEFAULT 1,
            valid_until TEXT,
            created_at TEXT NOT NULL,
            refuted INTEGER NOT NULL DEFAULT 0
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
            text, content='memories', content_rowid='rowid'
        );
        CREATE TABLE IF NOT EXISTS memory_emb (
            memory_id TEXT PRIMARY KEY,
            vec TEXT NOT NULL,
            dim INTEGER NOT NULL,
            FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE
        );
        CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
            INSERT INTO memories_fts(rowid, text) VALUES (new.rowid, new.text);
        END;
        CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, text)
            VALUES ('delete', old.rowid, old.text);
        END;
        CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, text)
            VALUES ('delete', old.rowid, old.text);
            INSERT INTO memories_fts(rowid, text) VALUES (new.rowid, new.text);
        END;
        """
    )
    return conn


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    raw = data.get("evidence")
    if isinstance(raw, str):
        try:
            data["evidence"] = json.loads(raw)
        except json.JSONDecodeError:
            data["evidence"] = []
    data["refuted"] = bool(data.get("refuted"))
    return data


def _all_with_vectors(conn: sqlite3.Connection) -> list[tuple[dict[str, Any], list[float]]]:
    rows = conn.execute(
        "SELECT m.*, e.vec FROM memories m LEFT JOIN memory_emb e ON e.memory_id = m.id"
    ).fetchall()
    out: list[tuple[dict[str, Any], list[float]]] = []
    for row in rows:
        item = _row_dict(row)
        vec: list[float] = []
        raw = row["vec"] if "vec" in row.keys() else None
        if raw:
            try:
                vec = [float(x) for x in json.loads(raw)]
            except (TypeError, json.JSONDecodeError):
                vec = []
        out.append((item, vec))
    return out


def write(
    *,
    kind: str,
    scope: str,
    text: str,
    provenance: str,
    confidence: float = 0.5,
    evidence: list[Any] | None = None,
    n_support: int = 1,
    valid_until: str | None = None,
    refuted: bool = False,
    vector: Sequence[float] | None = None,
    path: Path | None = None,
) -> dict[str, Any] | None:
    """Insert a lesson, or fold it into a near-duplicate. Conflicts are refused."""
    text = (text or "").strip()
    if not text or not provenance:
        return None

    conn = _connect(path)
    try:
        items = _all_with_vectors(conn)
        for existing, _ev in items:
            same_slot = (
                existing["kind"] == kind
                and existing["scope"] == scope
                and existing["provenance"] == provenance
            )
            if same_slot:
                # Same finding restated (harvest re-run, copy drift): keep the
                # larger sample. Never add n on every tick.
                n = max(int(existing["n_support"]), int(n_support))
                conf = max(float(existing["confidence"]), float(confidence))
                conn.execute(
                    "UPDATE memories SET text=?, evidence=?, n_support=?, "
                    "confidence=?, refuted=? WHERE id=?",
                    (
                        text,
                        json.dumps(list(evidence or existing.get("evidence") or [])),
                        n,
                        conf,
                        1 if refuted else int(existing.get("refuted") or 0),
                        existing["id"],
                    ),
                )
                conn.commit()
                existing["text"] = text
                existing["n_support"] = n
                existing["confidence"] = conf
                existing["refuted"] = bool(refuted or existing.get("refuted"))
                return existing

        vec = list(vector) if vector is not None else None
        if vec is None:
            try:
                embedded = embed([text], timeout=8.0)
                vec = embedded[0] if embedded else []
            except Exception:
                logger.exception("memory embed failed")
                vec = []

        for existing, ev in items:
            if not ev or not vec:
                continue
            sim = cosine(vec, ev)
            if sim >= DEDUP_COSINE:
                incoming = max(1, int(n_support))
                if existing["scope"] == scope:
                    n = max(int(existing["n_support"]), incoming)
                elif existing["provenance"] != provenance and incoming <= 1:
                    n = int(existing["n_support"]) + 1
                else:
                    n = max(int(existing["n_support"]), incoming)
                conf = max(float(existing["confidence"]), float(confidence))
                conn.execute(
                    "UPDATE memories SET n_support=?, confidence=? WHERE id=?",
                    (n, conf, existing["id"]),
                )
                conn.commit()
                existing["n_support"] = n
                existing["confidence"] = conf
                return existing
            if sim >= CONFLICT_COSINE and existing["kind"] != kind:
                logger.info("memory conflict skipped kind=%s vs %s", kind, existing["kind"])
                return None

        mid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO memories(
                id, kind, scope, text, provenance, confidence, evidence,
                n_support, valid_until, created_at, refuted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mid,
                kind,
                scope,
                text,
                provenance,
                float(confidence),
                json.dumps(list(evidence or [])),
                int(n_support),
                valid_until,
                now,
                1 if refuted else 0,
            ),
        )
        if vec:
            conn.execute(
                "INSERT INTO memory_emb(memory_id, vec, dim) VALUES (?, ?, ?)",
                (mid, json.dumps(vec), len(vec)),
            )
        conn.commit()
        return {
            "id": mid,
            "kind": kind,
            "scope": scope,
            "text": text,
            "provenance": provenance,
            "confidence": float(confidence),
            "evidence": list(evidence or []),
            "n_support": int(n_support),
            "valid_until": valid_until,
            "created_at": now,
            "refuted": bool(refuted),
        }
    finally:
        conn.close()


def search(
    query: str,
    *,
    limit: int = 5,
    path: Path | None = None,
    query_vec: Sequence[float] | None = None,
) -> list[dict[str, Any]]:
    """Hybrid rank: 0.6 cosine + 0.4 FTS presence, refuted items sink."""
    query = (query or "").strip()
    if not query:
        return []
    conn = _connect(path)
    try:
        fts_ids: set[str] = set()
        try:
            rows = conn.execute(
                "SELECT m.id FROM memories_fts f "
                "JOIN memories m ON m.rowid = f.rowid "
                "WHERE memories_fts MATCH ? LIMIT 50",
                (query,),
            ).fetchall()
            fts_ids = {r["id"] for r in rows}
        except sqlite3.OperationalError:
            fts_ids = set()

        vec = list(query_vec) if query_vec is not None else []
        if not vec:
            try:
                embedded = embed([query])
                vec = embedded[0] if embedded else []
            except Exception:
                vec = []

        scored: list[tuple[float, dict[str, Any]]] = []
        for item, ev in _all_with_vectors(conn):
            cos = cosine(vec, ev) if vec and ev else 0.0
            lexical = 1.0 if item["id"] in fts_ids else 0.0
            score = 0.6 * cos + 0.4 * lexical
            if item["refuted"]:
                score *= 0.25
            if score <= 0:
                continue
            item["score"] = round(score, 4)
            scored.append((score, item))
        scored.sort(key=lambda x: -x[0])
        return [item for _, item in scored[:limit]]
    finally:
        conn.close()


def prompt_block(query: str, *, limit: int = 4, path: Path | None = None) -> str:
    hits = search(query, limit=limit, path=path)
    if not hits:
        return ""
    lines = [
        "Lições acumuladas (não contradiga as REFUTADAS; não reproponha o que já foi refutado):"
    ]
    for h in hits:
        tag = "REFUTADA" if h.get("refuted") else "válida"
        lines.append(f"- [{tag} {h.get('kind')}/{h.get('scope')}] {h.get('text')}")
    return "\n".join(lines)


def list_recent(*, limit: int = 50, path: Path | None = None) -> list[dict[str, Any]]:
    """Chronological lessons for the memory browser. No embedding call."""
    conn = _connect(path)
    try:
        rows = conn.execute(
            "SELECT id, kind, scope, text, provenance, confidence, n_support, "
            "refuted, created_at FROM memories ORDER BY created_at DESC LIMIT ?",
            (max(1, min(int(limit), 200)),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def count(path: Path | None = None) -> int:
    conn = _connect(path)
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM memories").fetchone()
        return int(row["n"] if row else 0)
    finally:
        conn.close()


def reindex(*, path: Path | None = None, batch: int = 32) -> dict[str, int]:
    """Backfill embeddings in one batched /api/embed call per chunk.

    Context7: ``input`` is a list; one HTTP round-trip per batch, not per row.
    """
    conn = _connect(path)
    updated = 0
    n = 0
    try:
        rows = conn.execute("SELECT id, text FROM memories ORDER BY created_at").fetchall()
        n = len(rows)
        texts = [r["text"] for r in rows]
        ids = [r["id"] for r in rows]
        for start in range(0, n, batch):
            chunk = texts[start : start + batch]
            try:
                vectors = embed(chunk, timeout=60.0)
            except Exception:
                logger.exception("memory reindex embed failed")
                continue
            for mid, vec in zip(ids[start : start + batch], vectors):
                if not vec:
                    continue
                conn.execute("DELETE FROM memory_emb WHERE memory_id=?", (mid,))
                conn.execute(
                    "INSERT INTO memory_emb(memory_id, vec, dim) VALUES (?, ?, ?)",
                    (mid, json.dumps(vec), len(vec)),
                )
                updated += 1
        conn.commit()
    finally:
        conn.close()
    logger.info("memory reindex updated=%d", updated)
    return {"updated": updated, "n": n}


def consolidate(*, path: Path | None = None) -> dict[str, int]:
    """Merge near-duplicates, expire dated lessons, bump support on recurrences."""
    conn = _connect(path)
    merged = expired = 0
    try:
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            "SELECT id FROM memories WHERE valid_until IS NOT NULL AND valid_until < ?",
            (now,),
        )
        ids = [r["id"] for r in cur.fetchall()]
        for mid in ids:
            conn.execute("DELETE FROM memory_emb WHERE memory_id=?", (mid,))
            conn.execute("DELETE FROM memories WHERE id=?", (mid,))
            expired += 1

        items = _all_with_vectors(conn)
        consumed: set[str] = set()
        by_slot: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for item, _ev in items:
            by_slot.setdefault(
                (item["kind"], item["scope"], item["provenance"]),
                [],
            ).append(item)
        for group in by_slot.values():
            if len(group) < 2:
                continue
            group.sort(key=lambda r: -int(r["n_support"]))
            winner = group[0]
            for loser in group[1:]:
                if loser["id"] in consumed:
                    continue
                n = max(int(winner["n_support"]), int(loser["n_support"]))
                conf = max(float(winner["confidence"]), float(loser["confidence"]))
                conn.execute(
                    "UPDATE memories SET n_support=?, confidence=? WHERE id=?",
                    (n, conf, winner["id"]),
                )
                conn.execute("DELETE FROM memory_emb WHERE memory_id=?", (loser["id"],))
                conn.execute("DELETE FROM memories WHERE id=?", (loser["id"],))
                winner["n_support"] = n
                winner["confidence"] = conf
                consumed.add(loser["id"])
                merged += 1
        items = [(a, va) for a, va in items if a["id"] not in consumed]
        for i, (a, va) in enumerate(items):
            if a["id"] in consumed or not va:
                continue
            for b, vb in items[i + 1 :]:
                if b["id"] in consumed or not vb:
                    continue
                if cosine(va, vb) < DEDUP_COSINE:
                    continue
                if a["kind"] != b["kind"]:
                    continue
                winner, loser = (a, b) if a["n_support"] >= b["n_support"] else (b, a)
                n = max(int(winner["n_support"]), int(loser["n_support"]))
                conf = max(float(winner["confidence"]), float(loser["confidence"]))
                conn.execute(
                    "UPDATE memories SET n_support=?, confidence=? WHERE id=?",
                    (n, conf, winner["id"]),
                )
                conn.execute("DELETE FROM memory_emb WHERE memory_id=?", (loser["id"],))
                conn.execute("DELETE FROM memories WHERE id=?", (loser["id"],))
                consumed.add(loser["id"])
                merged += 1
        conn.commit()
    finally:
        conn.close()
    clamped = clamp_inflated_support(path=path).get("clamped", 0)
    logger.info(
        "memory consolidate merged=%d expired=%d clamped=%d",
        merged,
        expired,
        clamped,
    )
    return {"merged": merged, "expired": expired, "clamped": clamped}


def _evidence_n(evidence: Any) -> int | None:
    if isinstance(evidence, str):
        try:
            evidence = json.loads(evidence)
        except json.JSONDecodeError:
            return None
    if not isinstance(evidence, list) or not evidence:
        return None
    first = evidence[0]
    if not isinstance(first, dict):
        return None
    raw = first.get("n")
    if raw is None:
        raw = first.get("n_support")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _text_n(text: str | None) -> int | None:
    if not text:
        return None
    marker = "(n="
    start = text.find(marker)
    if start < 0:
        return None
    tail = text[start + len(marker) :]
    digits = []
    for ch in tail:
        if ch.isdigit():
            digits.append(ch)
        else:
            break
    if not digits:
        return None
    n = int("".join(digits))
    return n if n > 0 else None


def _honest_n(row: sqlite3.Row) -> int | None:
    ev_n = _evidence_n(row["evidence"])
    if ev_n is not None:
        return ev_n
    text_n = _text_n(row["text"] if "text" in row.keys() else None)
    if text_n is not None:
        return text_n
    prov = str(row["provenance"] if "provenance" in row.keys() else "")
    if prov.startswith("insight:"):
        return 1
    return None


def clamp_inflated_support(*, path: Path | None = None, factor: int = 1) -> dict[str, int]:
    """Cap n_support to the finding n. Never exceed evidence/text n."""
    conn = _connect(path)
    clamped = 0
    try:
        rows = conn.execute(
            "SELECT id, scope, provenance, n_support, evidence, text FROM memories"
        ).fetchall()
        for row in rows:
            cap = _honest_n(row)
            if cap is None:
                continue
            current = int(row["n_support"] or 0)
            if current > factor * cap:
                conn.execute(
                    "UPDATE memories SET n_support=? WHERE id=?",
                    (cap, row["id"]),
                )
                clamped += 1
                logger.info(
                    "memory clamp %s %s → %s",
                    row["scope"],
                    current,
                    cap,
                )
        conn.commit()
    finally:
        conn.close()
    return {"clamped": clamped}


def status(path: Path | None = None) -> dict[str, Any]:
    return {"n": count(path), "path": str(path or _path())}


__all__ = [
    "DEDUP_COSINE",
    "write",
    "search",
    "list_recent",
    "prompt_block",
    "count",
    "reindex",
    "consolidate",
    "clamp_inflated_support",
    "status",
]
