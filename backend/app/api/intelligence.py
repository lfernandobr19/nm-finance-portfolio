"""Read-only intelligence pulse and evolution views. Never runs a job."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db import get_db
from app.domain.models import User
from app.schemas import (
    CalibrationViewOut,
    DecisionListOut,
    EvolutionListOut,
    IntelligencePulseOut,
    LedgerListOut,
    MemoryListOut,
)
from app.services.intelligence import read_intelligence_status
from app.services.learn import evolution as evo
from app.services.worker_heartbeat import read_heartbeat

router = APIRouter(tags=["intelligence"])


@router.get("/intelligence/pulse", response_model=IntelligencePulseOut)
def get_intelligence_pulse(_: User = Depends(get_current_user)) -> IntelligencePulseOut:
    """Last pulse snapshot from disk. Does not run the job or touch the gate."""
    payload = read_intelligence_status()
    hb = read_heartbeat()
    if hb:
        payload["ollama"] = hb.get("ollama")
        payload["groq_cooldown"] = hb.get("groq_cooldown")
        payload["ollama_expires_at"] = hb.get("ollama_expires_at")
        payload["last_llm_source"] = hb.get("last_llm_source")
    return IntelligencePulseOut.model_validate(payload)


@router.get("/intelligence/evolution", response_model=EvolutionListOut)
def get_intelligence_evolution(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=100),
) -> EvolutionListOut:
    return EvolutionListOut.model_validate({"items": evo.list_evolution(db, limit=limit)})


@router.get("/intelligence/memory", response_model=MemoryListOut)
def get_intelligence_memory(
    _: User = Depends(get_current_user),
    limit: int = Query(default=50, ge=1, le=100),
) -> MemoryListOut:
    return MemoryListOut.model_validate({"items": evo.list_memories(limit=limit)})


@router.get("/intelligence/ledger", response_model=LedgerListOut)
def get_intelligence_ledger(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    source: str | None = None,
    resolved: bool | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> LedgerListOut:
    return LedgerListOut.model_validate(
        {"items": evo.list_ledger(db, source=source, resolved=resolved, limit=limit)}
    )


@router.get("/intelligence/decisions", response_model=DecisionListOut)
def get_intelligence_decisions(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    verdict: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> DecisionListOut:
    return DecisionListOut.model_validate(
        {"items": evo.list_decisions(db, limit=limit, verdict=verdict)}
    )


@router.get("/intelligence/calibration", response_model=CalibrationViewOut)
def get_intelligence_calibration(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CalibrationViewOut:
    return CalibrationViewOut.model_validate(evo.calibration_view(db))
