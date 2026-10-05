"""Orchestrator: run catalog queries over cached bars, write snapshot + guards.

Runs inside the nightly ``job_intelligence`` (06:00 UTC). Each channel fetches
from its own cache (Yahoo ``.cache/market``, BRAPI ``.cache/brapi``, and the
``day_trade_bars`` table). Failures per-channel degrade gracefully so a network
blip never kills the pulse.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.services.learn.ledger import record_forecast_once
from app.services.studies.analog import analyze_sessions, run_universe
from app.services.studies.apply import evaluate, write_guards
from app.services.studies.catalog import catalog_queries
from app.services.studies.insight import generate_insights
from app.services.studies.models import StudyQuery, StudyResult, StudySnapshot, now_iso
from app.services.studies.propose import propose_queries

logger = logging.getLogger("fiidesk.studies.runner")

SNAPSHOT_PATH = Path(".cache/fiidesk/studies.json")
EXTRA_PATH = Path(".cache/fiidesk/study_queries_extra.json")
UNIVERSE_CAP = 60  # bound the universe sweep per daily channel
# Channels whose outcomes the forecast resolver can actually price.
_LEDGER_CHANNELS = {"hv_dip", "day_trade"}
EXTRA_CAP = 20  # bound the persisted proposal list so it never grows unbounded


def _hv_dip_bars() -> dict[str, list[Any]]:
    from app.services.hv_dip.universe import hv_dip_tickers
    from app.services.market_data import MarketDataClient

    client = MarketDataClient()
    tickers = hv_dip_tickers()[:UNIVERSE_CAP]
    return client.fetch_daily_bars_many(tickers)


def _swing_bars() -> dict[str, list[Any]]:
    from app.services.brapi_client import BrapiClient
    from app.services.swing.universe import swing_tickers

    client = BrapiClient()
    return {t: client.fetch_daily_bars(t) for t in swing_tickers()}


def _day_trade_sessions(db: Session) -> list[dict[str, Any]]:
    from app.services.day_trade.learning import load_sessions

    return load_sessions(db)


def _load_extra_queries() -> list[StudyQuery]:
    """Persisted 7B proposals that become computable catalog entries on later runs."""
    try:
        data = json.loads(EXTRA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    out: list[StudyQuery] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            out.append(StudyQuery.model_validate(item))
        except ValidationError:
            continue
    return out


def _save_extra_queries(queries: list[StudyQuery]) -> None:
    EXTRA_PATH.parent.mkdir(parents=True, exist_ok=True)
    bounded = queries[-EXTRA_CAP:]
    EXTRA_PATH.write_text(
        json.dumps([q.model_dump() for q in bounded], indent=2, default=str),
        encoding="utf-8",
    )


def _load_previous_insights() -> list[Any]:
    """Last snapshot's insights, so a failed/regeneration-off run never wipes the
    panel back to empty (transient LLM rate-limit/timeout)."""
    try:
        data = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    prev = data.get("insights")
    return prev if isinstance(prev, list) else []


def _run_channel(query, *, bars: dict[str, list[Any]]) -> list[StudyResult]:
    return run_universe(bars, query)


def _run_day_trade(query, sessions: list[dict[str, Any]]) -> list[StudyResult]:
    if not sessions:
        return []
    m = analyze_sessions(sessions, query)
    if m["n"] == 0:
        return []
    oos = m.pop("oos", None) or {}
    return [
        StudyResult(
            query_id=query.id,
            label=query.label,
            channel=query.channel,
            fingerprint=query.fingerprint,
            ticker="UNIVERSE",
            oos_n=oos.get("n", 0),
            oos_p_higher=oos.get("p_higher"),
            oos_p_stop_first=oos.get("p_stop_first"),
            oos_expectancy_r=oos.get("expectancy_r"),
            **m,
        )
    ]


def _record_study_forecasts(
    db: Session,
    queries: list[StudyQuery],
    results: list[StudyResult],
) -> int:
    """Put each per-ticker ``p_higher`` on record so studies can be scored.

    A study that is never graded is an opinion. Universe aggregates are skipped:
    they describe a basket, so there is no single forward return that settles
    them. One forecast per (query, ticker, day) keeps the hourly re-runs from
    stacking correlated rows.
    """
    horizons = {q.id: int(q.horizon or 10) for q in queries}
    today = datetime.now(timezone.utc).date().isoformat()
    written = 0
    for r in results:
        if r.ticker == "UNIVERSE" or r.p_higher is None:
            continue
        if r.channel not in _LEDGER_CHANNELS:
            # The resolver prices tickers through the USD daily-bar client, which
            # returns nothing for B3 symbols. Recording a forecast nothing can
            # ever grade would just grow an unresolvable queue.
            continue
        row = record_forecast_once(
            db,
            ref_id=f"{r.query_id}:{r.ticker}:{today}",
            source="studies",
            kind=r.fingerprint or r.query_id,
            ticker=r.ticker,
            p_pred=float(r.p_higher),
            horizon_days=horizons.get(r.query_id, 10),
            features={
                "direction": "up",
                "query_id": r.query_id,
                "channel": r.channel,
                "n": r.n,
                "vs_universe": r.vs_universe,
                "expectancy_r": r.expectancy_r,
            },
        )
        if row is not None:
            written += 1
    if written:
        logger.info("studies recorded %d forecasts in the ledger", written)
    return written


def run_studies(db: Session, *, propose: bool = True, insights: bool = True) -> dict[str, Any]:
    base = catalog_queries()
    extra = _load_extra_queries()
    base_ids = {q.id for q in base}
    # Extra (persisted 7B proposals) are computed exactly like catalog queries.
    queries = [*base, *[q for q in extra if q.id not in base_ids]]
    results: list[StudyResult] = []

    bars_hv: dict[str, list[Any]] | None = None
    bars_swing: dict[str, list[Any]] | None = None
    for q in queries:
        try:
            if q.channel == "hv_dip":
                if bars_hv is None:
                    bars_hv = _hv_dip_bars()
                results.extend(_run_channel(q, bars=bars_hv))
            elif q.channel == "swing":
                if bars_swing is None:
                    bars_swing = _swing_bars()
                results.extend(_run_channel(q, bars=bars_swing))
            elif q.channel == "day_trade":
                results.extend(_run_day_trade(q, _day_trade_sessions(db)))
        except Exception as exc:  # noqa: BLE001 — never kill the pulse
            logger.warning("studies channel %s failed: %s", q.channel, exc)

    # Propose new questions (LLM, capped). New valid proposals are persisted so
    # they become computable (get results/guards) on subsequent runs instead of
    # being display-only.
    proposed: list[StudyQuery] = []
    if propose:
        known_ids = {q.id for q in queries}
        proposed = propose_queries(sorted(known_ids))
        if proposed:
            extra_ids = {q.id for q in extra}
            new = [q for q in proposed if q.id not in known_ids and q.id not in extra_ids]
            if new:
                _save_extra_queries([*extra, *new])

    _record_study_forecasts(db, queries, results)

    eval_out = evaluate(results)

    # Grounded LLM insights (digest → text). Best-effort; never kills the pulse.
    # Preserve the previous insights when regeneration is off or the LLM fails,
    # so a transient rate-limit/timeout never wipes the panel back to empty.
    insight_list: list[Any] = _load_previous_insights()
    if insights:
        fresh: list[Any] = []
        try:
            fresh = generate_insights(db, results=results)
        except Exception as exc:  # noqa: BLE001
            logger.warning("studies insights failed: %s", exc)
        if fresh:
            insight_list = fresh
        else:
            # Re-read the latest snapshot: a concurrent run may have just written
            # insights, and an empty result must not clobber them.
            latest = _load_previous_insights()
            if latest:
                insight_list = latest

    snapshot = StudySnapshot(
        ts=now_iso(),
        queries=[*queries, *proposed],
        results=results,
        guards=eval_out["guards"],
        decisions=eval_out["decisions"],
        insights=insight_list,
    )
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(
        json.dumps(snapshot.model_dump(), indent=2, default=str), encoding="utf-8"
    )
    write_guards(eval_out["guards"])
    try:
        from app.services.learn.harvest import harvest_guards, harvest_insights

        harvest_guards(eval_out["guards"])
        harvest_insights(insight_list)
    except Exception:
        logger.warning("studies harvest failed", exc_info=True)
    logger.info(
        "studies: %d queries, %d results, %d proposed, %d guards, %d insights",
        len(queries), len(results), len(proposed), len(eval_out["guards"]), len(insight_list),
    )
    return snapshot.model_dump()


__all__ = ["SNAPSHOT_PATH", "run_studies"]
