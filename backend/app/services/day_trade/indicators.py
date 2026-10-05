"""Intraday indicators for day trade rules / regime / learning.

Operates on `IntradayBar` (session-scoped, valid bars only). Kept dependency-free
so rules, the regime filter, and the offline optimizer share identical math.
"""

from __future__ import annotations

from app.services.day_trade.bars import IntradayBar


def session_vwap(bars: list[IntradayBar]) -> float:
    """Session-anchored VWAP (typical price = (H+L+C)/3)."""
    if not bars:
        return 0.0
    num = 0.0
    den = 0.0
    for b in bars:
        typical = (b.high + b.low + b.close) / 3.0
        vol = max(b.volume, 0.0)
        num += typical * vol
        den += vol
    if den <= 0:
        return bars[-1].close
    return num / den


def true_range(bar: IntradayBar, prev: IntradayBar) -> float:
    return max(
        bar.high - bar.low,
        abs(bar.high - prev.close),
        abs(bar.low - prev.close),
    )


def atr(bars: list[IntradayBar], period: int = 14) -> float | None:
    if len(bars) < period + 1:
        return None
    trs = [true_range(bars[i], bars[i - 1]) for i in range(1, len(bars))]
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period


def atr_pct(bars: list[IntradayBar], period: int = 14) -> float | None:
    a = atr(bars, period)
    if a is None or not bars or bars[-1].close <= 0:
        return None
    return (a / bars[-1].close) * 100.0


def vwap_slope_normalized(bars: list[IntradayBar], lookback: int = 10) -> float | None:
    """Slope of session VWAP over `lookback` bars, normalized by ATR.

    ~0 -> balanced/range; larger |value| -> directional. Normalizing by ATR makes
    the gate comparable across tickers and volatility regimes.
    """
    if len(bars) < lookback + 1:
        return None
    window = bars[-lookback:]
    # Approximate VWAP trajectory by cumulative VWAP ending at each bar.
    vwaps: list[float] = []
    for i in range(1, len(window) + 1):
        vwaps.append(session_vwap(window[:i]))
    if len(vwaps) < 2:
        return None
    # Least-squares slope of the VWAP trajectory (normalized by bar index).
    n = len(vwaps)
    x_mean = (n - 1) / 2.0
    y_mean = sum(vwaps) / n
    num = sum((i - x_mean) * (vwaps[i] - y_mean) for i in range(n))
    den = sum((i - x_mean) ** 2 for i in range(n))
    slope = num / den if den else 0.0
    a = atr(bars, 14)
    if a is None or a <= 0:
        return None
    return slope / a


__all__ = ["session_vwap", "atr", "atr_pct", "true_range", "vwap_slope_normalized"]
