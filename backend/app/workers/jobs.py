"""ARQ job coroutines. Sync engines run in asyncio.to_thread (Context7: jobs must be async)."""

from __future__ import annotations

import asyncio
import logging
import threading

logger = logging.getLogger("fiidesk.arq.jobs")

# job_react's insight generation is slow (~50s local LLM) while the cron fires
# every minute. unique=True should dedupe, but the startup run + first cron tick
# can briefly overlap; this lock guarantees only one _run_react executes at a
# time so concurrent runs never clobber each other's snapshot.
_react_lock = threading.Lock()


async def job_ping(ctx: dict) -> str:
    from app.services.worker_heartbeat import write_heartbeat

    logger.info("arq job_ping ok")
    await asyncio.to_thread(write_heartbeat, "ok")
    return "ok"


def _run_income() -> None:
    from app.services.worker_heartbeat import write_heartbeat
    from app.workers.runner import run_income_cycle

    run_income_cycle()
    write_heartbeat("ok")


def _run_swing() -> None:
    from app.workers.runner import run_swing_if_due

    run_swing_if_due(force=True)


def _run_hv_dip_scan() -> None:
    from app.workers.runner import run_hv_dip_if_due

    run_hv_dip_if_due(force=True)


def _run_hv_dip_refresh() -> None:
    from app.workers.runner import run_hv_dip_refresh_if_due

    run_hv_dip_refresh_if_due(force=True)


def _run_exit_watch() -> None:
    from app.workers.runner import run_hv_dip_exit_if_due

    run_hv_dip_exit_if_due()


def _run_tasty_reconcile() -> None:
    from app.workers.runner import run_tastytrade_reconcile

    run_tastytrade_reconcile()


def _run_rest() -> None:
    from app.workers.runner import (
        run_day_trade_learn_if_due,
        run_desk_allocate,
        run_desk_budget_learn_if_due,
        run_hv_dip_learn_if_due,
        run_index_core_if_due,
        run_mega_rotation_if_due,
        run_news_us_if_due,
        run_pnl_milestones_if_due,
        run_settlement_if_due,
    )

    # Keep internal cadence gates (15 min news, 7d index, learn windows).
    run_news_us_if_due()
    run_pnl_milestones_if_due()
    run_settlement_if_due()
    run_index_core_if_due()
    run_mega_rotation_if_due()
    run_desk_allocate()
    run_day_trade_learn_if_due()
    run_hv_dip_learn_if_due()
    run_desk_budget_learn_if_due()


async def job_income(ctx: dict) -> None:
    await asyncio.to_thread(_run_income)


async def job_swing_dw(ctx: dict) -> None:
    await asyncio.to_thread(_run_swing)


async def job_hv_dip_scan(ctx: dict) -> None:
    await asyncio.to_thread(_run_hv_dip_scan)


async def job_hv_dip_refresh(ctx: dict) -> None:
    await asyncio.to_thread(_run_hv_dip_refresh)


async def job_exit_watch(ctx: dict) -> None:
    await asyncio.to_thread(_run_exit_watch)


async def job_tasty_reconcile(ctx: dict) -> None:
    await asyncio.to_thread(_run_tasty_reconcile)


def _run_desk_allocate() -> None:
    from app.workers.runner import run_desk_allocate

    run_desk_allocate()


async def job_desk_allocate(ctx: dict) -> None:
    await asyncio.to_thread(_run_desk_allocate)


def _run_intelligence() -> None:
    from app.db import SessionLocal
    from app.services.intelligence import run_intelligence_pulse

    db = SessionLocal()
    try:
        run_intelligence_pulse(db)
        db.commit()
    except Exception:
        logger.exception("job_intelligence failed")
        db.rollback()
    finally:
        db.close()


async def job_intelligence(ctx: dict) -> None:
    await asyncio.to_thread(_run_intelligence)


def _run_react() -> None:
    """Event-driven learn: recompute studies/learn/calibrate/review/propose only
    when their underlying data changed (new bars/trades/news). Reacts in near
    real time without a blind per-minute clock or LLM waste.
    """
    if not _react_lock.acquire(blocking=False):
        logger.info("job_react skipped: already running")
        return
    try:
        _run_react_locked()
    finally:
        _react_lock.release()


