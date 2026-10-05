"""Walk-forward auto-tuning for day trade rules (paper learn loop).

Pure-Python (no numpy). The optimizer:
  1. Replays each rule over persisted intraday bars (per ticker/session).
  2. Walk-forward: expanding in-sample grid-search, rolling out-of-sample eval.
  3. Deflates the result with the Deflated Sharpe Ratio and a CSCV probability
     of backtest overfitting, so a "lucky" grid-search result is not deployed.

Guardrails (sample minimum, significance, margin, bounds) are enforced by
`run_learning` before any param change is written.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.models import DayTradeBar
from app.services.day_trade.bars import IntradayBar
from app.services.day_trade.configs import activate_params, get_active_params
from app.services.day_trade.params import RULE_IDS, grid_combos
from app.services.day_trade.rules.opening_range_break import evaluate_opening_range_break
from app.services.day_trade.rules.vwap_reclaim import evaluate_vwap_reclaim
from app.services.learn.trials import record_trials
from app.services.stats import (
    deflated_sharpe_ratio,
    probability_of_backtest_overfitting,
    sharpe,
)

logger = logging.getLogger("fiidesk.day_trade.learning")

RULE_FNS = {
    "opening_range_break": evaluate_opening_range_break,
    "vwap_reclaim": evaluate_vwap_reclaim,
}


# --------------------------------------------------------------------------- #
# Replay / simulation
# --------------------------------------------------------------------------- #
def _simulate_forward(
    bars: list[IntradayBar],
    entry_idx: int,
    side: str,
    entry: float,
    stop: float,
    target: float,
) -> tuple[str, float, int]:
    for j in range(entry_idx + 1, len(bars)):
        b = bars[j]
        if side == "long":
            if b.low <= stop:
                return "stop", stop - entry, j - entry_idx
            if b.high >= target:
                return "target", target - entry, j - entry_idx
        else:
            if b.high >= stop:
                return "stop", entry - stop, j - entry_idx
            if b.low <= target:
                return "target", entry - target, j - entry_idx
    return "open", 0.0, len(bars) - 1 - entry_idx


def _r_multiple(entry: float, stop: float, pnl: float) -> float | None:
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    return pnl / risk


def replay_session(
    bars: list[IntradayBar],
    fn,
    params: dict[str, Any],
) -> list[dict[str, Any]]:
    outcomes: list[dict[str, Any]] = []
    fired = False
    for i in range(len(bars)):
        window = bars[: i + 1]
        if len(window) < 2:
            continue
        sig = fn(window, params)
        if sig is None or fired:
            continue
        fired = True
        status, pnl, hold = _simulate_forward(
            bars, i, sig.side, sig.entry_price, sig.stop_price, sig.target_price
        )
        outcomes.append(
            {
                "side": sig.side,
                "entry": sig.entry_price,
                "stop": sig.stop_price,
                "target": sig.target_price,
                "status": status,
                "pnl": pnl,
                "hold_bars": hold,
                "r": _r_multiple(sig.entry_price, sig.stop_price, pnl),
            }
        )
    return outcomes


def _metric_on(
    sessions: list[dict[str, Any]],
    rule_id: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    fn = RULE_FNS[rule_id]
    rs: list[float] = []
    n = 0
    wins = 0
    for sess in sessions:
        for o in replay_session(sess["bars"], fn, params):
            n += 1
            if o["r"] is not None:
                rs.append(o["r"])
                wins += 1 if o["pnl"] > 0 else 0
    expectancy = (sum(rs) / len(rs)) if rs else None
    return {"n": n, "wins": wins, "returns": rs, "expectancy": expectancy}


# --------------------------------------------------------------------------- #
# Walk-forward
# --------------------------------------------------------------------------- #
def run_walk_forward(
    rule_id: str,
    sessions: list[dict[str, Any]],
    *,
    n_windows: int = 4,
    max_combos: int = 60,
    current_params: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Walk-forward grid search for one rule.

    Returns a dict with best params + OOS validation metrics, or None when there
    is not enough data to form windows.
    """
    dates = sorted({s["date"] for s in sessions})
    if len(dates) < n_windows + 1:
        return None
    combos = grid_combos(rule_id, max_combos=max_combos)
    if not combos:
        return None
    if current_params:
        combos = [dict(current_params)] + [c for c in combos if c != current_params]
        combos = combos[:max_combos]

    window_size = len(dates) // (n_windows + 1)
    if window_size < 1:
        return None

    oos_series: list[float] = []
    oos_n = 0
    current_oos_series: list[float] = []
    # matrix rows = windows, cols = combos (OOS expectancy per combo)
    matrix: list[list[float]] = []

    for w in range(n_windows):
        is_dates = set(dates[: (w + 1) * window_size])
        oos_dates = set(dates[(w + 1) * window_size : (w + 2) * window_size])
        is_sessions = [s for s in sessions if s["date"] in is_dates]
        oos_sessions = [s for s in sessions if s["date"] in oos_dates]

        is_metrics = [_metric_on(is_sessions, rule_id, c) for c in combos]
        oos_metrics = [_metric_on(oos_sessions, rule_id, c) for c in combos]

        # Track current-params OOS (index 0 is the current combo when provided).
        if current_params and oos_metrics:
            current_oos_series.extend(oos_metrics[0]["returns"])

        # Best combo by in-sample expectancy (require some signals).
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
            [
                (m["expectancy"] if m["expectancy"] is not None else 0.0)
                for m in oos_metrics
            ]
        )

    if oos_n == 0 or not oos_series:
        return None

    # Cumulative, not per-run: reporting the same 60 combos every night claims
    # each night that the search was small, while the real count keeps growing.
    n_trials = record_trials(f"day_trade:{rule_id}", len(combos))
    dsr = deflated_sharpe_ratio(oos_series, n_trials=n_trials)
    pbo = probability_of_backtest_overfitting(matrix) if len(matrix) >= 4 else 1.0
    expectancy = sum(oos_series) / len(oos_series)
    current_expectancy = (
        (sum(current_oos_series) / len(current_oos_series))
        if current_oos_series
        else None
    )

    best_combo = None
    best_expectancy = -1e18
    for c in combos:
        m = _metric_on(sessions, rule_id, c)
        if m["expectancy"] is not None and m["expectancy"] > best_expectancy:
            best_expectancy = m["expectancy"]
            best_combo = c

    return {
        "rule_id": rule_id,
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
def load_sessions(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(select(DayTradeBar).order_by(DayTradeBar.ts.asc())).scalars().all()
    groups: dict[tuple[Any, str], list[IntradayBar]] = {}
    for row in rows:
        key = (row.session_date, row.ticker)
        groups.setdefault(key, []).append(
            IntradayBar(
                ts=row.ts,
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=float(row.volume),
            )
        )
    sessions = [
        {"date": d, "ticker": t, "bars": bars}
        for (d, t), bars in groups.items()
    ]
    sessions.sort(key=lambda s: (s["date"], s["ticker"]))
    return sessions


def _should_activate(wf: dict[str, Any], settings) -> tuple[bool, str]:
    min_n = int(settings.day_trade_min_closed_signals)
    if wf["oos_n"] < min_n:
        return False, f"sample too small ({wf['oos_n']} < {min_n})"
    if wf["significance"] > float(settings.day_trade_min_significance):
        return False, f"not significant (sig={wf['significance']:.3f})"
    if wf["oos_expectancy"] <= 0:
        return False, f"negative OOS edge ({wf['oos_expectancy']:.3f}R)"
    if wf["pbo"] > 0.5:
        return False, f"high overfitting risk (PBO={wf['pbo']:.2f})"

    # Hysteresis: candidate must beat the current params' OOS by a minimum margin
    # so params do not churn every night on noise.
    margin = float(settings.day_trade_tune_min_margin_pct) / 100.0
    cur = wf.get("current_oos_expectancy")
    if cur is not None and cur > 0:
        improvement = (wf["oos_expectancy"] - cur) / cur
        if improvement < margin:
            return False, (
                f"no meaningful improvement ({improvement:.1%} < {margin:.1%})"
            )
    return True, "ok"


def run_learning(db: Session) -> dict[str, Any]:
    settings = get_settings()
    result: dict[str, Any] = {"status": "ok", "rules": {}}
    if not settings.day_trade_learn_enabled:
        logger.info("learn_status kind=day_trade n=0 status=disabled")
        return {"status": "disabled", "rules": {}}

    sessions = load_sessions(db)
    if not sessions:
        logger.info("learn_status kind=day_trade n=0 status=no_data")
        return {"status": "no_data", "rules": {}}

    current = get_active_params(db)
    for rule_id in RULE_IDS:
        wf = run_walk_forward(
            rule_id,
            sessions,
            current_params=current.get(rule_id),
        )
        if wf is None:
            result["rules"][rule_id] = {"status": "insufficient_data"}
            continue
        ok, reason = _should_activate(wf, settings)
        wf["applied"] = False
        wf["skip_reason"] = reason if not ok else None
        result["rules"][rule_id] = wf
        if not ok:
            logger.info("day_trade learn %s skip: %s", rule_id, reason)
            continue

        new_params = dict(current)
        new_params[rule_id] = wf["best_params"]
        activate_params(
            db,
            new_params,
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
        logger.info("day_trade learn %s applied: %s", rule_id, wf["best_params"])

    db.commit()
    logger.info("learn_status kind=day_trade n=%s status=%s", len(sessions), result.get("status"))
    return result


__all__ = [
    "sharpe",
    "deflated_sharpe_ratio",
    "probability_of_backtest_overfitting",
    "replay_session",
    "run_walk_forward",
    "run_learning",
    "load_sessions",
]
