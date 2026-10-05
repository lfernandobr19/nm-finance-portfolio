"""OHLC helpers: weekly derive, SMA, ATR, volume, recent breakout + trend context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.services.brapi_client import Bar

# Entry uses recent highs (~2 weeks). Longer history is only regime context.
BREAKOUT_LOOKBACK = 10
SWING_LOW_LOOKBACK = 10
WEEKLY_SMA_PERIOD = 10
WEEKLY_SLOPE_LAG = 3  # weeks: SMA must be rising vs this lag
RANGE_LOOKBACK_DAYS = 60  # ~3mo free window used as regime context
MIN_RANGE_PERCENTILE = 0.45  # reject longs stuck in the lower half of the range


@dataclass
class WeeklyBar:
    week_end: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


def derive_weekly(daily: list[Bar]) -> list[WeeklyBar]:
    """Aggregate daily bars into ISO-week bars (week ends on last session of the week)."""
    if not daily:
        return []
    buckets: dict[tuple[int, int], list[Bar]] = {}
    for b in daily:
        iso = b.date.isocalendar()
        key = (iso.year, iso.week)
        buckets.setdefault(key, []).append(b)
    weeks: list[WeeklyBar] = []
    for key in sorted(buckets):
        rows = sorted(buckets[key], key=lambda x: x.date)
        weeks.append(
            WeeklyBar(
                week_end=rows[-1].date,
                open=rows[0].open,
                high=max(r.high for r in rows),
                low=min(r.low for r in rows),
                close=rows[-1].close,
                volume=sum(r.volume for r in rows),
            )
        )
    return weeks


def sma(values: list[float], period: int) -> float | None:
    if len(values) < period or period <= 0:
        return None
    window = values[-period:]
    return sum(window) / period


def atr(daily: list[Bar], period: int = 14) -> float | None:
    if len(daily) < period + 1:
        return None
    trs: list[float] = []
    for i in range(1, len(daily)):
        cur, prev = daily[i], daily[i - 1]
        tr = max(
            cur.high - cur.low,
            abs(cur.high - prev.close),
            abs(cur.low - prev.close),
        )
        trs.append(tr)
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period


def atr_pct(daily: list[Bar], period: int = 14) -> float | None:
    a = atr(daily, period)
    if a is None or not daily or daily[-1].close <= 0:
        return None
    return (a / daily[-1].close) * 100.0


def volume_vs_sma(daily: list[Bar], period: int = 20) -> float | None:
    if len(daily) < period:
        return None
    vols = [b.volume for b in daily]
    avg = sma(vols, period)
    if avg is None or avg <= 0:
        return None
    return daily[-1].volume / avg


def weekly_sma_slope_up(
    weekly: list[WeeklyBar],
    sma_period: int = WEEKLY_SMA_PERIOD,
    lag: int = WEEKLY_SLOPE_LAG,
) -> bool:
    """True when weekly SMA is rising (trend improving), not merely crossed by a bounce."""
    closes = [w.close for w in weekly]
    need = sma_period + lag
    if len(closes) < need:
        return False
    ma_now = sma(closes, sma_period)
    ma_prev = sma(closes[:-lag], sma_period)
    if ma_now is None or ma_prev is None:
        return False
    return ma_now > ma_prev


def weekly_trend_bullish(
    weekly: list[WeeklyBar],
    sma_period: int = WEEKLY_SMA_PERIOD,
) -> bool:
    """
    Weekly favor = price above SMA **and** SMA sloping up.

    With only ~3 months of free OHLC, SMA10 alone is almost the whole series mean;
    a dead-cat bounce can cross it while the average is still falling. Requiring a
    rising SMA avoids treating late-downtrend rebounds as new uptrends.
    """
    closes = [w.close for w in weekly]
    ma = sma(closes, sma_period)
    if ma is None:
        return False
    if weekly[-1].close <= ma:
        return False
    return weekly_sma_slope_up(weekly, sma_period=sma_period)


def daily_breakout_long(
    daily: list[Bar],
    lookback: int = BREAKOUT_LOOKBACK,
) -> tuple[bool, float | None]:
    """Close breaks above **recent** prior highs (excluding today). Default 10 sessions."""
    if len(daily) < lookback + 1:
        return False, None
    prior = daily[-(lookback + 1) : -1]
    level = max(b.high for b in prior)
    last = daily[-1]
    return last.close > level, level


def recent_swing_low(daily: list[Bar], lookback: int = SWING_LOW_LOOKBACK) -> float | None:
    """Lowest low over the recent window (excluding today) — for tighter technical stops."""
    if len(daily) < lookback + 1:
        return None
    prior = daily[-(lookback + 1) : -1]
    return min(b.low for b in prior)


def range_position(daily: list[Bar], lookback: int = RANGE_LOOKBACK_DAYS) -> float | None:
    """
    Where is the last close inside the high-low range of the lookback window?
    0 = at the low, 1 = at the high. Used as regime context (not as entry trigger).
    """
    if len(daily) < max(20, lookback // 2):
        return None
    window = daily[-lookback:] if len(daily) >= lookback else daily
    hi = max(b.high for b in window)
    lo = min(b.low for b in window)
    if hi <= lo:
        return None
    close = daily[-1].close
    return (close - lo) / (hi - lo)


def higher_lows_recent(daily: list[Bar], recent: int = 15, prior: int = 25) -> bool:
    """Recent trough above the prior trough — structure improving vs older decline."""
    need = recent + prior + 1
    if len(daily) < need:
        return False
    body = daily[:-1]
    recent_low = min(b.low for b in body[-recent:])
    prior_low = min(b.low for b in body[-(recent + prior) : -recent])
    return recent_low > prior_low


def trend_context_allows_long(daily: list[Bar], weekly: list[WeeklyBar]) -> tuple[bool, str]:
    """
    Older price action as context: is a long still fighting a 3-month dump?

    Pass if either:
    - price sits in the upper half of the available range (continuation zone), or
    - recent lows are higher than the prior trough (base / recovery structure).
    """
    _ = weekly  # reserved for richer weekly structure checks later
    pos = range_position(daily)
    if pos is None:
        return False, "histórico insuficiente para contexto de faixa"
    if pos >= MIN_RANGE_PERCENTILE:
        return True, f"preço em {pos:.0%} da faixa ~3mes (contexto OK)"
    if higher_lows_recent(daily):
        return True, "mínimas recentes acima da mínima anterior (estrutura melhorando)"
    return (
        False,
        f"preço em {pos:.0%} da faixa ~3mes — rebound em tendência de baixa, sem estrutura",
    )


def last_closed_hourly(bars: list[Bar], *, now: datetime | None = None) -> Bar | None:
    """Drop the in-progress hour (bar start + 1h still in the future)."""
    if not bars:
        return None
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    closed = [b for b in bars if b.date + timedelta(hours=1) <= now]
    return closed[-1] if closed else None


def hourly_confirms_breakout(
    bar: Bar | None,
    *,
    breakout_level: float,
    stop: float,
) -> bool:
    if bar is None:
        return False
    return float(bar.close) >= float(breakout_level) and float(bar.low) >= float(stop)


def hourly_confirmation_status(
    bars: list[Bar] | None,
    *,
    breakout_level: float,
    stop: float,
    now: datetime | None = None,
) -> str:
    """h1_ok | h1_fail | h1_skip (no bars / no closed bar → fail-open)."""
    if not bars:
        return "h1_skip"
    closed = last_closed_hourly(bars, now=now)
    if closed is None:
        return "h1_skip"
    if hourly_confirms_breakout(closed, breakout_level=breakout_level, stop=stop):
        return "h1_ok"
    return "h1_fail"
