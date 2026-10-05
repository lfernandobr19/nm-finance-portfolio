"""Phase 1 debug: analog matcher over synthetic bars (n, P target vs stop, ticker vs universe)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.brapi_client import Bar
from app.services.studies.analog import (
    DEEP_HORIZONS,
    analyze_series,
    find_entries,
    run_universe,
    sweep_horizons,
)
from app.services.studies.models import StudyQuery


def _make_bars(closes: list[float]) -> list[Bar]:
    d0 = datetime(2026, 1, 5, tzinfo=timezone.utc)
    return [
        Bar(
            date=d0 + timedelta(days=i),
            open=float(c),
            high=float(c) * 1.02,
            low=float(c) * 0.98,
            close=float(c),
            volume=1_000_000.0,
        )
        for i, c in enumerate(closes)
    ]


DEEP_DIP_QUERY = StudyQuery(
    id="deep_dip",
    label="dip",
    channel="hv_dip",
    fingerprint="deep_dip",
    horizon=10,
    target_r=2.0,
    params={"min_dip_pct": 15.0, "stop_pct": 8.0, "lookback": 10},
)


def test_deep_dip_recovers_target_before_stop():
    # A single 20% dip that fully recovers: the entry hits target before stop.
    closes = [100.0] * 10 + [80.0, 85.0, 90.0, 95.0, 100.0, 105.0]
    bars = _make_bars(closes)
    entries = find_entries(bars, DEEP_DIP_QUERY)
    assert len(entries) >= 1
    result = analyze_series(bars, DEEP_DIP_QUERY)
    assert result["n"] >= 1
    assert result["p_higher"] > 0.9
    assert result["p_stop_first"] < 0.1


def test_deep_dip_grind_down_stops_first():
    # A dip that keeps grinding down: stop hit before any target.
    closes = [100.0] * 10 + [80.0, 78.0, 76.0, 74.0, 72.0, 70.0]
    bars = _make_bars(closes)
    result = analyze_series(bars, DEEP_DIP_QUERY)
    assert result["n"] >= 1
    assert result["p_stop_first"] > result["p_higher"]
    assert result["p_higher"] < 0.2


def test_no_entries_returns_zero_n():
    # No dip deep enough → n == 0, probabilities None.
    bars = _make_bars([100.0] * 30)
    result = analyze_series(bars, DEEP_DIP_QUERY)
    assert result["n"] == 0


def test_run_universe_computes_vs_universe():
    win = _make_bars([100.0] * 10 + [80.0, 85.0, 90.0, 95.0, 100.0, 105.0])
    lose = _make_bars([100.0] * 10 + [80.0, 78.0, 76.0, 74.0, 72.0, 70.0])
    results = run_universe({"WIN": win, "LOSE": lose}, DEEP_DIP_QUERY)

    by_ticker = {r.ticker: r for r in results}
    universe = by_ticker["UNIVERSE"]
    assert universe.n == sum(r.n for r in results if r.ticker != "UNIVERSE")
    assert universe.p_higher is not None
    # The recovering ticker beats the universe; the grinding ticker trails it.
    assert by_ticker["WIN"].vs_universe > 0
    assert by_ticker["LOSE"].vs_universe < 0


def test_recovery_is_true_on_bounce_and_false_after_stop():
    win = analyze_series(
        _make_bars([100.0] * 10 + [80.0, 85.0, 90.0, 95.0, 100.0, 105.0]),
        DEEP_DIP_QUERY,
    )
    lose = analyze_series(
        _make_bars([100.0] * 10 + [80.0, 78.0, 76.0, 74.0, 72.0, 70.0]),
        DEEP_DIP_QUERY,
    )
    assert win["n"] >= 1
    assert win["recovery"] > 0.9
    assert lose["n"] >= 1
    assert lose["recovery"] < 0.1


def test_gap_hit_is_none_without_a_material_gap():
    # Dip already printed on the previous close, so the entry itself is not a gap.
    bars = _make_bars([100.0] * 9 + [80.0] * 6)
    result = analyze_series(bars, DEEP_DIP_QUERY)
    assert result["n"] >= 1
    assert result["gap_hit"] is None


def test_sweep_horizons_covers_recovery_and_gap_hit():
    win = _make_bars([100.0] * 10 + [80.0, 85.0, 90.0, 95.0, 100.0, 105.0])
    findings = sweep_horizons({"WIN": win}, [DEEP_DIP_QUERY], horizons=(5, 10))
    assert {f["horizon"] for f in findings} == {5, 10}
    assert all(f["fingerprint"] == "deep_dip" for f in findings)
    assert all("recovery" in f and "gap_hit" in f for f in findings)
    assert set(DEEP_HORIZONS) == {5, 10, 20, 40}
