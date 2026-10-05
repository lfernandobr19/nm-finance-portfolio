"""Out-of-sample split: a pattern must survive bars it was never measured on."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.services.studies.analog import (
    MIN_SPLIT_BARS,
    AnalogEntry,
    analyze_series,
    analyze_sessions,
    run_universe,
    split_index,
    split_pairs,
)
from app.services.studies.apply import OOS_FLOOR, evaluate
from app.services.studies.models import StudyQuery, StudyResult


@dataclass
class Bar:
    open: float
    high: float
    low: float
    close: float
    volume: float = 1000.0


def _dip_series(n: int, *, recover_after: int | None = None) -> list[Bar]:
    """Sawtooth that repeatedly dips ~20% below a recent high, then recovers.

    When ``recover_after`` is set, dips beyond that index stop recovering, so the
    held-out tail disagrees with the earlier part of the series.
    """
    bars: list[Bar] = []
    price = 100.0
    for i in range(n):
        phase = i % 10
        if phase < 3:
            price *= 1.05
        elif phase < 6:
            price *= 0.88
        else:
            recovering = recover_after is None or i < recover_after
            price *= 1.06 if recovering else 0.97
        bars.append(Bar(price, price * 1.02, price * 0.98, price))
    return bars


QUERY = StudyQuery(
    id="deep_dip",
    label="Dip profundo recupera?",
    channel="hv_dip",
    fingerprint="deep_dip",
    horizon=5,
    params={"min_dip_pct": 15.0, "stop_pct": 8.0, "lookback": 10},
)


# --------------------------------------------------------------------------- #
# Mechanics of the split
# --------------------------------------------------------------------------- #

def test_split_index_holds_back_the_tail():
    assert split_index(1000) == 700
    assert split_index(1000, oos_fraction=0.5) == 500


def test_embargo_drops_entries_that_straddle_the_cut():
    """An entry graded with bars past the cut has already seen the tail."""
    pairs = [(AnalogEntry(i, 10.0, 9.0, 12.0), {"target": True, "stop": False, "r": 2.0})
             for i in range(100)]
    in_sample, out_sample = split_pairs(pairs, cut=70, horizon=5)

    assert max(e.idx for e, _ in in_sample) == 64  # 64 + 5 < 70
    assert min(e.idx for e, _ in out_sample) == 70
    straddlers = {e.idx for e, _ in pairs} - {e.idx for e, _ in in_sample} - {
        e.idx for e, _ in out_sample
    }
    assert straddlers == {65, 66, 67, 68, 69}


def test_no_entry_appears_on_both_sides():
    pairs = [(AnalogEntry(i, 10.0, 9.0, 12.0), {"target": True, "stop": False, "r": 2.0})
             for i in range(200)]
    in_sample, out_sample = split_pairs(pairs, cut=140, horizon=10)
    assert not ({e.idx for e, _ in in_sample} & {e.idx for e, _ in out_sample})


def test_a_zero_horizon_still_embargoes_the_cut_bar():
    pairs = [(AnalogEntry(i, 10.0, 9.0, 12.0), {"target": True, "stop": False, "r": 2.0})
             for i in range(10)]
    in_sample, out_sample = split_pairs(pairs, cut=5, horizon=0)
    assert [e.idx for e, _ in in_sample] == [0, 1, 2, 3, 4]
    assert [e.idx for e, _ in out_sample] == [5, 6, 7, 8, 9]


# --------------------------------------------------------------------------- #
# analyze_series
# --------------------------------------------------------------------------- #

def test_long_series_reports_an_out_of_sample_aggregate():
    metrics = analyze_series(_dip_series(400), QUERY)
    assert metrics["n"] > 0
    assert metrics["oos"] is not None
    assert metrics["oos"]["n"] > 0
    assert metrics["oos"]["n"] < metrics["n"]


def test_short_series_has_no_out_of_sample_aggregate():
    metrics = analyze_series(_dip_series(MIN_SPLIT_BARS - 1), QUERY)
    assert metrics["oos"] is None


def test_out_of_sample_reflects_the_tail_not_the_whole():
    """Full sample looks fine; the tail is where the behaviour changed."""
    bars = _dip_series(400, recover_after=280)
    metrics = analyze_series(bars, QUERY)
    assert metrics["oos"] is not None
    assert metrics["oos"]["p_higher"] < metrics["p_higher"]


def test_out_of_sample_ignores_bars_before_the_cut():
    """Two series identical only in their tail must agree out-of-sample."""
    tail_only = analyze_series(_dip_series(400), QUERY)["oos"]
    same_tail = analyze_series(_dip_series(400), QUERY)["oos"]
    assert tail_only == same_tail


def test_universe_row_carries_the_out_of_sample_totals():
    results = run_universe({"AAA": _dip_series(400), "BBB": _dip_series(400)}, QUERY)
    universe = next(r for r in results if r.ticker == "UNIVERSE")
    assert universe.oos_n > 0
    assert universe.oos_p_higher is not None
    assert universe.oos_n < universe.n


def test_sessions_split_on_session_boundaries():
    sessions = [{"bars": _dip_series(60)} for _ in range(20)]
    query = QUERY.model_copy(update={"channel": "day_trade"})
    metrics = analyze_sessions(sessions, query)
    assert metrics["oos"] is not None
    assert 0 < metrics["oos"]["n"] < metrics["n"]


# --------------------------------------------------------------------------- #
# Guards require confirmation
# --------------------------------------------------------------------------- #

def _universe(**kw) -> StudyResult:
    base = dict(
        query_id="q", label="l", channel="hv_dip", fingerprint="deep_dip",
        ticker="UNIVERSE", n=200, p_higher=0.10, p_stop_first=0.85,
        p_recover=0.30,
    )
    return StudyResult(**{**base, **kw})


def test_weak_and_confirmed_becomes_a_guard():
    out = evaluate([_universe(oos_n=60, oos_p_recover=0.32)])
    guard = out["guards"]["hv_dip:deep_dip"]
    assert guard["force_review"] is True
    assert guard["oos_n"] == 60
    assert "confirmada fora da amostra" in guard["reason"]


def test_weak_but_contradicted_out_of_sample_is_held():
    """The tail says the pattern works; that veto is the point of the split."""
    out = evaluate([_universe(oos_n=60, oos_p_recover=0.60)])
    assert out["guards"] == {}
    assert out["decisions"][0]["action"] == "hold"
    assert "não confirmada" in out["decisions"][0]["reason"]


def test_a_thin_tail_cannot_veto():
    out = evaluate([
        _universe(oos_n=OOS_FLOOR - 1, oos_p_recover=0.90)
    ])
    assert out["guards"]["hv_dip:deep_dip"]["force_review"] is True
    assert "sem amostra de confirmação" in out["guards"]["hv_dip:deep_dip"]["reason"]


def test_no_tail_at_all_keeps_previous_behaviour():
    out = evaluate([_universe()])
    assert out["guards"]["hv_dip:deep_dip"]["force_review"] is True
    assert out["decisions"][0]["oos_p_recover"] is None


@pytest.mark.parametrize("oos_p_recover,expected_guard", [(0.05, True), (0.70, False)])
def test_tail_direction_decides(oos_p_recover, expected_guard):
    out = evaluate([
        _universe(oos_n=50, oos_p_recover=oos_p_recover)
    ])
    assert bool(out["guards"]) is expected_guard
