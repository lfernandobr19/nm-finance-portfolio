"""Continuous research queue. Runs on its own ARQ worker so it cannot starve trading.

Every task registers a hypothesis in ``trial_registry`` before it looks at data.
Budget is wall-clock seconds per tick; leftover work stays queued.
Never escalates to Groq.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.learn.trials import record_trials

logger = logging.getLogger("fiidesk.learn.research")

_QUEUE = Path(".cache/fiidesk/research_queue.db")

TASKS = (
    "deep_backtest",
    "pattern_mining",
    "news_mining",
    "reflect",
)


def _budget() -> float:
    settings = get_settings()
    return float(getattr(settings, "learn_research_budget_seconds", None) or 45.0)


def _connect(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or _QUEUE
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            result TEXT
        )
        """
    )
    return conn


def enqueue(task: str, payload: dict[str, Any] | None = None, *, path: Path | None = None) -> int:
    if task not in TASKS:
        raise ValueError(f"unknown research task: {task}")
    conn = _connect(path)
    try:
        cur = conn.execute(
            "INSERT INTO queue(task, payload, created_at) VALUES (?, ?, ?)",
            (task, json.dumps(payload or {}), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def pending(*, path: Path | None = None) -> list[dict[str, Any]]:
    conn = _connect(path)
    try:
        rows = conn.execute(
            "SELECT * FROM queue WHERE status='pending' ORDER BY id ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def ensure_seed(*, path: Path | None = None) -> None:
    """Keep a rotating set of work so the worker is never idle on an empty queue."""
    if pending(path=path):
        return
    for task in TASKS:
        enqueue(task, path=path)


def _mark(conn: sqlite3.Connection, row_id: int, status: str, result: dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE queue SET status=?, finished_at=?, result=? WHERE id=?",
        (status, now, json.dumps(result, default=str), row_id),
    )


def task_deep_backtest(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Horizon sweep + unused metrics (recovery, gap_hit). Never promotes params."""
    from app.services.learn.harvest import harvest_deep_findings
    from app.services.studies.analog import DEEP_HORIZONS, sweep_horizons
    from app.services.studies.catalog import catalog_queries
    from app.services.studies.models import StudyQuery

    bars = payload.get("bars")
    if not isinstance(bars, dict) or not bars:
        try:
            from app.services.studies.runner import _hv_dip_bars

            bars = _hv_dip_bars()
        except Exception:
            logger.exception("deep_backtest bars failed")
            bars = {}

    queries = payload.get("queries")
    if not isinstance(queries, list) or not queries:
        queries = [q for q in catalog_queries() if q.channel == "hv_dip"]
    else:
        queries = [
            q if isinstance(q, StudyQuery) else StudyQuery.model_validate(q)
            for q in queries
        ]

    raw_h = payload.get("horizons")
    horizons = tuple(int(h) for h in raw_h) if raw_h else DEEP_HORIZONS
    n_combos = max(1, len(queries) * len(horizons))
    n_trials = record_trials("research:deep_backtest", n_combos)

    findings = sweep_horizons(bars, queries, horizons=horizons) if bars else []
    harvested = harvest_deep_findings(findings)
    return {
        "n_findings": len(findings),
        "n_harvested": harvested,
        "n_trials": n_trials,
        "horizons": list(horizons),
        "metrics": ["p_higher", "recovery", "gap_hit"],
        "family": "research:deep_backtest",
    }


def task_pattern_mining(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.studies.runner import run_studies

    n_trials = record_trials("research:pattern_mining", 1)
    snap = run_studies(db, propose=True, insights=False)
    return {
        "n_results": len(snap.get("results") or []),
        "n_trials": n_trials,
        "family": "research:pattern_mining",
    }


def task_news_mining(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.learn.news_whitelist import refresh_whitelist
    from app.services.llm_calibrate import calibrate_news_outcomes

    from app.services.learn.calibration import refit_news_by_type
    from app.services.learn.harvest import harvest_news

    n_trials = record_trials("research:news_mining", 1)
    cal = calibrate_news_outcomes(db, limit=200)
    white = refresh_whitelist(db)
    harvested = harvest_news(white)
    try:
        platts = refit_news_by_type(db)
    except Exception:
        logger.exception("news_mining platts failed")
        platts = {}
    return {
        "labeled": cal.get("n_labeled"),
        "allowed": white.get("allowed"),
        "n_harvested": harvested,
        "n_platts": platts.get("n_types"),
        "n_trials": n_trials,
        "family": "research:news_mining",
    }


def task_reflect(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.learn.ledger import ledger_summary
    from app.services.learn.memory import write

    n_trials = record_trials("research:reflect", 1)
    summary = ledger_summary(db)
    written = 0
    for source, stats in summary.items():
        brier = stats.get("brier")
        if brier is None or stats.get("resolved", 0) < 20:
            continue
        if brier > 0.25:
            row = write(
                kind="correction",
                scope=source,
                text=(
                    f"{source} está mal calibrado: Brier {brier:.3f} em "
                    f"{stats['resolved']} previsões (hit_rate={stats.get('hit_rate')}). "
                    "Desconfie da confiança crua desta fonte."
                ),
                provenance="research:reflect",
                confidence=min(0.9, 0.4 + brier),
                evidence=[{"source": source, **stats}],
            )
            if row:
                written += 1
    return {"written": written, "n_trials": n_trials, "family": "research:reflect"}


_HANDLERS: dict[str, Callable[[Session, dict[str, Any]], dict[str, Any]]] = {
    "deep_backtest": task_deep_backtest,
    "pattern_mining": task_pattern_mining,
    "news_mining": task_news_mining,
    "reflect": task_reflect,
}


def run_queue(
    db: Session,
    *,
    budget_seconds: float | None = None,
    path: Path | None = None,
    handlers: dict[str, Callable] | None = None,
) -> dict[str, Any]:
    """Drain pending tasks until the wall-clock budget is spent."""
    budget = float(budget_seconds if budget_seconds is not None else _budget())
    handlers = handlers or _HANDLERS
    ensure_seed(path=path)
    started = time.monotonic()
    ran: list[str] = []
    conn = _connect(path)
    try:
        rows = conn.execute(
            "SELECT * FROM queue WHERE status='pending' ORDER BY id ASC"
        ).fetchall()
        for row in rows:
            if time.monotonic() - started >= budget:
                break
            conn.execute(
                "UPDATE queue SET status='running', started_at=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), row["id"]),
            )
            conn.commit()
            payload = {}
            try:
                payload = json.loads(row["payload"] or "{}")
            except json.JSONDecodeError:
                payload = {}
            handler = handlers.get(row["task"])
            try:
                result = handler(db, payload) if handler else {"skipped": "no_handler"}
                _mark(conn, row["id"], "done", result if isinstance(result, dict) else {})
                ran.append(row["task"])
            except Exception as exc:  # noqa: BLE001
                logger.exception("research task %s failed", row["task"])
                _mark(conn, row["id"], "error", {"error": str(exc)})
            conn.commit()
    finally:
        conn.close()
    return {
        "ran": ran,
        "elapsed": round(time.monotonic() - started, 3),
        "budget": budget,
    }


def status(*, path: Path | None = None) -> dict[str, Any]:
    conn = _connect(path)
    try:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM queue GROUP BY status"
        ).fetchall()
        return {r["status"]: r["n"] for r in rows}
    finally:
        conn.close()


__all__ = [
    "TASKS",
    "enqueue",
    "pending",
    "ensure_seed",
    "run_queue",
    "status",
    "task_deep_backtest",
    "task_pattern_mining",
    "task_news_mining",
    "task_reflect",
]
