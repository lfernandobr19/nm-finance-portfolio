"""Numeric analog matcher: casar padrões nos bares e medir o desfecho à frente.

Pure Python over cached bars (no numpy/scipy, no DTW/pandas-ta). Probabilities
come only from OHLC; the LLM never computes them. Fingerprints are the desk's
existing patterns: deep dip (hv_dip), breakout+H1 (swing), ORB/VWAP (day trade).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.services.studies.models import StudyQuery, StudyResult


@dataclass
class AnalogEntry:
    idx: int
    entry: float
    stop: float
    target: float
    trend_up: bool | None = None
    ref_high: float | None = None
    prev_close: float | None = None


def _forward(bars: list[Any], e: AnalogEntry, horizon: int) -> dict[str, Any] | None:
    """Outcome of an entry over the next ``horizon`` bars (stop checked first).

    ``recovery`` and ``gap_hit`` are measured on the same path window as the
    exit — bars after a stop/target fill are not consulted (no look-ahead).
    """
    fut = bars[e.idx + 1 : e.idx + 1 + horizon]
    if not fut or e.entry <= e.stop:
        return None
    hit_target = False
    hit_stop = False
    exit_price: float | None = None
    visited: list[Any] = []
    for b in fut:
        visited.append(b)
        if float(b.low) <= e.stop:
            hit_stop = True
            exit_price = e.stop
            break
        if float(b.high) >= e.target:
            hit_target = True
            exit_price = e.target
            break
    if exit_price is None:
        exit_price = float(fut[-1].close)
    risk = e.entry - e.stop
    r = (exit_price - e.entry) / risk if risk > 0 else 0.0

    window = visited or fut
    max_high = max(float(b.high) for b in window)
    min_low = min(float(b.low) for b in window)

    recovery = False
    if not hit_stop:
        if e.ref_high is not None and e.ref_high > e.entry:
            halfway = e.entry + 0.5 * (e.ref_high - e.entry)
            recovery = max_high >= halfway
        else:
            recovery = max_high >= e.entry

    gap_hit: bool | None = None
    prev = e.prev_close
    if prev is not None and prev > 0:
        gap_pct = abs(e.entry - prev) / prev
        if gap_pct >= 0.01:
            if e.entry < prev:
                gap_hit = max_high >= prev
            else:
                gap_hit = min_low <= prev

    # The user's ruler: "does it appreciate again in ~2 weeks?" — the close after
    # the horizon is above the entry, *unconditioned* on an intermediate stop.
    # This is about the stock recovering, not about the strategy's stop leg.
    recover = float(fut[-1].close) > e.entry

    return {
        "target": hit_target,
        "stop": hit_stop,
        "r": r,
        "recovery": recovery,
        "gap_hit": gap_hit,
        "recover": recover,
    }


def _daily_sma_trend(bars: list[Any], idx: int, period: int = 20) -> bool | None:
    closes = [float(b.close) for b in bars[: idx + 1]]
    if len(closes) < period:
        return None
    return closes[-1] >= (sum(closes[-period:]) / period)


# --------------------------------------------------------------------------- #
# Fingerprints (each returns historical analog entries for a bar series)
# --------------------------------------------------------------------------- #
def _deep_dip(bars: list[Any], q: StudyQuery) -> list[AnalogEntry]:
    """Entry when price drops >= min_dip_pct below a recent lookback high."""
    min_dip = float(q.params.get("min_dip_pct", 15.0))
    stop_pct = float(q.params.get("stop_pct", q.stop_pct if q.stop_pct is not None else 8.0))
    lookback = int(q.params.get("lookback", 10))
    entries: list[AnalogEntry] = []
    for i in range(lookback, len(bars)):
        window = bars[i - lookback : i]
        if not window:
            continue
        hi = max(float(b.high) for b in window)
        if hi <= 0:
            continue
        close = float(bars[i].close)
        dip = (hi - close) / hi * 100.0
        if dip < min_dip:
            continue
        stop = close * (1.0 - stop_pct / 100.0)
        target = close + q.target_r * (close - stop)
        prev = float(bars[i - 1].close) if i > 0 else None
        entries.append(
            AnalogEntry(
                i, close, stop, target, _daily_sma_trend(bars, i),
                ref_high=hi, prev_close=prev,
            )
        )
    return entries


def _breakout_h1(bars: list[Any], q: StudyQuery) -> list[AnalogEntry]:
    """Entry on a daily breakout; stop = recent swing low; weekly trend context."""
    from app.services.swing.indicators import (
        daily_breakout_long,
        derive_weekly,
        recent_swing_low,
        weekly_trend_bullish,
    )

    lookback = int(q.params.get("lookback", 10))
    entries: list[AnalogEntry] = []
    for i in range(lookback + 1, len(bars)):
        past = bars[: i + 1]
        broke, level = daily_breakout_long(past, lookback)
        if not broke or level is None:
            continue
        stop = recent_swing_low(past, lookback)
        entry = float(bars[i].close)
        if stop is None or stop <= 0 or stop >= entry:
            continue
        target = entry + q.target_r * (entry - stop)
        weekly = derive_weekly(past)
        trend = weekly_trend_bullish(weekly) if weekly else None
        prev = float(bars[i - 1].close) if i > 0 else None
        entries.append(
            AnalogEntry(i, entry, stop, target, trend, ref_high=level, prev_close=prev)
        )
    return entries


def _orb(bars: list[Any], q: StudyQuery) -> list[AnalogEntry]:
    """Opening-range breakout: first N bars set the range; entry on the break (long)."""
    orb_minutes = int(q.params.get("orb_minutes", 15))
    bar_minutes = int(q.params.get("bar_minutes", 5))
    orb_bars = max(1, int(orb_minutes / bar_minutes))
    if len(bars) < orb_bars + 1:
        return []
    rng_hi = max(float(b.high) for b in bars[:orb_bars])
    rng_lo = min(float(b.low) for b in bars[:orb_bars])
    if rng_hi <= rng_lo:
        return []
    for i in range(orb_bars, len(bars)):
        close = float(bars[i].close)
        if close > rng_hi:
            stop = rng_lo
            target = close + q.target_r * (close - stop)
            prev = float(bars[i - 1].close) if i > 0 else None
            return [
                AnalogEntry(
                    i, close, stop, target, None, ref_high=rng_hi, prev_close=prev,
                )
            ]
    return []


def _vwap_reclaim(bars: list[Any], q: StudyQuery) -> list[AnalogEntry]:
    """Entry when price reclaims the session VWAP from below (mean-reversion up)."""
    entries: list[AnalogEntry] = []
    cum_pv = 0.0
    cum_v = 0.0
    was_below = False
    for i, b in enumerate(bars):
        typical = (float(b.high) + float(b.low) + float(b.close)) / 3.0
        v = float(b.volume) or 0.0
        cum_pv += typical * v
        cum_v += v
        if cum_v <= 0:
            continue
        vwap = cum_pv / cum_v
        close = float(b.close)
        if close < vwap:
            was_below = True
        elif was_below and close > vwap:
            stop = vwap * (1.0 - 0.01)
            target = close + q.target_r * (close - stop)
            prev = float(bars[i - 1].close) if i > 0 else None
            entries.append(AnalogEntry(i, close, stop, target, None, prev_close=prev))
            was_below = False
    return entries


_FINGERPRINT_FNS: dict[str, Callable[[list[Any], StudyQuery], list[AnalogEntry]]] = {
    "deep_dip": _deep_dip,
    "breakout_h1": _breakout_h1,
    "orb": _orb,
    "vwap_reclaim": _vwap_reclaim,
}


def find_entries(bars: list[Any], query: StudyQuery) -> list[AnalogEntry]:
    fn = _FINGERPRINT_FNS.get(query.fingerprint)
    if fn is None:
        return []
    return fn(bars, query)


def _aggregate(entries: list[AnalogEntry], outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(outcomes)
    if n == 0:
        return {"n": 0}
    p_higher = sum(1 for o in outcomes if o["target"]) / n
    p_stop_first = sum(1 for o in outcomes if o["stop"]) / n
    expectancy = sum(o["r"] for o in outcomes) / n
    recoveries = [bool(o.get("recovery")) for o in outcomes]
    gaps = [o["gap_hit"] for o in outcomes if o.get("gap_hit") is not None]
    recovers = [bool(o.get("recover")) for o in outcomes]
    ups = [e.trend_up for e in entries if e.trend_up is not None]
    trend_up = (sum(1 for u in ups if u) / len(ups)) if ups else None
    return {
        "n": n,
        "p_higher": p_higher,
        "p_stop_first": p_stop_first,
        "expectancy_r": expectancy,
        "trend_up": trend_up,
        "recovery": (sum(recoveries) / n) if recoveries else None,
        "gap_hit": (sum(1 for g in gaps if g) / len(gaps)) if gaps else None,
        "p_recover": (sum(recovers) / n) if recovers else None,
    }


# Tail of every series held back from discovery. A pattern measured on the same
# bars that suggested it will always look good; this is where it has to survive.
OOS_FRACTION = 0.30
# Below this a 30% tail holds too few bars for the confirmation to mean anything.
MIN_SPLIT_BARS = 150


def _pairs(bars: list[Any], query: StudyQuery) -> list[tuple[AnalogEntry, dict[str, Any]]]:
    """Entries kept alongside their outcome, so the two can be split together."""
    out: list[tuple[AnalogEntry, dict[str, Any]]] = []
    for e in find_entries(bars, query):
        o = _forward(bars, e, query.horizon)
        if o is not None:
            out.append((e, o))
    return out


def split_index(n_bars: int, *, oos_fraction: float = OOS_FRACTION) -> int:
    """First bar index belonging to the out-of-sample tail."""
    return int(n_bars * (1.0 - oos_fraction))


def split_pairs(
    pairs: list[tuple[AnalogEntry, dict[str, Any]]],
    cut: int,
    horizon: int,
) -> tuple[list[tuple[AnalogEntry, dict[str, Any]]], list[tuple[AnalogEntry, dict[str, Any]]]]:
    """Split into in-sample and out-of-sample around ``cut``.

    An entry at bar ``i`` is graded using bars up to ``i + horizon``, so entries
    within one horizon of the cut are dropped entirely. Without that embargo the
    in-sample side reads bars from the out-of-sample tail and the "confirmation"
    is measuring data it has already seen.
    """
    in_sample = [(e, o) for e, o in pairs if e.idx + horizon < cut]
    out_sample = [(e, o) for e, o in pairs if e.idx >= cut]
    return in_sample, out_sample


def analyze_series(bars: list[Any], query: StudyQuery) -> dict[str, Any]:
    """Aggregate analog metrics for a single bar series (``{'n': 0}`` when no entries).

    Carries an ``oos`` sub-aggregate over the held-out tail whenever the series
    is long enough to split.
    """
    pairs = _pairs(bars, query)
    entries = find_entries(bars, query)
    metrics = _aggregate(entries, [o for _, o in pairs])
    metrics["oos"] = None
    if len(bars) >= MIN_SPLIT_BARS:
        _, out_sample = split_pairs(pairs, split_index(len(bars)), query.horizon)
        if out_sample:
            metrics["oos"] = _aggregate([e for e, _ in out_sample], [o for _, o in out_sample])
    return metrics


def analyze_sessions(sessions: list[dict[str, Any]], query: StudyQuery) -> dict[str, Any]:
    """Aggregate analog metrics across intraday sessions (day-trade channel).

    The held-out tail is the most recent sessions. Sessions do not overlap, so
    unlike the daily series this split needs no embargo.
    """
    def _collect(subset: list[dict[str, Any]]) -> tuple[list[AnalogEntry], list[dict[str, Any]]]:
        entries: list[AnalogEntry] = []
        outcomes: list[dict[str, Any]] = []
        for s in subset:
            bars = s.get("bars") or []
            for e in find_entries(bars, query):
                o = _forward(bars, e, query.horizon)
                if o is not None:
                    entries.append(e)
                    outcomes.append(o)
        return entries, outcomes

    metrics = _aggregate(*_collect(sessions))
    metrics["oos"] = None
    cut = split_index(len(sessions))
    if cut > 0 and len(sessions) - cut > 0:
        oos_entries, oos_outcomes = _collect(sessions[cut:])
        if oos_outcomes:
            metrics["oos"] = _aggregate(oos_entries, oos_outcomes)
    return metrics


def run_universe(bars_by_ticker: dict[str, list[Any]], query: StudyQuery) -> list[StudyResult]:
    """Per-ticker results + an n-weighted universe aggregate (ticker='UNIVERSE')."""
    per: dict[str, dict[str, Any]] = {
        t: analyze_series(bars, query) for t, bars in bars_by_ticker.items() if bars
    }
    valid = [(t, m) for t, m in per.items() if m["n"] > 0]
    results: list[StudyResult] = []

    universe: StudyResult | None = None
    n_total = sum(m["n"] for _, m in valid)
    if n_total > 0:
        p_higher = sum(m["p_higher"] * m["n"] for _, m in valid) / n_total
        p_stop = sum(m["p_stop_first"] * m["n"] for _, m in valid) / n_total
        expectancy = sum(m["expectancy_r"] * m["n"] for _, m in valid) / n_total
        rec_n = sum(m["n"] for _, m in valid if m.get("recovery") is not None)
        gap_items = [(m["gap_hit"], m["n"]) for _, m in valid if m.get("gap_hit") is not None]
        gap_n = sum(n for _, n in gap_items)
        pr_n = sum(m["n"] for _, m in valid if m.get("p_recover") is not None)
        oos = [m["oos"] for _, m in valid if m.get("oos") and m["oos"]["n"] > 0]
        oos_n = sum(o["n"] for o in oos)
        oos_rec_n = sum(o["n"] for o in oos if o.get("recovery") is not None)
        oos_gap = [(o["gap_hit"], o["n"]) for o in oos if o.get("gap_hit") is not None]
        oos_gap_n = sum(n for _, n in oos_gap)
        oos_pr_n = sum(o["n"] for o in oos if o.get("p_recover") is not None)
        universe = StudyResult(
            query_id=query.id,
            label=query.label,
            channel=query.channel,
            fingerprint=query.fingerprint,
            ticker="UNIVERSE",
            n=n_total,
            p_higher=p_higher,
            p_stop_first=p_stop,
            expectancy_r=expectancy,
            recovery=(
                sum(m["recovery"] * m["n"] for _, m in valid if m.get("recovery") is not None)
                / rec_n
                if rec_n
                else None
            ),
            gap_hit=(
                sum(g * n for g, n in gap_items) / gap_n if gap_n else None
            ),
            p_recover=(
                sum(m["p_recover"] * m["n"] for _, m in valid if m.get("p_recover") is not None)
                / pr_n
                if pr_n
                else None
            ),
            oos_n=oos_n,
            oos_p_higher=(
                sum(o["p_higher"] * o["n"] for o in oos) / oos_n if oos_n else None
            ),
            oos_p_stop_first=(
                sum(o["p_stop_first"] * o["n"] for o in oos) / oos_n if oos_n else None
            ),
            oos_expectancy_r=(
                sum(o["expectancy_r"] * o["n"] for o in oos) / oos_n if oos_n else None
            ),
            oos_recovery=(
                sum(o["recovery"] * o["n"] for o in oos if o.get("recovery") is not None)
                / oos_rec_n
                if oos_rec_n
                else None
            ),
            oos_gap_hit=(
                sum(g * n for g, n in oos_gap) / oos_gap_n if oos_gap_n else None
            ),
            oos_p_recover=(
                sum(o["p_recover"] * o["n"] for o in oos if o.get("p_recover") is not None)
                / oos_pr_n
                if oos_pr_n
                else None
            ),
        )
        results.append(universe)

    for t, m in valid:
        vs = None
        if universe is not None and m["p_higher"] is not None and universe.p_higher is not None:
            vs = m["p_higher"] - universe.p_higher
        results.append(
            StudyResult(
                query_id=query.id,
                label=query.label,
                channel=query.channel,
                fingerprint=query.fingerprint,
                ticker=t,
                n=m["n"],
                p_higher=m["p_higher"],
                p_stop_first=m["p_stop_first"],
                expectancy_r=m["expectancy_r"],
                trend_up=m["trend_up"],
                vs_universe=vs,
                recovery=m.get("recovery"),
                gap_hit=m.get("gap_hit"),
                p_recover=m.get("p_recover"),
                oos_n=(m.get("oos") or {}).get("n", 0),
                oos_p_higher=(m.get("oos") or {}).get("p_higher"),
                oos_p_stop_first=(m.get("oos") or {}).get("p_stop_first"),
                oos_expectancy_r=(m.get("oos") or {}).get("expectancy_r"),
                oos_recovery=(m.get("oos") or {}).get("recovery"),
                oos_gap_hit=(m.get("oos") or {}).get("gap_hit"),
                oos_p_recover=(m.get("oos") or {}).get("p_recover"),
            )
        )
    return results


# Horizons the catalog never sweeps — declared in StudyQuery but unused until now.
DEEP_HORIZONS = (5, 10, 20, 40)


def sweep_horizons(
    bars_by_ticker: dict[str, list[Any]],
    queries: list[StudyQuery],
    *,
    horizons: tuple[int, ...] = DEEP_HORIZONS,
) -> list[dict[str, Any]]:
    """Re-run ``run_universe`` across horizons, exposing recovery / gap_hit.

    Each (query, horizon) pair is a distinct hypothesis. Callers must register
    them in ``trial_registry`` *before* looking at the numbers.
    """
    findings: list[dict[str, Any]] = []
    for query in queries:
        for horizon in horizons:
            q = query.model_copy(update={"horizon": int(horizon), "id": f"{query.id}:h{horizon}"})
            results = run_universe(bars_by_ticker, q)
            uni = next((r for r in results if r.ticker == "UNIVERSE"), None)
            if uni is None or uni.n == 0:
                continue
            findings.append(
                {
                    "query_id": query.id,
                    "fingerprint": query.fingerprint,
                    "horizon": int(horizon),
                    "n": uni.n,
                    "p_higher": uni.p_higher,
                    "p_stop_first": uni.p_stop_first,
                    "recovery": uni.recovery,
                    "gap_hit": uni.gap_hit,
                    "p_recover": uni.p_recover,
                    "oos_n": uni.oos_n,
                    "oos_p_higher": uni.oos_p_higher,
                    "oos_recovery": uni.oos_recovery,
                    "oos_gap_hit": uni.oos_gap_hit,
                    "oos_p_recover": uni.oos_p_recover,
                }
            )
    return findings


__all__ = [
    "AnalogEntry",
    "OOS_FRACTION",
    "MIN_SPLIT_BARS",
    "DEEP_HORIZONS",
    "analyze_series",
    "analyze_sessions",
    "find_entries",
    "run_universe",
    "sweep_horizons",
    "split_index",
    "split_pairs",
]
