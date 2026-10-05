"""Circuit breaker: auto-disable a rule when live expectancy collapses.

Runs nightly (post-session) over USD accounts. When a rule's realized expectancy
drops below `day_trade_circuit_breaker_expectancy_r` with enough closed signals,
the trip is recorded in the active config (observable) and the user is notified.
Per-bar suppression is already handled by gating; this adds the persistent flag
+ notification + rollback surface.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.models import AccountCurrency, InvestmentAccount
from app.services.day_trade.analytics import _r_multiple, closed_signals
from app.services.day_trade.configs import update_validation
from app.services.notify import notify_day_trade_event

logger = logging.getLogger("fiidesk.day_trade.circuit_breaker")


def _live_expectancy_by_rule(db: Session, account_id: str) -> dict[str, tuple[int, float]]:
    by: dict[str, list[float]] = {}
    for s in closed_signals(db, account_id):
        r = _r_multiple(s)
        if r is None:
            continue
        by.setdefault(s.rule_id, []).append(r)
    return {k: (len(v), sum(v) / len(v)) for k, v in by.items()}


def check_circuit_breaker(db: Session, account_id: str) -> list[str]:
    settings = get_settings()
    threshold = float(settings.day_trade_circuit_breaker_expectancy_r or -0.3)
    min_n = int(settings.day_trade_gate_min_n or 10)
    tripped: list[str] = []
    for rule_id, (n, exp) in _live_expectancy_by_rule(db, account_id).items():
        if n >= min_n and exp < threshold:
            tripped.append(rule_id)
            logger.warning(
                "day_trade circuit breaker: %s expectancy %.3fR < %.3f (n=%d)",
                rule_id,
                exp,
                threshold,
                n,
            )
    return tripped


def run_circuit_breaker(db: Session) -> dict[str, list[str]]:
    accounts = (
        db.query(InvestmentAccount)
        .filter(InvestmentAccount.currency == AccountCurrency.USD)
        .all()
    )
    out: dict[str, list[str]] = {}
    for acc in accounts:
        trips = check_circuit_breaker(db, acc.id)
        if not trips:
            continue
        update_validation(db, {"circuit_breaker_tripped": trips})
        for rule_id in trips:
            notify_day_trade_event(
                db,
                account_id=acc.id,
                event="circuit_breaker",
                detail=f"Regra {rule_id} desabilitada — expectancy abaixo do limiar.",
            )
        out[acc.id] = trips
    db.commit()
    return out


__all__ = ["check_circuit_breaker", "run_circuit_breaker"]
