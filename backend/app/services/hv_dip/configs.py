"""hv_dip config: get/set active param set with append-only history.

Mirrors day_trade/configs.py so the hv_dip learn loop gets the same rollback and
observability guarantees.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import HvDipConfig, HvDipConfigHistory
from app.services.hv_dip.params import clamp_params, default_params

logger = logging.getLogger("fiidesk.hv_dip.config")


def get_active_config(db: Session) -> HvDipConfig | None:
    row = (
        db.execute(
            select(HvDipConfig)
            .where(HvDipConfig.is_active.is_(True))
            .order_by(HvDipConfig.version.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    return row


def get_active_params(db: Session) -> dict[str, float]:
    cfg = get_active_config(db)
    if cfg is None:
        return default_params()
    return clamp_params(cfg.params)


def activate_params(
    db: Session,
    params: dict[str, float],
    *,
    origin: str = "manual",
    reason: str = "",
    validation: dict[str, Any] | None = None,
) -> HvDipConfig:
    clean = clamp_params(params)
    current = get_active_config(db)
    next_version = (current.version + 1) if current else 1

    if current is not None:
        current.is_active = False

    row = HvDipConfig(
        version=next_version,
        is_active=True,
        params=clean,
        origin=origin,
        validation=validation or {},
        activated_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.flush()

    hist = HvDipConfigHistory(
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
        "hv_dip config v%d activated (origin=%s) reason=%s",
        next_version, origin, reason,
    )
    return row


def ensure_default_config(db: Session) -> HvDipConfig:
    cfg = get_active_config(db)
    if cfg is None:
        return activate_params(db, default_params(), origin="manual", reason="bootstrap default")
    return cfg


def list_history(db: Session, limit: int = 50) -> list[HvDipConfigHistory]:
    rows = db.execute(
        select(HvDipConfigHistory)
        .order_by(HvDipConfigHistory.created_at.desc())
        .limit(limit)
    ).scalars().all()
    return list(rows)


def rollback_config(db: Session, version: int | None = None) -> HvDipConfig | None:
    """Re-activate a previous version (default: the one before current)."""
    current = get_active_config(db)
    if current is None:
        return None
    target = version if version is not None else current.version - 1
    if target < 1:
        return None
    hist = (
        db.execute(
            select(HvDipConfigHistory)
            .where(HvDipConfigHistory.version == target)
            .order_by(HvDipConfigHistory.created_at.desc())
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
