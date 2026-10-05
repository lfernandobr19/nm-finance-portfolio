"""Walk-forward auto-tuning for the hv_dip strategy (paper learn loop).

The hv_dip learn loop evaluates candidate *entry-threshold* param sets against the
realized R-multiples of closed positions, using walk-forward with expanding
in-sample grid-search and rolling out-of-sample evaluation. Results are deflated
with the Deflated Sharpe Ratio and CSCV probability-of-overfitting before any
param is activated, and a circuit breaker reverts/rejects if the tuned expectancy
falls below the floor.

Scoring-only knobs (quality bonus, oscillation window/swing) are versioned but not
grid-searched — see params.py.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.models import Position, PositionStatus, StrategyKind
from app.services.hv_dip.configs import activate_params, ensure_default_config, get_active_params
from app.services.hv_dip.params import grid_combos
from app.services.learn.trials import record_trials
from app.services.stats import (
    deflated_sharpe_ratio,
    probability_of_backtest_overfitting,
    sharpe,
)

logger = logging.getLogger("fiidesk.hv_dip.learning")


# --------------------------------------------------------------------------- #
# Evidence loading
# --------------------------------------------------------------------------- #
def load_hv_dip_closed_trades(db: Session) -> list[dict[str, Any]]:
    """Closed hv_dip positions → feature/outcome samples for the optimizer."""
    rows = (
        db.execute(
            select(Position)
            .where(Position.strategy_kind == StrategyKind.hv_dip)
            .where(Position.status == PositionStatus.closed)
            .where(Position.closed_at.is_not(None))
        )
        .scalars()
        .all()
    )
    trades: list[dict[str, Any]] = []
    for p in rows:
        r = p.r_multiple_realized
        if r is None:
            continue
        metrics = p.metrics or {}
        trades.append(
            {
                "closed_at": p.closed_at,
                "r": float(r),
                "dip_pct": metrics.get("dip_pct"),
                "recovery_rate": metrics.get("recovery_rate"),
                "quality_tier": metrics.get("quality_tier") or "mid",
                "is_fresh_high": bool(metrics.get("is_fresh_high")),
                "synthetic": False,
            }
        )
    trades.sort(key=lambda t: t["closed_at"])
    return trades


def _trade_passes(trade: dict[str, Any], params: dict[str, float]) -> bool:
    """Would this trade have been taken under the given entry thresholds?"""
    dip = trade.get("dip_pct")
    if dip is None or float(dip) < params["dip_pct"]:
        return False
    rr = trade.get("recovery_rate")
    if rr is None or float(rr) < params["min_recovery_rate"]:
        return False
    if params["reject_fresh_high"] >= 0.5 and trade.get("is_fresh_high"):
        return False
    return True


def _metric_on(trades: list[dict[str, Any]], params: dict[str, float]) -> dict[str, Any]:
    rs: list[float] = []
    n = 0
    for t in trades:
        if not _trade_passes(t, params):
            continue
        n += 1
        rs.append(t["r"])
    expectancy = (sum(rs) / len(rs)) if rs else None
    return {"n": n, "returns": rs, "expectancy": expectancy}


# --------------------------------------------------------------------------- #
# Walk-forward
# --------------------------------------------------------------------------- #
def run_walk_forward(
    trades: list[dict[str, Any]],
    *,
    n_windows: int = 4,
    max_combos: int = 64,
    current_params: dict[str, float] | None = None,
) -> dict[str, Any] | None:
    if len(trades) < n_windows + 2:
        return None
    combos = grid_combos(max_combos=max_combos)
    if not combos:
        return None
    if current_params:
        combos = [dict(current_params)] + [c for c in combos if c != current_params]
        combos = combos[:max_combos]

    dates = sorted({t["closed_at"] for t in trades})
    window_size = len(dates) // (n_windows + 1)
    if window_size < 1:
        return None

    oos_series: list[float] = []
    oos_n = 0
    current_oos_series: list[float] = []
    matrix: list[list[float]] = []

    for w in range(n_windows):
        is_dates = set(dates[: (w + 1) * window_size])
        oos_dates = set(dates[(w + 1) * window_size : (w + 2) * window_size])
        is_trades = [t for t in trades if t["closed_at"] in is_dates]
        oos_trades = [t for t in trades if t["closed_at"] in oos_dates]

        is_metrics = [_metric_on(is_trades, c) for c in combos]
        oos_metrics = [_metric_on(oos_trades, c) for c in combos]

        if current_params and oos_metrics:
            current_oos_series.extend(oos_metrics[0]["returns"])

        scored = [
            (i, m["expectancy"] if m["expectancy"] is not None else -1e9)
            for i, m in enumerate(is_metrics)
            if m["n"] > 0
        ]
        if not scored:
            continue
        best_i = max(scored, key=lambda x: x[1])[0]
        best_oos = oos_metrics[best_i]
        oos_series.extend(best_oos["returns"])
        oos_n += best_oos["n"]
        matrix.append(
            [(m["expectancy"] if m["expectancy"] is not None else 0.0) for m in oos_metrics]
        )

    if oos_n == 0 or not oos_series:
        return None

    # Cumulative across runs: a nightly search that always reports its own 60
    # combos understates the multiple-testing burden it has actually incurred.
    n_trials = record_trials("hv_dip:quick_target", len(combos))
    dsr = deflated_sharpe_ratio(oos_series, n_trials=n_trials)
    pbo = probability_of_backtest_overfitting(matrix) if len(matrix) >= 4 else 1.0
    expectancy = sum(oos_series) / len(oos_series)
    current_expectancy = (
        (sum(current_oos_series) / len(current_oos_series)) if current_oos_series else None
    )

    best_combo = None
    best_expectancy = -1e18
    for c in combos:
        m = _metric_on(trades, c)
        if m["expectancy"] is not None and m["expectancy"] > best_expectancy:
            best_expectancy = m["expectancy"]
            best_combo = c

    return {
        "best_params": best_combo or {},
        "oos_n": oos_n,
        "oos_expectancy": expectancy,
        "current_oos_expectancy": current_expectancy,
        "oos_sharpe": sharpe(oos_series),
        "dsr": dsr,
        "significance": 1.0 - dsr,
        "pbo": pbo,
        "n_combos": len(combos),
        "n_trials_cumulative": n_trials,
    }


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #
def _should_activate(wf: dict[str, Any], settings) -> tuple[bool, str]:
    min_n = int(settings.hv_dip_min_closed_signals)
    if wf["oos_n"] < min_n:
        return False, f"sample too small ({wf['oos_n']} < {min_n})"
    if wf["significance"] > float(settings.hv_dip_learn_significance):
        return False, f"not significant (sig={wf['significance']:.3f})"
    if wf["oos_expectancy"] <= 0:
        return False, f"negative OOS edge ({wf['oos_expectancy']:.3f}R)"
    if wf["pbo"] > 0.5:
        return False, f"high overfitting risk (PBO={wf['pbo']:.2f})"
    # Circuit breaker: tuned expectancy must clear the floor.
    if wf["oos_expectancy"] < float(settings.hv_dip_learn_circuit_breaker_r):
        return False, (
            f"circuit breaker: expectancy {wf['oos_expectancy']:.3f}R below "
            f"floor {settings.hv_dip_learn_circuit_breaker_r}"
        )

    margin = float(settings.hv_dip_learn_min_margin_pct) / 100.0
    cur = wf.get("current_oos_expectancy")
    if cur is not None and cur > 0:
        improvement = (wf["oos_expectancy"] - cur) / cur
        if improvement < margin:
            return False, f"no meaningful improvement ({improvement:.1%} < {margin:.1%})"
    return True, "ok"


def _load_synthetic() -> list[dict[str, Any]]:
    from app.services.hv_dip.replay import load_cached_replay

    return load_cached_replay()


def run_learning(db: Session) -> dict[str, Any]:
    settings = get_settings()
    if not settings.hv_dip_learn_enabled:
        return {"status": "disabled"}

    ensure_default_config(db)
    real = load_hv_dip_closed_trades(db)
    synthetic = _load_synthetic()
    min_n = int(settings.hv_dip_min_closed_signals)

    # Exploration on the combined, labelled set. Promotion still requires a
    # real sample — mixing without the flag is exactly what this split prevents.
    if len(real) < min_n:
        explore = list(real) + list(synthetic)
        wf = run_walk_forward(explore) if len(explore) >= 6 else None
        logger.info(
            "hv_dip learn: explore only (real=%d synthetic=%d < %d)",
            len(real), len(synthetic), min_n,
        )
        logger.info("learn_status kind=hv_dip n=%s status=explored", len(real))
        return {
            "status": "explored" if wf else "no_data",
            "n_trades": len(real),
            "n_real": len(real),
            "n_synthetic": len(synthetic),
            "applied": False,
            "wf": wf,
            "skip_reason": "synthetic_cannot_promote",
        }

    current = get_active_params(db)
    wf = run_walk_forward(real, current_params=current)
    if wf is None:
        return {
            "status": "insufficient_data",
            "n_trades": len(real),
            "n_real": len(real),
            "n_synthetic": len(synthetic),
        }

    ok, reason = _should_activate(wf, settings)
    wf["applied"] = False
    wf["n_trades"] = len(real)
    wf["n_real"] = len(real)
    wf["n_synthetic"] = len(synthetic)
    if not ok:
        wf["skip_reason"] = reason
        logger.info("hv_dip learn skip: %s", reason)
        logger.info("learn_status kind=hv_dip n=%s status=skipped", len(real))
        return {"status": "skipped", "wf": wf}

    activate_params(
        db,
        wf["best_params"],
        origin="auto",
        reason=(
            f"walk-forward: OOS expectancy {wf['oos_expectancy']:.3f}R "
            f"(n={wf['oos_n']}, DSR={wf['dsr']:.3f}, PBO={wf['pbo']:.2f})"
        ),
        validation={
            "oos_n": wf["oos_n"],
            "oos_expectancy": wf["oos_expectancy"],
            "oos_sharpe": wf["oos_sharpe"],
            "dsr": wf["dsr"],
            "significance": wf["significance"],
            "pbo": wf["pbo"],
        },
    )
    wf["applied"] = True
    logger.info("hv_dip learn applied: %s", wf["best_params"])
    logger.info("learn_status kind=hv_dip n=%s status=applied", len(real))
    return {"status": "applied", "wf": wf}


__all__ = [
    "load_hv_dip_closed_trades",
    "run_walk_forward",
    "run_learning",
]
