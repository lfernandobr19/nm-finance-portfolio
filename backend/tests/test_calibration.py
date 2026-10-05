"""Calibration primitives: reliability curve, Brier decomposition, Platt scaling."""

from __future__ import annotations

import random

from app.services.learn import calibration as calib_mod
from app.services.learn.calibration import (
    apply_platt,
    brier,
    brier_decomposition,
    calibrate,
    calibrated_probability,
    expected_calibration_error,
    fit_platt,
    load_calibrators,
    refit_if_due,
    reliability_curve,
)


def _overconfident(n: int = 400, seed: int = 7) -> list[tuple[float, bool]]:
    """Says ~0.8, is right ~0.43: the failure mode the news classifier shows."""
    rng = random.Random(seed)
    pairs = []
    for _ in range(n):
        p = rng.uniform(0.65, 0.95)
        true_rate = 0.30 + 0.25 * (p - 0.65) / 0.30
        pairs.append((p, rng.random() < true_rate))
    return pairs


def _well_calibrated(n: int = 400, seed: int = 11) -> list[tuple[float, bool]]:
    rng = random.Random(seed)
    pairs = []
    for _ in range(n):
        p = rng.uniform(0.05, 0.95)
        pairs.append((p, rng.random() < p))
    return pairs


def test_brier_matches_known_values():
    assert brier([(1.0, True), (0.0, False)]) == 0.0
    assert brier([(0.5, True), (0.5, False)]) == 0.25
    assert brier([(1.0, False)]) == 1.0
    assert brier([]) is None


def test_reliability_curve_buckets_and_drops_empties():
    pairs = [(0.05, False), (0.05, False), (0.95, True), (0.95, True)]
    curve = reliability_curve(pairs, n_bins=10)

    assert len(curve) == 2  # only the two populated buckets
    low, high = curve
    assert low["n"] == 2 and low["freq"] == 0.0
    assert high["n"] == 2 and high["freq"] == 1.0
    assert abs(low["gap"]) < 0.1 and abs(high["gap"]) < 0.1


def test_reliability_curve_exposes_the_gap_when_overconfident():
    curve = reliability_curve(_overconfident(), n_bins=10)
    # Every populated bucket should predict higher than it delivers.
    assert curve
    assert all(b["gap"] > 0 for b in curve)


def test_platt_fixes_overconfidence():
    pairs = _overconfident()
    raw = brier(pairs)
    a, b = fit_platt(pairs)
    calibrated = [(apply_platt(p, a, b), y) for p, y in pairs]

    assert raw > 0.25  # worse than "always say 50%"
    assert brier(calibrated) < 0.25  # and now better
    assert brier(calibrated) < raw

    mean_cal = sum(p for p, _ in calibrated) / len(calibrated)
    base_rate = sum(1 for _, y in pairs if y) / len(pairs)
    assert abs(mean_cal - base_rate) < 0.05


def test_platt_does_not_wreck_already_calibrated_input():
    pairs = _well_calibrated()
    a, b = fit_platt(pairs)
    calibrated = [(apply_platt(p, a, b), y) for p, y in pairs]
    # Allowed to be a touch worse from estimating two parameters, never a lot.
    assert brier(calibrated) <= brier(pairs) + 0.01


def test_platt_is_identity_on_degenerate_samples():
    assert fit_platt([]) == (-1.0, 0.0)
    assert fit_platt([(0.6, True)]) == (-1.0, 0.0)
    # Single-class history must not encode "always wins".
    assert fit_platt([(0.6, True), (0.7, True), (0.8, True)]) == (-1.0, 0.0)


def test_apply_platt_is_monotonic_in_the_raw_score():
    a, b = fit_platt(_overconfident())
    probs = [apply_platt(p, a, b) for p in (0.1, 0.3, 0.5, 0.7, 0.9)]
    assert probs == sorted(probs)
    assert all(0.0 <= p <= 1.0 for p in probs)


def test_brier_decomposition_identity_holds():
    pairs = _overconfident()
    d = brier_decomposition(pairs)
    assert d is not None
    # Murphy: BS = reliability - resolution + uncertainty
    rebuilt = d["reliability"] - d["resolution"] + d["uncertainty"]
    assert abs(rebuilt - d["brier"]) < 1e-3


def test_decomposition_separates_miscalibration_from_no_signal():
    d = brier_decomposition(_overconfident())
    # Badly scaled but the error is in reliability, which Platt can remove.
    assert d["reliability"] > 0.05
    # And it barely discriminates, which no rescaling can fix.
    assert d["resolution"] < 0.05


def test_expected_calibration_error_is_zero_for_perfect_input():
    perfect = [(0.0, False)] * 50 + [(1.0, True)] * 50
    assert expected_calibration_error(perfect) == 0.0
    assert expected_calibration_error([]) is None


def test_refit_requires_enough_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(calib_mod, "_COEF_PATH", tmp_path / "calibration.json")
    assert refit_if_due("news", _overconfident(n=10)) is None
    assert load_calibrators() == {}


def test_refit_persists_and_is_reused(tmp_path, monkeypatch):
    monkeypatch.setattr(calib_mod, "_COEF_PATH", tmp_path / "calibration.json")
    pairs = _overconfident()

    entry = refit_if_due("news", pairs)
    assert entry is not None
    assert entry["n"] == 400
    assert entry["brier_calibrated"] < entry["brier_raw"]
    assert load_calibrators()["news"]["platt_a"] == entry["platt_a"]

    # Same evidence: no churn, the stored fit is returned as-is.
    again = refit_if_due("news", pairs)
    assert again["fitted_at"] == entry["fitted_at"]


def test_calibrated_probability_falls_back_to_raw(tmp_path, monkeypatch):
    monkeypatch.setattr(calib_mod, "_COEF_PATH", tmp_path / "calibration.json")
    # Unfitted source: untouched rather than guessed at.
    assert calibrated_probability("hv_dip", 0.83) == 0.83

    refit_if_due("news", _overconfident())
    assert calibrated_probability("news", 0.83) < 0.83


def test_calibrated_probability_falls_back_to_pooled_source(tmp_path, monkeypatch):
    monkeypatch.setattr(calib_mod, "_COEF_PATH", tmp_path / "calibration.json")
    refit_if_due("news", _overconfident())
    # Type-specific key is missing; the pooled news curve still remaps.
    typed = calibrated_probability("news:guidance_up", 0.83, fallback="news")
    pooled = calibrated_probability("news", 0.83)
    assert typed == pooled
    assert typed < 0.83


def test_news_calibrator_key_is_namespaced():
    from app.services.learn.calibration import news_calibrator_key

    assert news_calibrator_key("product_launch") == "news:product_launch"
    assert news_calibrator_key("") == "news:other"


def test_calibrate_report_shape():
    report = calibrate(_overconfident())
    assert report["n"] == 400
    assert report["brier_calibrated"] < report["brier_raw"]
    assert report["ece_calibrated"] < report["ece_raw"]
    assert report["decomposition"]["n"] == 400
    assert report["curve"]
