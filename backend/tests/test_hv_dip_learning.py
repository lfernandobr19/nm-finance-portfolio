"""Tests for hv_dip learn loop (Fase 6b) + stats parity."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.hv_dip.learning import (
    _metric_on,
    _should_activate,
    _trade_passes,
    run_walk_forward,
)
from app.services.hv_dip.params import clamp_params, default_params, grid_combos
from app.services.stats import (
    deflated_sharpe_ratio,
    probability_of_backtest_overfitting,
    sharpe,
)

START = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _trade(i: int, r: float, dip: float = 10.0, recovery: float | None = 0.7, fresh: bool = False) -> dict:
    return {
        "closed_at": START + timedelta(days=i),
        "r": r,
        "dip_pct": dip,
        "recovery_rate": recovery,
        "quality_tier": "large",
        "is_fresh_high": fresh,
    }


# ---- stats parity (deterministic) ----

def test_sharpe_simple_series():
    assert sharpe([1.0, 2.0, 3.0, 4.0]) > 0.0


def test_deflated_sharpe_ratio_bounds():
    v = deflated_sharpe_ratio([0.1, -0.05, 0.2, 0.15, -0.1, 0.3], n_trials=10)
    assert 0.0 <= v <= 1.0


def test_pbo_bounds():
    matrix = [[0.1, -0.1, 0.05], [0.2, 0.0, -0.05], [0.0, 0.1, 0.05], [0.05, 0.05, 0.0]]
    v = probability_of_backtest_overfitting(matrix)
    assert 0.0 <= v <= 1.0


# ---- params ----

def test_default_params_has_all_keys():
    p = default_params()
    for k in ("dip_pct", "min_recovery_rate", "reject_fresh_high", "quality_bonus", "osc_swing_pct", "osc_window"):
        assert k in p


def test_clamp_params_bounds():
    p = clamp_params({"dip_pct": 99.0, "min_recovery_rate": -1.0, "reject_fresh_high": 0.5})
    assert p["dip_pct"] == 12.0
    assert p["min_recovery_rate"] == 0.5
    assert p["reject_fresh_high"] == 1.0


def test_grid_combos_nonempty():
    combos = grid_combos()
    assert combos
    assert all("dip_pct" in c for c in combos)


# ---- trade predicate ----

def test_trade_passes_defaults():
    assert _trade_passes(_trade(0, 0.5), default_params()) is True


def test_trade_fails_deep_dip_threshold():
    assert _trade_passes(_trade(0, 0.5, dip=6.0), default_params()) is False


def test_trade_fails_low_recovery():
    assert _trade_passes(_trade(0, 0.5, recovery=0.3), default_params()) is False


def test_trade_fails_fresh_high_when_reject():
    assert _trade_passes(_trade(0, 0.5, fresh=True), default_params()) is False


# ---- metric / walk-forward ----

def test_metric_on_filters():
    trades = [_trade(0, 1.0), _trade(1, 2.0, dip=5.0), _trade(2, 3.0, recovery=0.2)]
    m = _metric_on(trades, default_params())
    assert m["n"] == 1
    assert m["expectancy"] == 1.0


def test_run_walk_forward_insufficient_data():
    assert run_walk_forward([_trade(i, 0.5) for i in range(4)]) is None


def test_run_walk_forward_produces_result():
    trades = [_trade(i, 0.5 + 0.01 * (i % 3)) for i in range(40)]
    wf = run_walk_forward(trades)
    assert wf is not None
    assert "best_params" in wf
    assert wf["oos_n"] > 0


# ---- should activate ----

def _settings(**kw) -> SimpleNamespace:
    defaults = dict(
        hv_dip_min_closed_signals=30,
        hv_dip_learn_significance=0.05,
        hv_dip_learn_min_margin_pct=5.0,
        hv_dip_learn_circuit_breaker_r=-0.3,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def test_should_activate_rejects_small_sample():
    wf = {"oos_n": 5, "significance": 0.01, "oos_expectancy": 0.5, "pbo": 0.1}
    ok, reason = _should_activate(wf, _settings())
    assert ok is False
    assert "sample" in reason


def test_should_activate_rejects_circuit_breaker():
    wf = {"oos_n": 100, "significance": 0.01, "oos_expectancy": -0.5, "pbo": 0.1}
    ok, reason = _should_activate(wf, _settings())
    assert ok is False
    assert "circuit" in reason or "negative" in reason


def test_should_activate_accepts_good():
    wf = {
        "oos_n": 100,
        "significance": 0.01,
        "oos_expectancy": 0.5,
        "pbo": 0.1,
        "current_oos_expectancy": 0.3,
    }
    ok, _ = _should_activate(wf, _settings())
    assert ok is True
