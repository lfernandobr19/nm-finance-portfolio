"""hv_dip intelligence endpoints (read-only) for the desktop app.

Exposes the observation radar (falling knives) and the active learn-loop
configuration with append-only history and rollback. These surfaces did not
exist in the mobile app and are the core of the desktop "Centro de Inteligência".
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_membership, require_roles
from app.db import get_db
from app.domain.models import AccountMembership, HvDipObservation, MembershipRole
from app.schemas import HvDipConfigHistoryOut, HvDipConfigOut, HvDipObservationOut
from app.services.hv_dip import configs as hv_configs

router = APIRouter(tags=["hv-dip"])


@router.get(
    "/accounts/{account_id}/hv-dip/observations",
    response_model=list[HvDipObservationOut],
)
def list_hv_dip_observations(
    account_id: str,
    _: AccountMembership = Depends(get_membership),
    db: Session = Depends(get_db),
) -> list[HvDipObservationOut]:
    rows = db.execute(
        select(HvDipObservation)
        .where(HvDipObservation.account_id == account_id)
        .order_by(HvDipObservation.last_evaluated_at.desc().nullslast())
        .limit(200)
    ).scalars().all()
    return [HvDipObservationOut.model_validate(r) for r in rows]


@router.get(
    "/accounts/{account_id}/hv-dip/config",
    response_model=HvDipConfigOut,
)
def hv_dip_config(
    account_id: str,
    _: AccountMembership = Depends(get_membership),
    db: Session = Depends(get_db),
) -> HvDipConfigOut:
    cfg = hv_configs.ensure_default_config(db)
    db.commit()
    return HvDipConfigOut.model_validate(cfg)


@router.get(
    "/accounts/{account_id}/hv-dip/config/history",
    response_model=list[HvDipConfigHistoryOut],
)
def hv_dip_config_history(
    account_id: str,
    _: AccountMembership = Depends(get_membership),
    db: Session = Depends(get_db),
) -> list[HvDipConfigHistoryOut]:
    return [HvDipConfigHistoryOut.model_validate(r) for r in hv_configs.list_history(db, limit=50)]


@router.post(
    "/accounts/{account_id}/hv-dip/config/rollback",
    response_model=HvDipConfigOut,
)
def hv_dip_config_rollback(
    account_id: str,
    version: int | None = Query(default=None),
    _: AccountMembership = Depends(require_roles(MembershipRole.owner, MembershipRole.operator)),
    db: Session = Depends(get_db),
) -> HvDipConfigOut:
    cfg = hv_configs.rollback_config(db, version=version)
    if cfg is None:
        raise HTTPException(status_code=404, detail="No rollback target available")
    db.commit()
    return HvDipConfigOut.model_validate(cfg)
