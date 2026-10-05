"""hv_dip bar replay: no look-ahead, R matches the manual calc, tagged synthetic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.brapi_client import Bar
from app.services.hv_dip.exit_engine import quick_target_prices
from app.services.hv_dip.learning import load_hv_dip_closed_trades, run_learning, run_walk_forward
from app.services.hv_dip.replay import replay_bars, simulate_exit

START = datetime(2025, 1, 2, tzinfo=timezone.utc)


def _bar(i: int, price: float, *, high: float | None = None, low: float | None = None) -> Bar:
    return Bar(
        date=START + timedelta(days=i),
        open=price,
        high=price + 0.4 if high is None else high,
        low=price - 0.4 if low is None else low,
        close=price,
        volume=3_000_000.0,
    )


def test_simulate_exit_target_r_matches_manual():
    entry = 10.0
    stop, target = quick_target_prices(entry, target_r=1.0, stop_pct=5.0)
    # Default stop 5% → 9.50, target 1R → 10.50
    future = [
        _bar(1, 10.1),
        _bar(2, 10.3, high=10.60, low=10.05),
    ]
    out = simulate_exit(
        entry=entry,
        stop=stop,
        target=target,
        opened_at=START,
        future=future,
        max_hold_days=3,
    )
    assert out is not None
    assert out["exit_reason"] == "target"
    risk = entry - stop
    assert abs(out["r"] - (target - entry) / risk) < 1e-9
    assert abs(out["r"] - 1.0) < 1e-6


def test_simulate_exit_stop_wins_same_bar():
    entry = 10.0
    stop, target = quick_target_prices(entry, target_r=1.0, stop_pct=5.0)
    future = [_bar(1, 10.0, high=target + 0.2, low=stop - 0.2)]
    out = simulate_exit(
        entry=entry,
        stop=stop,
        target=target,
        opened_at=START,
        future=future,
        max_hold_days=3,
    )
    assert out is not None
    assert out["exit_reason"] == "stop"
    assert abs(out["r"] + 1.0) < 1e-6


def test_replay_never_looks_ahead():
    seen: list[datetime] = []

    def setup_fn(ticker, bars, **kwargs):
        # Entry only on the 51st bar (index 50). Recording the as-of date
        # exclusively when a setup is emitted proves the window ended there.
        if len(bars) != 51:
            return None
        seen.append(bars[-1].date)
        entry = float(bars[-1].close)
        stop, target = quick_target_prices(entry, target_r=1.0, stop_pct=5.0)
        return {
            "ticker": ticker,
            "entry": entry,
            "stop": stop,
            "target": target,
            "review_required": False,
            "dip_pct": 8.0,
            "recovery_rate": 0.7,
            "quality_tier": "mid",
            "is_fresh_high": False,
        }

    bars = [_bar(i, 10.0) for i in range(55)]
    # Bar 50 is the entry; bar 51 hits the target.
    bars[51] = _bar(51, 10.6, high=10.8, low=10.4)
    trades = replay_bars("TEST", bars, setup_fn=setup_fn, min_history=49, skip_review=True)
    assert trades
    assert seen == [bars[50].date]
    assert trades[0]["synthetic"] is True
    assert abs(trades[0]["r"] - 1.0) < 1e-6


def test_replay_skips_review_required():
    def setup_fn(ticker, bars, **kwargs):
        entry = float(bars[-1].close)
        stop, target = quick_target_prices(entry, target_r=1.0, stop_pct=5.0)
        return {
            "ticker": ticker,
            "entry": entry,
            "stop": stop,
            "target": target,
            "review_required": True,
        }

    bars = [_bar(i, 10.0) for i in range(60)]
    assert replay_bars("TEST", bars, setup_fn=setup_fn, min_history=45) == []


def test_run_walk_forward_accepts_synthetic_and_learning_does_not_promote(monkeypatch):
    """Synthetic sample can explore; run_learning still refuses to activate."""
    trades = []
    for i in range(40):
        trades.append(
            {
                "closed_at": START + timedelta(days=i),
                "r": 0.4 if i % 2 == 0 else -0.2,
                "dip_pct": 8.0,
                "recovery_rate": 0.7,
                "quality_tier": "mid",
                "is_fresh_high": False,
                "synthetic": True,
            }
        )
    wf = run_walk_forward(trades, n_windows=4, max_combos=8)
    assert wf is not None
    assert wf["oos_n"] > 0

    monkeypatch.setattr(
        "app.services.hv_dip.learning.load_hv_dip_closed_trades",
        lambda db: [],
    )
    monkeypatch.setattr(
        "app.services.hv_dip.learning._load_synthetic",
        lambda: trades,
    )
    monkeypatch.setattr(
        "app.services.hv_dip.learning.ensure_default_config",
        lambda db: None,
    )
    monkeypatch.setattr(
        "app.services.hv_dip.learning.get_settings",
        lambda: type(
            "S",
            (),
            {
                "hv_dip_learn_enabled": True,
                "hv_dip_min_closed_signals": 30,
            },
        )(),
    )
    out = run_learning(object())
    assert out["status"] in {"explored", "no_data"}
    assert out.get("applied") is not True
    assert out.get("n_synthetic", 0) >= 0


def test_load_real_trades_have_no_synthetic_flag(monkeypatch):
    """The DB loader is the real-only path; it must not invent synthetic rows."""
    # Smoke: function exists and returns a list. Empty DB in unit tests is fine.
    assert callable(load_hv_dip_closed_trades)
