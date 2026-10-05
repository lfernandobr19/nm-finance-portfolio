"""Multiple-testing controls: exact binomial p-values, Benjamini-Hochberg, guards."""

from __future__ import annotations

import random

import pytest

from app.services.stats import (
    benjamini_hochberg,
    binomial_test_greater,
    binomial_test_less,
)
from app.services.studies.apply import evaluate
from app.services.studies.models import StudyResult


def _universe(
    fingerprint: str,
    *,
    n: int,
    p_recover: float | None,
    p_higher: float = 0.3,
    p_stop: float = 0.4,
) -> StudyResult:
    return StudyResult(
        query_id=f"q_{fingerprint}",
        label=fingerprint,
        channel="hv_dip",
        fingerprint=fingerprint,
        ticker="UNIVERSE",
        n=n,
        p_higher=p_higher,
        p_stop_first=p_stop,
        p_recover=p_recover,
    )


# --------------------------------------------------------------------------- #
# Exact binomial
# --------------------------------------------------------------------------- #

def test_binomial_less_matches_hand_computed_values():
    # P(X <= 0) with n=2, p=0.5 is 0.25; P(X <= 1) is 0.75.
    assert binomial_test_less(0, 2, 0.5) == pytest.approx(0.25)
    assert binomial_test_less(1, 2, 0.5) == pytest.approx(0.75)
    assert binomial_test_less(2, 2, 0.5) == pytest.approx(1.0)


def test_binomial_greater_is_the_complement_tail():
    assert binomial_test_greater(2, 2, 0.5) == pytest.approx(0.25)
    assert binomial_test_greater(0, 2, 0.5) == pytest.approx(1.0)


def test_binomial_handles_degenerate_input():
    assert binomial_test_less(0, 0) == 1.0
    assert binomial_test_greater(5, 0) == 1.0
    # Out-of-range successes are clamped rather than raising.
    assert binomial_test_less(99, 3, 0.5) == pytest.approx(1.0)


def test_binomial_survives_the_sample_sizes_the_studies_produce():
    """math.comb(3652, 1200) overflows the moment it touches a float."""
    p = binomial_test_less(1200, 3652, 0.45)
    assert 0.0 <= p < 1e-40
    assert binomial_test_greater(1200, 3652, 0.45) == pytest.approx(1.0)
    assert 0.0 <= binomial_test_less(49_000, 100_000, 0.5) < 1e-5


def test_binomial_is_monotonic_in_successes():
    tail = [binomial_test_less(k, 500, 0.45) for k in range(0, 500, 25)]
    assert tail == sorted(tail)
    assert tail[-1] == pytest.approx(1.0)


def test_binomial_is_exact_not_normal_approximation():
    """At small n the normal approximation is wrong in exactly this region."""
    # 2 of 10 successes against a fair coin: the exact tail is ~5.5%.
    assert binomial_test_less(2, 10, 0.5) == pytest.approx(0.0546875, abs=1e-6)


# --------------------------------------------------------------------------- #
# Benjamini-Hochberg
# --------------------------------------------------------------------------- #

def test_bh_on_known_p_values():
    # With m=4 and alpha=0.10 the thresholds are .025, .05, .075, .10.
    mask = benjamini_hochberg([0.001, 0.04, 0.30, 0.80], alpha=0.10)
    assert mask == [True, True, False, False]


def test_bh_rejects_everything_when_nothing_is_strong():
    assert benjamini_hochberg([0.20, 0.35, 0.60], alpha=0.10) == [False, False, False]


def test_bh_keeps_order_of_the_input():
    mask = benjamini_hochberg([0.90, 0.001, 0.85], alpha=0.10)
    assert mask == [False, True, False]


def test_bh_is_a_step_up_procedure():
    """A large p below the cutoff rank still survives if a later one clears it."""
    # m=5, alpha=0.5 -> thresholds .1 .2 .3 .4 .5; p=(0.09, 0.19, 0.29, 0.39, 0.49)
    # the largest clearing rank is 5, so all five are rejected.
    mask = benjamini_hochberg([0.09, 0.19, 0.29, 0.39, 0.49], alpha=0.5)
    assert mask == [True] * 5


def test_bh_on_empty_input():
    assert benjamini_hochberg([], alpha=0.1) == []


def test_bh_controls_false_discoveries_on_pure_noise():
    """The whole point: random data must not manufacture discoveries."""
    rng = random.Random(42)
    discoveries = 0
    for _ in range(200):
        # 20 fair coins, 40 flips each, tested for being worse than chance.
        p_values = [
            binomial_test_less(sum(rng.random() < 0.5 for _ in range(40)), 40, 0.5)
            for _ in range(20)
        ]
        discoveries += sum(benjamini_hochberg(p_values, alpha=0.10))
    # Uncorrected, p<0.10 would fire about 2 times per run (400 total).
    assert discoveries < 120


# --------------------------------------------------------------------------- #
# Guards through the FDR gate
# --------------------------------------------------------------------------- #

def test_a_clearly_broken_pattern_still_becomes_a_guard():
    """Correction must not make the system blind to a real problem."""
    results = [_universe("deep_dip", n=200, p_recover=0.10)]
    out = evaluate(results)
    assert "hv_dip:deep_dip" in out["guards"]
    assert out["guards"]["hv_dip:deep_dip"]["force_review"] is True
    assert out["guards"]["hv_dip:deep_dip"]["p_value"] < 0.10


def test_a_marginally_weak_pattern_no_longer_fires():
    """Below even odds but too few samples: FDR holds it (no guard on noise)."""
    results = [_universe("marginal", n=32, p_recover=0.40)]
    out = evaluate(results)
    decision = out["decisions"][0]
    assert decision["p_recover"] < 0.50  # below the user's even-odds ruler
    assert out["guards"] == {}
    assert "não sobrevive ao FDR" in decision["reason"]


def test_small_samples_are_skipped_before_any_test():
    out = evaluate([_universe("thin", n=5, p_recover=0.0)], floor=30)
    assert out["decisions"][0]["action"] == "skipped"
    assert out["n_tested"] == 0
    assert out["guards"] == {}


def test_per_ticker_rows_are_not_tested():
    r = _universe("deep_dip", n=200, p_recover=0.1)
    r.ticker = "AMD"
    out = evaluate([r])
    assert out["n_tested"] == 0
    assert out["guards"] == {}


def test_missing_outcomes_hold_without_a_p_value():
    r = _universe("no_outcome", n=100, p_recover=None)
    out = evaluate([r])
    assert out["decisions"][0]["action"] == "hold"
    assert out["n_tested"] == 0


def test_testing_many_patterns_raises_the_bar_for_each():
    """The same marginal pattern is harder to flag when tested alongside others."""
    weak = _universe("weak", n=60, p_recover=0.20)
    alone = evaluate([weak])
    crowd = evaluate([weak] + [
        _universe(f"fine{i}", n=60, p_recover=0.60) for i in range(19)
    ])
    assert len(alone["guards"]) >= len(crowd["guards"])
