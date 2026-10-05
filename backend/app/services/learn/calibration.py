"""Probability calibration in pure stdlib (the backend has no numpy/scipy).

Two distinct failures hide behind a bad Brier score, and only one of them is
fixable here:

- **Discrimination** — can the source rank winners above losers at all? No
  post-processing creates this; it needs a better model or better features.
- **Calibration** — when it says 70%, does it happen 70% of the time? This is a
  monotone remap of the score and is exactly what Platt scaling fixes.

Sigmoid/Platt is used rather than isotonic on purpose: isotonic regression
overfits badly below ~1000 samples, and this desk operates with dozens.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

logger = logging.getLogger("fiidesk.learn.calibration")

Pair = tuple[float, bool]

_COEF_PATH = Path(".cache/fiidesk/calibration.json")
# Below this, a fitted curve says more about the window than about the source.
MIN_SAMPLES = 30
# Refit only once the evidence has grown meaningfully, so coefficients do not
# jitter on every single new outcome.
REFIT_GROWTH = 1.25


def _sigmoid(z: float) -> float:
    """Numerically stable logistic."""
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


def _softplus(z: float) -> float:
    """log(1 + exp(z)) without overflow."""
    if z > 35:
        return z
    if z < -35:
        return math.exp(z)
    return math.log1p(math.exp(z))


def brier(pairs: Sequence[Pair]) -> float | None:
    """Mean squared error of the asserted probability. 0.25 = "always say 50%"."""
    if not pairs:
        return None
    total = sum((p - (1.0 if y else 0.0)) ** 2 for p, y in pairs)
    return total / len(pairs)


def reliability_curve(pairs: Sequence[Pair], n_bins: int = 10) -> list[dict[str, Any]]:
    """Observed frequency per predicted-probability bucket.

    Empty buckets are dropped rather than reported as zero, so a sparse curve
    reads as "no data here" instead of "never happens here".
    """
    if not pairs or n_bins <= 0:
        return []
    buckets: list[list[Pair]] = [[] for _ in range(n_bins)]
    for p, y in pairs:
        idx = min(n_bins - 1, max(0, int(p * n_bins)))
        buckets[idx].append((p, y))

    out: list[dict[str, Any]] = []
    for i, bucket in enumerate(buckets):
        if not bucket:
            continue
        n = len(bucket)
        p_mean = sum(p for p, _ in bucket) / n
        freq = sum(1 for _, y in bucket if y) / n
        out.append(
            {
                "bin": i,
                "lo": round(i / n_bins, 4),
                "hi": round((i + 1) / n_bins, 4),
                "n": n,
                "p_mean": round(p_mean, 4),
                "freq": round(freq, 4),
                "gap": round(p_mean - freq, 4),
            }
        )
    return out


def expected_calibration_error(pairs: Sequence[Pair], n_bins: int = 10) -> float | None:
    """Sample-weighted mean |predicted - observed| across buckets."""
    curve = reliability_curve(pairs, n_bins=n_bins)
    if not curve:
        return None
    total = sum(b["n"] for b in curve)
    if total == 0:
        return None
    return sum(b["n"] * abs(b["gap"]) for b in curve) / total


def brier_decomposition(pairs: Sequence[Pair], n_bins: int = 10) -> dict[str, Any] | None:
    """Murphy decomposition: ``BS = reliability - resolution + uncertainty``.

    Reading it is what turns a number into a diagnosis. High ``reliability``
    (it is an error term, so lower is better) means the confidences are simply
    mis-scaled and Platt will help. Near-zero ``resolution`` means the source
    says the same thing regardless of the case, and no rescaling can save it.
    """
    if not pairs:
        return None
    n_total = len(pairs)
    base_rate = sum(1 for _, y in pairs if y) / n_total
    curve = reliability_curve(pairs, n_bins=n_bins)

    rel = sum(b["n"] * (b["p_mean"] - b["freq"]) ** 2 for b in curve) / n_total
    res = sum(b["n"] * (b["freq"] - base_rate) ** 2 for b in curve) / n_total
    unc = base_rate * (1.0 - base_rate)
    return {
        "brier": round(brier(pairs) or 0.0, 6),
        "reliability": round(rel, 6),
        "resolution": round(res, 6),
        "uncertainty": round(unc, 6),
        "base_rate": round(base_rate, 4),
        "n": n_total,
    }


def fit_platt(
    pairs: Sequence[Pair],
    *,
    max_iter: int = 200,
    tol: float = 1e-7,
) -> tuple[float, float]:
    """Fit ``p_cal = sigmoid(-(a * p_raw + b))`` by regularised log-loss.

    Uses Platt's smoothed targets (``(N+ + 1)/(N+ + 2)`` and ``1/(N- + 2)``)
    instead of hard 0/1 so a small, perfectly-separated sample cannot drive the
    coefficients to infinity. Returns the identity-ish ``(-1, 0)`` when there is
    nothing to learn from, which leaves probabilities untouched.
    """
    usable = [(float(p), bool(y)) for p, y in pairs]
    if len(usable) < 2:
        return (-1.0, 0.0)

    n_pos = sum(1 for _, y in usable if y)
    n_neg = len(usable) - n_pos
    if n_pos == 0 or n_neg == 0:
        # Single-class history: any fit would encode "always/never", which is an
        # artefact of the window rather than a property of the source.
        return (-1.0, 0.0)

    hi = (n_pos + 1.0) / (n_pos + 2.0)
    lo = 1.0 / (n_neg + 2.0)
    data = [(p, hi if y else lo) for p, y in usable]

    def loss(a: float, b: float) -> float:
        total = 0.0
        for p, t in data:
            u = a * p + b
            # -[t*log(P) + (1-t)*log(1-P)] with P = sigmoid(-u), expanded to
            # stay finite for large |u|.
            total += t * u + _softplus(-u)
        return total

    def gradient(a: float, b: float) -> tuple[float, float]:
        ga = gb = 0.0
        for p, t in data:
            # d/du of the term above is t - sigmoid(-u).
            d = t - _sigmoid(-(a * p + b))
            ga += d * p
            gb += d
        return (ga, gb)

    a, b = -1.0, 0.0
    current = loss(a, b)
    step = 1.0
    for _ in range(max_iter):
        ga, gb = gradient(a, b)
        if math.hypot(ga, gb) < tol:
            break
        # Backtracking line search: the objective is convex in (a, b), so a
        # shrinking step that reduces the loss always converges.
        improved = False
        for _ in range(60):
            cand_a = a - step * ga
            cand_b = b - step * gb
            cand = loss(cand_a, cand_b)
            if cand < current:
                a, b, current = cand_a, cand_b, cand
                step *= 1.5
                improved = True
                break
            step *= 0.5
        if not improved:
            break
    return (a, b)


def apply_platt(p_raw: float, a: float, b: float) -> float:
    """Map a raw score through fitted coefficients into a calibrated probability."""
    return _sigmoid(-(a * float(p_raw) + b))


def calibrate(pairs: Sequence[Pair], n_bins: int = 10) -> dict[str, Any]:
    """Full calibration report for one source: raw, fitted, and post-fit quality."""
    a, b = fit_platt(pairs)
    calibrated = [(apply_platt(p, a, b), y) for p, y in pairs]
    return {
        "n": len(pairs),
        "platt_a": round(a, 6),
        "platt_b": round(b, 6),
        "brier_raw": round(brier(pairs), 6) if pairs else None,
        "brier_calibrated": round(brier(calibrated), 6) if pairs else None,
        "ece_raw": round(expected_calibration_error(pairs, n_bins) or 0.0, 6) if pairs else None,
        "ece_calibrated": (
            round(expected_calibration_error(calibrated, n_bins) or 0.0, 6) if pairs else None
        ),
        "decomposition": brier_decomposition(pairs, n_bins=n_bins),
        "curve": reliability_curve(pairs, n_bins=n_bins),
    }


def load_calibrators() -> dict[str, Any]:
    try:
        return json.loads(_COEF_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_calibrators(data: dict[str, Any]) -> None:
    _COEF_PATH.parent.mkdir(parents=True, exist_ok=True)
    _COEF_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def refit_if_due(source: str, pairs: Sequence[Pair]) -> dict[str, Any] | None:
    """Refit and persist one source's coefficients when the evidence has grown.

    Refuses to fit below ``MIN_SAMPLES`` and refuses to *keep* a fit that does
    not beat the raw score on the very data it was fitted to — that would be a
    transform that only adds noise.
    """
    store = load_calibrators()
    entry = store.get(source) or {}
    n = len(pairs)
    if n < MIN_SAMPLES:
        return None
    if entry.get("n") and n < int(entry["n"]) * REFIT_GROWTH:
        return entry

    report = calibrate(pairs)
    raw, cal = report["brier_raw"], report["brier_calibrated"]
    if raw is not None and cal is not None and cal > raw:
        logger.info("calibration %s: fit rejected (%.4f > %.4f raw)", source, cal, raw)
        return entry or None

    entry = {
        "source": source,
        "n": n,
        "platt_a": report["platt_a"],
        "platt_b": report["platt_b"],
        "brier_raw": raw,
        "brier_calibrated": cal,
        "resolution": (report["decomposition"] or {}).get("resolution"),
        "fitted_at": datetime.now(timezone.utc).isoformat(),
    }
    store[source] = entry
    save_calibrators(store)
    logger.info(
        "calibration %s refit n=%d brier %.4f -> %.4f", source, n, raw or 0.0, cal or 0.0
    )
    return entry


def calibrated_probability(
    source: str,
    p_raw: float,
    *,
    fallback: str | None = None,
) -> float:
    """Apply the stored mapping, or pass the raw score through untouched.

    An unfitted source is left alone rather than guessed at: inventing a
    transform from no data is exactly the overconfidence this module exists to
    remove. ``fallback`` is used when the specific source (e.g. ``news:upgrade``)
    has no fit yet — the pooled ``news`` curve is better than the raw LLM score.
    """
    store = load_calibrators()
    entry = store.get(source) or (store.get(fallback) if fallback else None)
    if not entry:
        return float(p_raw)
    return apply_platt(p_raw, float(entry["platt_a"]), float(entry["platt_b"]))


def news_calibrator_key(event_type: str | None) -> str:
    t = (event_type or "").strip() or "other"
    return f"news:{t}"


def _news_event_pairs(db) -> dict[str, list[Pair]]:
    """``(confidence, outcome)`` by event_type, preferring the longest landed horizon."""
    from app.domain.models import NewsEvent
    from app.services.llm_calibrate import HORIZONS

    events = (
        db.query(NewsEvent)
        .filter(NewsEvent.confidence.isnot(None))
        .all()
    )
    by_type: dict[str, list[Pair]] = {}
    for ev in events:
        raw = dict(ev.raw or {})
        outcome = None
        for horizon in sorted(HORIZONS, reverse=True):
            value = raw.get(f"outcome_ok_{horizon}d")
            if value is not None:
                outcome = bool(value)
                break
        if outcome is None:
            continue
        try:
            p = float(ev.confidence)
        except (TypeError, ValueError):
            continue
        key = str(ev.event_type or "other")
        by_type.setdefault(key, []).append((p, outcome))
    return by_type


def refit_news_by_type(db) -> dict[str, Any]:
    """Fit one Platt curve per event_type plus the pooled ``news`` fallback.

    Context7/sklearn: sigmoid/Platt on small per-type samples; isotonic would
    overfit well below ~1000 points, and most types sit in the dozens-to-hundreds.
    """
    grouped = _news_event_pairs(db)
    fitted: dict[str, Any] = {}
    pooled: list[Pair] = []
    for event_type, pairs in grouped.items():
        pooled.extend(pairs)
        entry = refit_if_due(news_calibrator_key(event_type), pairs)
        if entry:
            fitted[event_type] = {
                "n": entry.get("n"),
                "brier_raw": entry.get("brier_raw"),
                "brier_calibrated": entry.get("brier_calibrated"),
            }
    if pooled:
        refit_if_due("news", pooled)
    logger.info(
        "news platts fitted=%s types_seen=%d pooled=%d",
        sorted(fitted),
        len(grouped),
        len(pooled),
    )
    return {"fitted": fitted, "n_types": len(grouped), "n_pooled": len(pooled)}


__all__ = [
    "Pair",
    "MIN_SAMPLES",
    "brier",
    "reliability_curve",
    "expected_calibration_error",
    "brier_decomposition",
    "fit_platt",
    "apply_platt",
    "calibrate",
    "load_calibrators",
    "save_calibrators",
    "refit_if_due",
    "calibrated_probability",
    "news_calibrator_key",
    "refit_news_by_type",
]
