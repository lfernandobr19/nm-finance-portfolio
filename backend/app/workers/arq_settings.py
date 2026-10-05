"""ARQ WorkerSettings — cron unique jobs (Context7: arq package.WorkerSettings)."""

from __future__ import annotations

import logging

from arq import cron, func
from arq.connections import RedisSettings

from app.config import get_settings
from app.workers.jobs import (
    job_desk_allocate,
    job_exit_watch,
    job_hv_dip_refresh,
    job_hv_dip_scan,
    job_income,
    job_intelligence,
    job_ping,
    job_react,
    job_research,
    job_rest,
    job_swing_dw,
    job_tasty_reconcile,
)

logger = logging.getLogger("fiidesk.arq")

# Streamer enqueue uses _job_id='tasty-reconcile'. keep_result short so a
# finished run does not block the next fill; uniqueness covers overlap only.
job_tasty_reconcile_fn = func(job_tasty_reconcile, timeout=120, keep_result=30)

_EVERY_5_MIN = set(range(0, 60, 5))
_EVERY_MIN = set(range(0, 60))


def redis_settings(url: str | None = None) -> RedisSettings:
    raw = (url or get_settings().redis_url or "redis://localhost:6379/0").strip()
    return RedisSettings.from_dsn(raw)


async def on_startup(ctx: dict) -> None:
    redis = ctx.get("redis")
    if redis is not None:
        pong = await redis.ping()
        logger.info("arq startup redis ping=%s", pong)
    else:
        logger.info("arq startup (no redis in ctx yet)")


async def on_shutdown(ctx: dict) -> None:
    redis = ctx.get("redis")
    logger.info("arq shutdown redis=%s", "yes" if redis is not None else "no")


class WorkerSettings:
    functions = [
        job_ping,
        job_income,
        job_swing_dw,
        job_hv_dip_scan,
        job_hv_dip_refresh,
        job_exit_watch,
        job_tasty_reconcile_fn,
        job_desk_allocate,
        job_rest,
        job_react,
        job_intelligence,
    ]
    cron_jobs = [
        cron(job_ping, hour=23, minute=59, run_at_startup=True, unique=True, max_tries=1),
        cron(job_income, minute=_EVERY_5_MIN, unique=True, max_tries=1),
        cron(
            job_swing_dw,
            hour={0, 6, 12, 18},
            minute=10,
            run_at_startup=True,
            unique=True,
            max_tries=1,
        ),
        cron(
            job_hv_dip_scan,
            minute={0, 30},
            run_at_startup=True,
            unique=True,
            max_tries=1,
        ),
        cron(
            job_desk_allocate,
            minute={0, 30},
            unique=True,
            max_tries=1,
        ),
        cron(job_hv_dip_refresh, minute=_EVERY_5_MIN, unique=True, max_tries=1),
        cron(job_exit_watch, minute=_EVERY_5_MIN, unique=True, max_tries=1),
        cron(job_tasty_reconcile, minute=_EVERY_5_MIN, unique=True, max_tries=1),
        cron(job_rest, minute=_EVERY_5_MIN, unique=True, max_tries=1),
        # Event-driven learn (studies/learn/calibrate/review/propose) reacts to
        # new data once a minute; the nightly job_intelligence remains the LLM
        # calibration + review + snapshot anchor.
        cron(job_react, minute=_EVERY_MIN, run_at_startup=True, unique=True, max_tries=1),
        cron(job_intelligence, hour=6, minute=0, unique=True, max_tries=1),
    ]
    redis_settings = redis_settings()
    on_startup = on_startup
    on_shutdown = on_shutdown
    max_jobs = 2
    job_timeout = 300
    health_check_interval = 60


class ResearchWorkerSettings:
    """Isolated queue so research cannot starve exit_watch / hv_dip / heartbeat."""

    queue_name = "arq:queue:research"
    functions = [job_research]
    cron_jobs = [
        cron(job_research, minute=_EVERY_MIN, unique=True, max_tries=1, timeout=3600),
    ]
    redis_settings = redis_settings()
    on_startup = on_startup
    on_shutdown = on_shutdown
    max_jobs = 1
    job_timeout = 3600
