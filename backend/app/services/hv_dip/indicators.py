"""High-Vol Dip indicators (reuse ATR helpers from swing)."""

from __future__ import annotations

from app.services.brapi_client import Bar
from app.services.swing.indicators import (
    atr,
    atr_pct,
    higher_lows_recent,
    sma,
    volume_vs_sma,
)

LOOKBACK_DEFAULT = 10


def recent_high(daily: list[Bar], lookback: int = LOOKBACK_DEFAULT) -> float | None:
    if len(daily) < lookback:
        return None
    window = daily[-lookback:]
    return max(b.high for b in window)


def recent_low(daily: list[Bar], lookback: int = LOOKBACK_DEFAULT) -> float | None:
    if len(daily) < lookback:
        return None
    window = daily[-lookback:]
    return min(b.low for b in window)


def dip_pct_from_high(daily: list[Bar], lookback: int = LOOKBACK_DEFAULT) -> float | None:
    hi = recent_high(daily, lookback)
    if hi is None or hi <= 0 or not daily:
        return None
    close = float(daily[-1].close)
    return (hi - close) / hi * 100.0


def days_since_recent_high(daily: list[Bar], lookback: int = LOOKBACK_DEFAULT) -> int | None:
    """Trading days since the most recent high within the lookback window.

    0 = the high is the last bar (fresh top); lookback-1 = the high is the oldest
    bar in the window (mature decline). Used to gauge decline maturity, so a
    long-standing dip that is turning up gets more patience than a fresh fall.
    """
    if len(daily) < lookback:
        return None
    window = daily[-lookback:]
    hi = max(b.high for b in window)
    last_idx = 0
    for i, b in enumerate(window):
        if b.high >= hi:
            last_idx = i
    return len(window) - 1 - last_idx


def is_52w_low(daily: list[Bar], *, tol: float = 0.002) -> bool:
    """True if last close is at/near the lowest low in available history (~52w if enough bars)."""
    if len(daily) < 60:
        return False
    window = daily[-252:] if len(daily) >= 252 else daily
    low = min(b.low for b in window)
    close = float(daily[-1].close)
    return close <= low * (1.0 + tol)


def weekly_range_pct(daily: list[Bar]) -> float | None:
    """Approx weekly range from last 5 sessions."""
    if len(daily) < 5:
        return None
    window = daily[-5:]
    hi = max(b.high for b in window)
    lo = min(b.low for b in window)
    mid = (hi + lo) / 2.0
    if mid <= 0:
        return None
    return (hi - lo) / mid * 100.0


def _oscillation_events(
    daily: list[Bar], *, window: int, swing_pct: float, recovery_pct: float | None = None
) -> tuple[int, int] | None:
    """Count (dips, recovered) oscillation events within the last `window` bars.

    A "dip" is a local peak -> local trough drawdown of at least `swing_pct`.
    A dip counts as "recovered" if price subsequently retraces at least
    `recovery_pct` (default 50%) of the dip range. This is the backbone for
    mean-reversion scoring: a name that repeatedly dips and recovers is a
    strong "buy the dip" candidate, whereas one that only grinds down is not.
    """
    if len(daily) < window:
        return None
    bars = daily[-window:]
    recovery_pct = recovery_pct if recovery_pct is not None else 50.0

    dips = 0
    recovered = 0
    i = 0
    n = len(bars)
    while i < n - 1:
        peak_idx = i
        while peak_idx + 1 < n and bars[peak_idx + 1].high > bars[peak_idx].high:
            peak_idx += 1
        peak = bars[peak_idx].high

        trough_idx = peak_idx
        while trough_idx + 1 < n and bars[trough_idx + 1].low < bars[trough_idx].low:
            trough_idx += 1
        trough = bars[trough_idx].low

        if trough_idx > peak_idx and peak > 0:
            dip = (peak - trough) / peak * 100.0
            if dip >= swing_pct:
                dips += 1
                need = trough + (peak - trough) * recovery_pct / 100.0
                for k in range(trough_idx + 1, n):
                    if bars[k].high >= need:
                        recovered += 1
                        break
        i = trough_idx + 1
    return dips, recovered


def recovery_rate(
    daily: list[Bar], *, window: int, swing_pct: float, recovery_pct: float | None = None
) -> float | None:
    """Fraction of historical dips (>= swing_pct) that recovered within `window`.

    None means there is not enough history or no qualifying dips to measure.
    """
    events = _oscillation_events(
        daily, window=window, swing_pct=swing_pct, recovery_pct=recovery_pct
    )
    if events is None or events[0] == 0:
        return None
    dips, recovered = events
    return recovered / dips


def round_trips(daily: list[Bar], *, window: int, swing_pct: float) -> int | None:
    """Number of complete oscillation cycles (dips that fully recovered)."""
    events = _oscillation_events(
        daily, window=window, swing_pct=swing_pct, recovery_pct=50.0
    )
    if events is None:
        return None
    return events[1]


def is_fresh_high(daily: list[Bar], *, window: int, recent_lookback: int) -> bool | None:
    """True if the recent `recent_lookback` bars set a new high vs the prior `window`."""
    if len(daily) < window:
        return None
    window_bars = daily[-window:]
    if len(window_bars) < recent_lookback + 1:
        return None
    prior = window_bars[: -recent_lookback]
    if not prior:
        return None
    prior_high = max(b.high for b in prior)
    recent_high_val = max(b.high for b in window_bars[-recent_lookback:])
    return recent_high_val > prior_high


def quality_tier(
    dollar_volume: float | None = None,
    price: float | None = None,
    *,
    min_dollar_volume: float,
    mega_dollar_volume: float,
) -> str:
    """Classify liquidity/quality: 'micro' (reject), 'mid' (unknown/neutral),
    'large' or 'mega'.

    A sub-$5 name is only treated as a penny stock when it is ALSO illiquid
    (below min_dollar_volume). A liquid large-cap that happens to trade below
    $5 (e.g. a deep-dip EV/growth name like LCID) is a legitimate "buy the dip"
    candidate, not a micro-cap — its dollar volume proves it is liquid enough.
    """
    p = float(price) if price is not None else None
    dv = float(dollar_volume) if dollar_volume is not None else None
    if p is not None and p < 5.0 and (dv is None or dv < min_dollar_volume):
        return "micro"
    if dv is None:
        return "mid"
    if dv >= mega_dollar_volume:
        return "mega"
    if dv >= min_dollar_volume:
        return "large"
    return "micro"


def recovery_in_progress(
    daily: list[Bar], *, min_rebound_pct: float = 5.0, lookback: int = 15
) -> bool:
    """Detect an early turnaround: price rebounded >= min_rebound_pct off a recent
    bottom AND recent lows are higher than the prior trough (base structure)."""
    if len(daily) < lookback + 2:
        return False
    window = daily[-lookback:]
    bottom = min(b.low for b in window)
    if bottom <= 0:
        return False
    last_close = float(daily[-1].close)
    rebound = (last_close - bottom) / bottom * 100.0
    if rebound < min_rebound_pct:
        return False
    return higher_lows_recent(daily)


__all__ = [
    "LOOKBACK_DEFAULT",
    "atr",
    "atr_pct",
    "sma",
    "volume_vs_sma",
    "recent_high",
    "recent_low",
    "dip_pct_from_high",
    "days_since_recent_high",
    "is_52w_low",
    "weekly_range_pct",
    "recovery_rate",
    "round_trips",
    "is_fresh_high",
    "quality_tier",
    "recovery_in_progress",
]
