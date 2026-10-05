"""Session regime classification (trend vs chop) for day trade gating.

Blocks mean-reversion rules (e.g. VWAP reclaim) in balanced/choppy sessions using
a volatility-normalized VWAP slope with hysteresis, so the state does not flicker
on every bar.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings
from app.services.day_trade.bars import IntradayBar
from app.services.day_trade.indicators import vwap_slope_normalized


@dataclass(frozen=True)
class RegimeState:
    regime: str  # "trend" | "chop" | "warmup"
    slope: float | None


def classify_regime(
    bars: list[IntradayBar],
    *,
    hysteresis: int | None = None,
    threshold: float | None = None,
    lookback: int | None = None,
) -> RegimeState:
    settings = get_settings()
    hysteresis = hysteresis or int(settings.day_trade_regime_hysteresis_bars)
    threshold = threshold or float(settings.day_trade_regime_slope_threshold)
    lookback = lookback or int(settings.day_trade_regime_lookback)

    need = lookback + hysteresis + 1
    if len(bars) < need:
        return RegimeState("warmup", None)

    slopes: list[float | None] = []
    for i in range(len(bars) - hysteresis, len(bars) + 1):
        slopes.append(vwap_slope_normalized(bars[: i + 1], lookback))
    if any(s is None for s in slopes):
        return RegimeState("warmup", None)

    cur = vwap_slope_normalized(bars, lookback)
    if all(s > threshold for s in slopes) or all(s < -threshold for s in slopes):
        return RegimeState("trend", cur)
    return RegimeState("chop", cur)


def is_trending(bars: list[IntradayBar]) -> bool:
    return classify_regime(bars).regime == "trend"


__all__ = ["RegimeState", "classify_regime", "is_trending"]