def _run_react_locked() -> None:
    from app.db import SessionLocal
    from app.services.intelligence import patch_intelligence_status
    from app.services.learn.calibration import refit_if_due
    from app.services.learn.ledger import SOURCES, resolve_pending, resolved_pairs
    from app.services.learn.news_whitelist import refresh_whitelist
    from app.services.llm_calibrate import calibrate_news_outcomes
    from app.services.market_hours import us_session_open
    from app.services.studies import change as ch
    from app.services.studies.runner import run_studies
    from app.services.trade_review import review_closed_positions
    from app.workers.runner import (
        run_day_trade_learn_if_due,
        run_desk_budget_learn_if_due,
        run_hv_dip_learn_if_due,
    )

    db = SessionLocal()
    try:
        # 1) Studies (analogies → guards) when bars changed, a propose is due, or
        #    insights are due (retry/regen floors). Insights are regenerated only
        #    when due; otherwise the previous insights are preserved.
        propose_now = ch.propose_due()
        insights_now = ch.insights_due(db)
        if ch.studies_due(db) or propose_now or insights_now:
            snapshot = run_studies(db, propose=propose_now, insights=insights_now)
            patch_intelligence_status({"studies": snapshot})
            ch.mark_studies_done(db)
            if insights_now:
                ch.mark_insights_attempted(db)
            if propose_now:
                ch.mark_propose_done()
            logger.info(
                "job_react studies recomputed propose=%s insights=%s",
                propose_now, insights_now,
            )

        # 2) Learn loops when closed-trade counts changed (session-closed only:
        #    walk-forward needs a stable, closed history).
        if not us_session_open():
            if ch.learn_due(db, "hv_dip"):
                run_hv_dip_learn_if_due(force=True)
            if ch.learn_due(db, "day_trade"):
                run_day_trade_learn_if_due(force=True)
            if ch.learn_due(db, "desk"):
                run_desk_budget_learn_if_due(force=True)
            ch.mark_learn_done(db)

        # 3) Calibrate news labels when unresolved outcomes exist, then re-derive
        #    which event types have earned the right to act as catalysts.
        if ch.calibrate_due(db):
            calibrate_news_outcomes(db)
            report = refresh_whitelist(db)
            try:
                from app.services.learn.harvest import harvest_news

                harvest_news(report)
            except Exception:
                logger.warning("job_react news harvest failed", exc_info=True)
            ch.mark_calibrate_done(db)
            logger.info("job_react calibrate ran")

        # 4) Review closed positions missing an LLM review.
        if ch.review_due(db):
            review_closed_positions(db, limit=10)
            ch.mark_review_done(db)
            logger.info("job_react review ran")

        # 5) Grade every forecast whose horizon has elapsed. Unconditional: the
        #    ledger is the measurement spine, and a forecast that is recorded but
        #    never scored is worth exactly as much as no forecast at all.
        stats = resolve_pending(db, limit=200)
        if stats["resolved"] or stats["abandoned"]:
            logger.info(
                "job_react ledger resolved=%d abandoned=%d skipped=%d",
                stats["resolved"], stats["abandoned"], stats["skipped"],
            )

        # 6) Refit the per-source probability mapping when fresh outcomes landed.
        if stats["resolved"]:
            for src in SOURCES:
                refit_if_due(src, resolved_pairs(db, source=src))
            try:
                from app.services.learn.calibration import refit_news_by_type

                refit_news_by_type(db)
            except Exception:
                logger.warning("job_react news-type platts failed", exc_info=True)

        try:
            from app.services.learn.evolution import cheap_status_patch

            patch_intelligence_status(cheap_status_patch(db))
        except Exception:
            logger.warning("job_react evolution patch failed", exc_info=True)

        db.commit()
    except Exception:
        logger.exception("job_react failed")
        db.rollback()
    finally:
        db.close()


async def job_react(ctx: dict) -> None:
    await asyncio.to_thread(_run_react)


async def job_rest(ctx: dict) -> None:
    await asyncio.to_thread(_run_rest)


def _run_research() -> None:
    from app.db import SessionLocal
    from app.services.learn.memory import consolidate
    from app.services.learn.research import run_queue
    from app.services.worker_heartbeat import write_heartbeat

    db = SessionLocal()
    try:
        out = run_queue(db)
        consolidate()
        db.commit()
        logger.info("job_research ran=%s elapsed=%s", out.get("ran"), out.get("elapsed"))
    except Exception:
        logger.exception("job_research failed")
        db.rollback()
    finally:
        db.close()
    write_heartbeat("ok")


async def job_research(ctx: dict) -> None:
    await asyncio.to_thread(_run_research)
