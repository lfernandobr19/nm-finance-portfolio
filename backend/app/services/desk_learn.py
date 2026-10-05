"""Walk-forward tuner for desk-gate USD budget slices (not LLM, not dip_pct)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.models import (
    DeskBudgetConfig,
    Position,
    PositionStatus,
    StrategyKind,
)
from app.services.desk_gate import parse_slices
from app.services.learn.trials import record_trials
from app.services.stats import deflated_sharpe_ratio, probability_of_backtest_overfitting, sharpe

logger = logging.getLogger("fiidesk.desk_gate.learn")

_KINDS = (StrategyKind.hv_dip, StrategyKind.index_core, StrategyKind.mega_rotation)


def load_closed_usd_auto(db: Session) -> list[dict[str, Any]]:
    rows = (
        db.query(Position)
        .filter(
            Position.strategy_kind.in_(_KINDS),
            Position.status == PositionStatus.closed,
            Position.closed_at.is_not(None),
            Position.r_multiple_realized.is_not(None),
        )
        .order_by(Position.closed_at.asc())
        .all()
    )
    out: list[dict[str, Any]] = []
    for p in rows:
        kind = p.strategy_kind
        key = kind.value if hasattr(kind, "value") else str(kind)
        out.append(
            {
                "closed_at": p.closed_at,
                "kind": key,
                "r": float(p.r_multiple_realized),
            }
        )
    return out


def _expectancy(trades: list[dict[str, Any]], kind: str) -> tuple[int, float | None]:
    rs = [t["r"] for t in trades if t["kind"] == kind]
    if not rs:
        return 0, None
    return len(rs), sum(rs) / len(rs)


def run_budget_learning(db: Session) -> dict[str, Any]:
    settings = get_settings()
    if not settings.desk_gate_learn_enabled:
        return {"status": "disabled"}

    trades = load_closed_usd_auto(db)
    min_n = int(settings.desk_gate_learn_min_closed)
    if len(trades) < min_n:
        logger.info("desk_gate learn: insufficient closed trades (%d < %d)", len(trades), min_n)
        logger.info("learn_status kind=desk n=%s status=no_data", len(trades))
        return {"status": "no_data", "n_trades": len(trades)}

    current = parse_slices(settings.desk_gate_usd_budgets)
    scored: list[tuple[str, float, int]] = []
    returns_by_kind: dict[str, list[float]] = {}
    for kind in ("hv_dip", "index_core", "mega_rotation"):
        n, exp = _expectancy(trades, kind)
        returns_by_kind[kind] = [t["r"] for t in trades if t["kind"] == kind]
        if exp is not None:
            scored.append((kind, exp, n))

    if not scored:
        return {"status": "no_edge", "n_trades": len(trades)}

    best_kind, best_exp, _ = max(scored, key=lambda x: x[1])
    if best_exp <= 0:
        return {"status": "skipped", "reason": "negative_best_expectancy", "n_trades": len(trades)}

    all_r = [t["r"] for t in trades]
    n_trials = record_trials("desk:budget_slices", max(1, len(scored)))
    dsr = deflated_sharpe_ratio(all_r, n_trials=n_trials)
    matrix = [returns_by_kind[k] or [0.0] for k, _, _ in scored]
    # CSCV needs a rectangular matrix; pad with zeros to equal length.
    width = max(len(row) for row in matrix)
    padded = [row + [0.0] * (width - len(row)) for row in matrix]
    pbo = probability_of_backtest_overfitting(padded) if len(padded) >= 2 and width >= 4 else 1.0
    if (1.0 - dsr) > 0.05:
        logger.info("desk_gate learn skip: not significant dsr=%s", dsr)
        return {"status": "skipped", "reason": "not_significant", "dsr": dsr, "n_trades": len(trades)}
    if pbo > 0.5:
        logger.info("desk_gate learn skip: high PBO=%s", pbo)
        return {"status": "skipped", "reason": "pbo", "pbo": pbo, "n_trades": len(trades)}

    new_slices = dict(current)
    bump = 0.05
    donor = "mega_rotation" if new_slices.get("mega_rotation", 0) > bump else "index_core"
    if donor == best_kind:
        donor = "hv_dip" if best_kind != "hv_dip" else "index_core"
    take = min(bump, max(0.0, float(new_slices.get(donor, 0.0))))
    new_slices[donor] = round(float(new_slices.get(donor, 0.0)) - take, 4)
    new_slices[best_kind] = round(float(new_slices.get(best_kind, 0.0)) + take, 4)

    current_row = (
        db.query(DeskBudgetConfig)
        .filter(DeskBudgetConfig.is_active.is_(True))
        .order_by(DeskBudgetConfig.version.desc())
        .first()
    )
    next_version = (current_row.version + 1) if current_row else 1
    if current_row is not None:
        current_row.is_active = False
    peak = float(getattr(current_row, "peak_equity_usd", 0) or 0) if current_row else 0.0
    row = DeskBudgetConfig(
        version=next_version,
        is_active=True,
        slices=new_slices,
        peak_equity_usd=peak,
        origin="auto",
        validation={
            "n_trades": len(trades),
            "best_kind": best_kind,
            "best_exp": best_exp,
            "dsr": dsr,
            "pbo": pbo,
            "oos_sharpe": sharpe(all_r),
        },
        activated_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.flush()
    logger.info("desk_gate learn applied slices=%s best=%s", new_slices, best_kind)
    logger.info("learn_status kind=desk n=%s status=applied", len(trades))
    return {"status": "applied", "slices": new_slices, "best_kind": best_kind, "n_trades": len(trades)}


__all__ = ["load_closed_usd_auto", "run_budget_learning"]
