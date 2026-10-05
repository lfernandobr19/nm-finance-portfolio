"""Research queue: persist, resume, budget, every task records a trial."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.brapi_client import Bar
from app.services.learn import research as res
from app.services.learn import trials
from app.services.studies.models import StudyQuery


def test_queue_persists_and_respects_budget(tmp_path: Path, monkeypatch):
    path = tmp_path / "q.db"
    monkeypatch.setattr(res, "_QUEUE", path)
    res.enqueue("reflect", path=path)
    res.enqueue("news_mining", path=path)
    assert len(res.pending(path=path)) == 2

    ran = []

    def handler(db, payload):
        ran.append("x")
        return {"ok": True}

    # Tiny budget: first task spends it all via a fake clock.
    times = iter([0.0, 0.0, 10.0, 10.0, 10.0])
    monkeypatch.setattr(res.time, "monotonic", lambda: next(times, 10.0))

    out = res.run_queue(
        object(),
        budget_seconds=1.0,
        path=path,
        handlers={t: handler for t in res.TASKS},
    )
    assert len(out["ran"]) == 1
    leftover = res.pending(path=path)
    assert leftover  # second task still queued


def test_every_handler_records_trial(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(trials, "_TRIALS_PATH", tmp_path / "trials.json")
    before = trials.all_counts().get("research:reflect") or 0
    monkeypatch.setattr(
        "app.services.learn.ledger.ledger_summary",
        lambda db: {},
    )
    out = res.task_reflect(object(), {})
    assert out["n_trials"] == before + 1
    assert (trials.all_counts().get("research:reflect") or 0) == before + 1


def _dip_bars() -> list[Bar]:
    d0 = datetime(2024, 1, 2, tzinfo=timezone.utc)
    closes = [100.0] * 10 + [80.0, 85.0, 90.0, 95.0, 100.0, 105.0]
    return [
        Bar(
            date=d0 + timedelta(days=i),
            open=float(c),
            high=float(c) * 1.02,
            low=float(c) * 0.98,
            close=float(c),
            volume=1_000_000.0,
        )
        for i, c in enumerate(closes)
    ]


def test_deep_backtest_sweeps_horizons_and_unused_metrics(tmp_path, monkeypatch):
    monkeypatch.setattr(trials, "_TRIALS_PATH", tmp_path / "trials.json")
    monkeypatch.setattr("app.services.learn.harvest.harvest_deep_findings", lambda *a, **k: 0)
    query = StudyQuery(
        id="deep_dip",
        label="dip",
        channel="hv_dip",
        fingerprint="deep_dip",
        horizon=10,
        target_r=2.0,
        params={"min_dip_pct": 15.0, "stop_pct": 8.0, "lookback": 10},
    )
    out = res.task_deep_backtest(
        object(),
        {
            "bars": {"WIN": _dip_bars()},
            "queries": [query],
            "horizons": (5, 10, 20, 40),
        },
    )
    assert out["family"] == "research:deep_backtest"
    assert out["horizons"] == [5, 10, 20, 40]
    assert set(out["metrics"]) == {"p_higher", "recovery", "gap_hit"}
    assert out["n_findings"] >= 1
    assert out["n_trials"] == 4


def test_saturated_research_does_not_block_heartbeat(tmp_path, monkeypatch):
    """Research on its own queue/thread cannot stall the trading heartbeat.

    Context7/arq: isolation is ``queue_name``, not job priority. This test
    proves the Python side shares no lock — a 1.2s research tick still lets
    ``write_heartbeat`` finish in well under that.
    """
    path = tmp_path / "q.db"
    monkeypatch.setattr(res, "_QUEUE", path)
    res.enqueue("reflect", path=path)

    def slow(db, payload):
        time.sleep(1.2)
        return {"ok": True}

    started = threading.Event()

    def run():
        started.set()
        res.run_queue(
            object(),
            budget_seconds=5.0,
            path=path,
            handlers={t: slow for t in res.TASKS},
        )

    worker = threading.Thread(target=run)
    worker.start()
    assert started.wait(timeout=1.0)

    monkeypatch.setattr(
        "app.services.worker_heartbeat.probe_ollama",
        lambda: ("down", None, None),
    )
    hb_path = tmp_path / "hb.json"
    monkeypatch.setattr("app.services.worker_heartbeat.HEARTBEAT_PATH", hb_path)

    monkeypatch.setattr("app.workers.runner.run_hv_dip_exit_if_due", lambda: None)
    t0 = time.monotonic()
    from app.services.worker_heartbeat import write_heartbeat
    from app.workers.jobs import _run_exit_watch

    write_heartbeat("ok")
    _run_exit_watch()
    elapsed = time.monotonic() - t0
    worker.join(timeout=3.0)
    assert elapsed < 0.6
    assert hb_path.exists()
