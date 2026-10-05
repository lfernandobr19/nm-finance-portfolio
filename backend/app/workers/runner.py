"""Periodic worker: income + swing BR + hv_dip USD (~1–2×/day)."""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path

# Allow `python -m app.workers.runner` from backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.config import get_settings
from app.db import SessionLocal
from app.services.hv_dip.exit_watch import run_hv_dip_exit_watch
from app.services.hv_dip import run_hv_dip_cycle
from app.services.hv_dip.live_refresh import refresh_pending_hv_dip_suggestions
from app.services.swing.engine import run_swing_cycle
from app.services.worker_heartbeat import write_heartbeat as _write_heartbeat
from app.services.market import ingest_market
from app.services.market_hours import us_session_open
from app.services.news import ingest_news
from app.services.news_us import ingest_news_us
from app.services.news_llm import classify_pending
from app.services.suggestions import create_suggestions_from_snapshots, expire_stale_suggestions
from app.services.tastytrade_reconcile import (
    reconcile_submitted_tastytrade_orders,
    sync_live_tastytrade_balances,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("fiidesk.worker")
settings = get_settings()

_last_swing_ts: float = 0.0
_last_hv_dip_ts: float = 0.0
_last_hv_dip_refresh_ts: float = 0.0
_last_news_us_ts: float = 0.0


def run_income_cycle() -> None:
    db = SessionLocal()
    try:
        snaps = ingest_market(db)
        logger.info("Ingested %d market snapshots", len(snaps))
        created = create_suggestions_from_snapshots(db, snaps)
        logger.info("Created %d income suggestions", len(created))
        news = ingest_news(db)
        logger.info("Ingested %d news items", len(news))
        expired = expire_stale_suggestions(db)
        logger.info("Expired %d suggestions", expired)
    except Exception:
        logger.exception("Income worker cycle failed")
        db.rollback()
    finally:
        db.close()


def run_swing_if_due(*, force: bool = False) -> None:
    global _last_swing_ts
    now = time.time()
    if not force and _last_swing_ts and (now - _last_swing_ts) < settings.swing_min_interval_seconds:
        logger.info(
            "Swing skipped (next in %ss)",
            int(settings.swing_min_interval_seconds - (now - _last_swing_ts)),
        )
        return
    db = SessionLocal()
    try:
        created = run_swing_cycle(db)
        _last_swing_ts = time.time()
        logger.info("Created %d swing suggestions", len(created))
    except Exception:
        logger.exception("Swing worker cycle failed")
        db.rollback()
    finally:
        db.close()


def run_hv_dip_if_due(*, force: bool = False) -> None:
    global _last_hv_dip_ts
    now = time.time()
    if (
        not force
        and _last_hv_dip_ts
        and (now - _last_hv_dip_ts) < settings.hv_dip_min_interval_seconds
    ):
        logger.info(
            "HV Dip skipped (next in %ss)",
            int(settings.hv_dip_min_interval_seconds - (now - _last_hv_dip_ts)),
        )
        return
    db = SessionLocal()
    try:
        created = run_hv_dip_cycle(db)
        _last_hv_dip_ts = time.time()
        logger.info("Created %d hv_dip suggestions", len(created))
    except Exception:
        logger.exception("HV Dip worker cycle failed")
        db.rollback()
    finally:
        db.close()


def run_hv_dip_refresh_if_due(*, force: bool = False) -> None:
    global _last_hv_dip_refresh_ts
    if not us_session_open():
        return
    now = time.time()
    interval = settings.hv_dip_live_refresh_interval_seconds
    if (
        not force
        and _last_hv_dip_refresh_ts
        and (now - _last_hv_dip_refresh_ts) < interval
    ):
        return
    db = SessionLocal()
    try:
        expired = expire_stale_suggestions(db)
        stats = refresh_pending_hv_dip_suggestions(db)
        db.commit()
        _last_hv_dip_refresh_ts = time.time()
        if stats["updated"] or stats["expired"] or expired:
            logger.info(
                "HV Dip refresh updated=%d expired=%d ttl_expired=%d skipped=%d",
                stats["updated"],
                stats["expired"],
                expired,
                stats["skipped"],
            )
    except Exception:
        logger.exception("HV Dip refresh failed")
        db.rollback()
    finally:
        db.close()


def run_hv_dip_exit_if_due() -> None:
    db = SessionLocal()
    try:
        from app.services.hv_dip.rotation_watch import run_hv_dip_rotation_watch

        sent = run_hv_dip_exit_watch(db)
        rot = run_hv_dip_rotation_watch(db)
        if sent or rot:
            logger.info("hv_dip exit actions=%d rotation=%d", sent, rot)
        db.commit()
        _write_heartbeat("ok")
    except Exception:
        logger.exception("HV Dip exit watch failed")
        db.rollback()
        _write_heartbeat("error")
    finally:
        db.close()


def run_pnl_milestones_if_due() -> None:
    """Notify on daily P&L milestones (USD) during the US session."""
    if not us_session_open():
        return
    db = SessionLocal()
    try:
        from app.services.pnl_milestones import run_pnl_milestones

        sent = run_pnl_milestones(db)
        if sent:
            logger.info("pnl milestones sent=%d", sent)
        db.commit()
    except Exception:
        logger.exception("pnl milestones failed")
        db.rollback()
    finally:
        db.close()


def run_tastytrade_reconcile() -> None:
    db = SessionLocal()
    try:
        n = reconcile_submitted_tastytrade_orders(db)
        b = sync_live_tastytrade_balances(db)
        if n or b:
            logger.info("tastytrade synced orders=%d balances=%d", n, b)
    except Exception:
        logger.exception("tastytrade reconcile failed")
        db.rollback()
    else:
        db.commit()
    finally:
        db.close()


_last_day_trade_learn_ts: float = 0.0


def run_day_trade_learn_if_due(*, force: bool = False) -> None:
    global _last_day_trade_learn_ts
    if not settings.day_trade_enabled:
        return
    if not settings.day_trade_learn_enabled:
        return
    now = time.time()
    if (
        not force
        and _last_day_trade_learn_ts
        and (now - _last_day_trade_learn_ts) < settings.day_trade_learn_interval_seconds
    ):
        return
    # Learn only after the US session closes (history is stable overnight).
    if us_session_open():
        return
    db = SessionLocal()
    try:
        from app.services.day_trade.backfill import backfill_watchlist
        from app.services.day_trade.circuit_breaker import run_circuit_breaker
        from app.services.day_trade.learning import run_learning

        bf = backfill_watchlist(db)
        res = run_learning(db)
        trips = run_circuit_breaker(db)
        _last_day_trade_learn_ts = time.time()
        logger.info("day_trade learn backfill=%s result=%s trips=%s", bf, res, trips)
    except Exception:
        logger.exception("Day trade learn failed")
        db.rollback()
    finally:
        db.close()


_last_hv_dip_learn_ts: float = 0.0


def run_hv_dip_learn_if_due(*, force: bool = False) -> None:
    global _last_hv_dip_learn_ts
    if not settings.hv_dip_learn_enabled:
        return
    now = time.time()
    if (
        not force
        and _last_hv_dip_learn_ts
        and (now - _last_hv_dip_learn_ts) < settings.hv_dip_learn_interval_seconds
    ):
        return
    # Learn only after the US session closes (history is stable overnight).
    if us_session_open():
        return
    db = SessionLocal()
    try:
        from app.services.hv_dip.learning import run_learning

        res = run_learning(db)
        _last_hv_dip_learn_ts = time.time()
        db.commit()
        logger.info("hv_dip learn result=%s", res)
    except Exception:
        logger.exception("HV Dip learn failed")
        db.rollback()
    finally:
        db.close()


_last_desk_learn_ts: float = 0.0


def run_desk_allocate() -> None:
    db = SessionLocal()
    try:
        from app.services.desk_gate import allocate_pending

        n = allocate_pending(db)
        db.commit()
        if n:
            logger.info("desk_allocate placed=%s", n)
    except Exception:
        logger.exception("desk_allocate failed")
        db.rollback()
    finally:
        db.close()


def run_desk_budget_learn_if_due(*, force: bool = False) -> None:
    global _last_desk_learn_ts
    if not settings.desk_gate_learn_enabled:
        return
    now = time.time()
    if (
        not force
        and _last_desk_learn_ts
        and (now - _last_desk_learn_ts) < settings.desk_gate_learn_interval_seconds
    ):
        return
    if us_session_open():
        return
    db = SessionLocal()
    try:
        from app.services.desk_learn import run_budget_learning

        res = run_budget_learning(db)
        _last_desk_learn_ts = time.time()
        db.commit()
        logger.info("desk_gate learn result=%s", res)
    except Exception:
        logger.exception("desk_gate learn failed")
        db.rollback()
    finally:
        db.close()


def run_news_us_if_due(*, force: bool = False) -> None:
    global _last_news_us_ts
    if not settings.news_us_enabled:
        return
    if not (settings.finnhub_api_key or "").strip():
        return
    now = time.time()
    interval = 15 * 60  # 15 min — respects Finnhub free-tier rate limit
    if not force and _last_news_us_ts and (now - _last_news_us_ts) < interval:
        return
    db = SessionLocal()
    try:
        n = ingest_news_us(db)
        c = classify_pending(db)
        _last_news_us_ts = time.time()
        if n or c:
            logger.info("news_us ingested=%d classified=%d", n, c)
    except Exception:
        logger.exception("news_us cycle failed")
        db.rollback()
    finally:
        db.close()


def run_settlement_if_due() -> None:
    """Release USD sell proceeds whose T+2 settlement date has passed.

    Idempotent and date-gated by `settle_due`, so it is safe to run every cycle.
    """
    db = SessionLocal()
    try:
        from app.domain.models import AccountCurrency, InvestmentAccount
        from app.services.hv_dip.settlement import settle_due

        accounts = (
            db.query(InvestmentAccount)
            .filter(InvestmentAccount.currency == AccountCurrency.USD)
            .all()
        )
        released = 0.0
        for acc in accounts:
            released += settle_due(acc)
        if released > 0:
            logger.info("settlement released US$ %.2f across %d accounts", released, len(accounts))
        db.commit()
    except Exception:
        logger.exception("settlement failed")
        db.rollback()
    finally:
        db.close()


_last_index_core_ts: float = 0.0


def run_index_core_if_due(*, force: bool = False) -> None:
    """Autonomous index DCA: fixed USD contribution per cadence (paper-first)."""
    global _last_index_core_ts
    if not settings.index_core_enabled:
        return
    now = time.time()
    if (
        not force
        and _last_index_core_ts
        and (now - _last_index_core_ts) < settings.index_core_interval_seconds
    ):
        logger.info(
            "Index core skipped (next in %ss)",
            int(settings.index_core_interval_seconds - (now - _last_index_core_ts)),
        )
        return
    # Market (notional) orders only make sense during the US session.
    if not us_session_open():
        return
    db = SessionLocal()
    try:
        from app.services.index_core import run_index_core_cycle

        placed = run_index_core_cycle(db)
        db.commit()
        if placed:
            _last_index_core_ts = time.time()
            logger.info("Index core placed %d contributions", placed)
    except Exception:
        logger.exception("Index core cycle failed")
        db.rollback()
    finally:
        db.close()


_last_mega_rotation_ts: float = 0.0


def run_mega_rotation_if_due(*, force: bool = False) -> None:
    """Mega Rotation: single-cash rotation among liquid mega-caps (paper-first)."""
    global _last_mega_rotation_ts
    if not settings.mega_rotation_enabled:
        return
    now = time.time()
    if (
        not force
        and _last_mega_rotation_ts
        and (now - _last_mega_rotation_ts) < settings.mega_rotation_interval_seconds
    ):
        return
    if not us_session_open():
        return
    db = SessionLocal()
    try:
        from app.services.mega_rotation import run_mega_rotation_cycle

        actions = run_mega_rotation_cycle(db)
        db.commit()
        if actions:
            logger.info("Mega Rotation actions=%d", actions)
        _last_mega_rotation_ts = time.time()
    except Exception:
        logger.exception("Mega Rotation cycle failed")
        db.rollback()
    finally:
        db.close()


def run_cycle() -> None:
    run_income_cycle()
    run_swing_if_due()
    run_news_us_if_due()
    run_hv_dip_if_due()
    run_hv_dip_refresh_if_due()
    run_hv_dip_exit_if_due()
    run_pnl_milestones_if_due()
    run_tastytrade_reconcile()
    run_settlement_if_due()
    run_index_core_if_due()
    run_mega_rotation_if_due()
    run_desk_allocate()
    run_day_trade_learn_if_due()
    run_hv_dip_learn_if_due()
    run_desk_budget_learn_if_due()


async def main() -> None:
    if "--once" in sys.argv:
        logger.info("Worker --once (income + swing + hv_dip + rest)")
        run_swing_if_due(force=True)
        run_hv_dip_if_due(force=True)
        run_hv_dip_exit_if_due()
        run_cycle()
        return
    raise SystemExit("use: arq app.workers.arq_settings.WorkerSettings")


if __name__ == "__main__":
    asyncio.run(main())
