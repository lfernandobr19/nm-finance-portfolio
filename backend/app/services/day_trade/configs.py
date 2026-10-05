"""Day trade config: get/set active param set with append-only history."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import DayTradeConfig, DayTradeConfigHistory
from app.services.day_trade.params import clamp_params, default_params

logger = logging.getLogger("fiidesk.day_trade.config")


def get_active_config(db: Session) -> DayTradeConfig | None:
    row = (
        db.execute(
            select(DayTradeConfig)
            .where(DayTradeConfig.is_active.is_(True))
            .order_by(DayTradeConfig.version.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    return row


def get_active_params(db: Session) -> dict[str, dict[str, float]]:
    cfg = get_active_config(db)
    if cfg is None:
        return default_params()
    return clamp_params(cfg.params)


def activate_params(
    db: Session,
    params: dict[str, dict[str, float]],
    *,
    origin: str = "manual",
    reason: str = "",
    validation: dict[str, Any] | None = None,
) -> DayTradeConfig:
    clean = clamp_params(params)
    current = get_active_config(db)
    next_version = (current.version + 1) if current else 1

    if current is not None:
        current.is_active = False

    row = DayTradeConfig(
        version=next_version,
        is_active=True,
        params=clean,
        origin=origin,
        validation=validation or {},
        activated_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.flush()

    hist = DayTradeConfigHistory(
        config_id=row.id,
        version=next_version,
        params=clean,
        origin=origin,
        reason=reason,
        validation=validation or {},
    )
    db.add(hist)
    db.flush()
    logger.info(
        "day_trade config v%d activated (origin=%s) reason=%s",
        next_version,
        origin,
        reason,
    )
    return row


def ensure_default_config(db: Session) -> DayTradeConfig:
    cfg = get_active_config(db)
    if cfg is None:
        return activate_params(db, default_params(), origin="manual", reason="bootstrap default")
    return cfg


def list_history(db: Session, limit: int = 50) -> list[DayTradeConfigHistory]:
    rows = db.execute(
        select(DayTradeConfigHistory)
        .order_by(DayTradeConfigHistory.created_at.desc())
        .limit(limit)
    ).scalars().all()
    return list(rows)


def update_validation(db: Session, patch: dict[str, Any]) -> None:
    """Merge a patch into the active config's validation dict (observability)."""
    cfg = get_active_config(db)
    if cfg is None:
        return
    merged = dict(cfg.validation or {})
    merged.update(patch)
    cfg.validation = merged
    db.flush()


def rollback_config(db: Session, version: int | None = None) -> DayTradeConfig | None:
    """Re-activate a previous version (default: the one before current)."""
    current = get_active_config(db)
    if current is None:
        return None
    target = version if version is not None else current.version - 1
    if target < 1:
        return None
    hist = (
        db.execute(
            select(DayTradeConfigHistory)
            .where(DayTradeConfigHistory.version == target)
            .order_by(DayTradeConfigHistory.created_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if hist is None:
        return None
    return activate_params(
        db,
        hist.params,
        origin="manual",
        reason=f"rollback to v{target}",
        validation=hist.validation or {},
    )


__all__ = [
    "get_active_config",
    "get_active_params",
    "activate_params",
    "ensure_default_config",
    "list_history",
    "rollback_config",
]
