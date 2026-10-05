"""Shared statistics helpers (no scipy/numpy).

Extracted from day_trade/learning.py so the hv_dip learn loop reuses the exact
same DSR/PBO math (DRY). Signatures are unchanged to avoid breaking the day
trade loop, which now imports from here.
"""

from __future__ import annotations

import math
import random

_EULER = 0.5772156649015329


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p: float) -> float:
    """Inverse normal CDF (Acklam's rational approximation)."""
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    ]
    p_low = 0.02425
    p_high = 1.0 - p_low
    p = min(max(p, 1e-12), 1.0 - 1e-12)
    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        num = ((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]
        den = (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        return num / den
    if p <= p_high:
        q = p - 0.5
        r = q * q
        num = ((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]
        den = ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0
        return num * q / den
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    num = ((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]
    den = (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
    return -num / den


def _moments(values: list[float]) -> tuple[float, float, float]:
    n = len(values)
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1) if n > 1 else 0.0
    std = math.sqrt(var)
    if std <= 1e-12:
        return 0.0, 3.0, std
    skew = sum(((v - mean) / std) ** 3 for v in values) / n
    kurt = sum(((v - mean) / std) ** 4 for v in values) / n
    return skew, kurt, std


def sharpe(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    if var <= 1e-12:
        return 0.0
    return mean / math.sqrt(var)


def deflated_sharpe_ratio(returns: list[float], n_trials: int) -> float:
    """Deflated Sharpe Ratio (Bailey & Lopez de Prado) as a probability in [0,1].

    Higher = more likely the Sharpe is real and not a multiple-testing artifact.
    """
    n = len(returns)
    if n < 3:
        return 0.0
    sr = sharpe(returns)
    skew, kurt, _std = _moments(returns)
    var_sr = (1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr) / (n - 1)
    if var_sr <= 0:
        var_sr = 1.0 / (n - 1)
    z1 = norm_ppf(1.0 - 1.0 / max(n_trials, 1))
    z2 = norm_ppf(1.0 - 1.0 / (max(n_trials, 1) * math.e))
    sr_star = math.sqrt(var_sr) * ((1.0 - _EULER) * z1 + _EULER * z2)
    den = math.sqrt(max(1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr, 1e-12))
    return norm_cdf((sr - sr_star) * math.sqrt(n - 1) / den)


def probability_of_backtest_overfitting(
    matrix: list[list[float]],
    *,
    s_blocks: int = 8,
    n_combinations: int = 100,
    seed: int = 42,
) -> float:
    """CSCV probability of backtest overfitting (Lopez de Prado).

    `matrix` rows are OOS observations (windows), cols are configurations.
    Returns probability in [0,1] that in-sample selection does NOT generalize.
    """
    rows = len(matrix)
    if rows < s_blocks:
        return 1.0
    cols = len(matrix[0]) if matrix else 0
    if cols < 2:
        return 1.0
    block_size = rows // s_blocks
    blocks = [matrix[i * block_size : (i + 1) * block_size] for i in range(s_blocks)]
    rng = random.Random(seed)
    half = s_blocks // 2
    logits: list[float] = []
    for _ in range(n_combinations):
        idx = list(range(s_blocks))
        rng.shuffle(idx)
        iset = set(idx[:half])
        oset = set(idx[half:])
        is_perf = [0.0] * cols
        oos_perf = [0.0] * cols
        for b in iset:
            for row in blocks[b]:
                for c in range(cols):
                    is_perf[c] += row[c]
        for b in oset:
            for row in blocks[b]:
                for c in range(cols):
                    oos_perf[c] += row[c]
        best_c = max(range(cols), key=lambda c: is_perf[c])
        rank = sum(1 for c in range(cols) if oos_perf[c] <= oos_perf[best_c]) / cols
        rank = min(max(rank, 1e-9), 1.0 - 1e-9)
        logits.append(math.log(rank / (1.0 - rank)))
    below = sum(1 for l in logits if l < 0.0)
    return below / len(logits)


def binomial_test_less(successes: int, n: int, p_null: float = 0.5) -> float:
    """Exact one-sided p-value for ``successes`` being lower than chance.

    ``P(X <= successes)`` under ``Binomial(n, p_null)``, computed exactly rather
    than through a normal approximation: the study samples here are often in the
    dozens, where the approximation is worst and would happily call noise
    significant.

    Summed in log space: ``math.comb(3652, 1200)`` is an integer with hundreds
    of digits and overflows the moment it meets a float, which is well inside
    the sample sizes the universe studies produce.
    """
    if n <= 0:
        return 1.0
    successes = max(0, min(int(successes), n))
    p_null = min(1.0 - 1e-12, max(1e-12, float(p_null)))

    log_p = math.log(p_null)
    log_q = math.log1p(-p_null)
    log_fact_n = math.lgamma(n + 1)

    total = 0.0
    for k in range(successes + 1):
        log_term = (
            log_fact_n - math.lgamma(k + 1) - math.lgamma(n - k + 1)
            + k * log_p + (n - k) * log_q
        )
        if log_term > -745.0:  # below this, exp underflows to zero anyway
            total += math.exp(log_term)
    return min(1.0, total)


def binomial_test_greater(successes: int, n: int, p_null: float = 0.5) -> float:
    """Exact one-sided p-value for ``successes`` beating chance: ``P(X >= successes)``."""
    if n <= 0:
        return 1.0
    successes = min(int(successes), n)
    if successes <= 0:
        # P(X >= 0) is certain. Clamping into binomial_test_less would silently
        # turn this into P(X <= 0) instead.
        return 1.0
    return min(1.0, 1.0 - binomial_test_less(successes - 1, n, p_null))


def benjamini_hochberg(p_values: list[float], alpha: float = 0.10) -> list[bool]:
    """Which hypotheses survive at false-discovery rate ``alpha``.

    Testing many patterns at once makes "significant at p < 0.05" meaningless:
    across 20 questions, one spurious winner is the *expected* result. BH sorts
    the p-values and keeps the largest ``k`` with ``p_(k) <= k/m * alpha``,
    rejecting that one and everything below it.

    Returns a mask aligned with the input order.
    """
    m = len(p_values)
    if m == 0:
        return []
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    cutoff_rank = 0
    for rank, (_, p) in enumerate(indexed, start=1):
        if p <= (rank / m) * alpha:
            cutoff_rank = rank
    mask = [False] * m
    for rank, (original_idx, _) in enumerate(indexed, start=1):
        if rank <= cutoff_rank:
            mask[original_idx] = True
    return mask


__all__ = [
    "norm_cdf",
    "norm_ppf",
    "sharpe",
    "deflated_sharpe_ratio",
    "probability_of_backtest_overfitting",
    "binomial_test_less",
    "binomial_test_greater",
    "benjamini_hochberg",
]
