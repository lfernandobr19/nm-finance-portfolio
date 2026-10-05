"""Opening range breakout (first N×5m candles), parametrized."""

from __future__ import annotations

from typing import Any

from app.services.day_trade.bars import IntradayBar
from app.services.day_trade.rules.signal import RuleSignal


def evaluate_opening_range_break(
    bars: list[IntradayBar],
    params: dict[str, Any] | None = None,
) -> RuleSignal | None:
    p = params or {}
    opening_bars = int(p.get("opening_bars", 3))
    volume_mult = float(p.get("volume_mult", 1.0))
    risk_mult = float(p.get("risk_mult", 1.0))
    reward_mult = float(p.get("reward_mult", 1.0))

    if len(bars) < opening_bars + 1:
        return None
    opening = bars[:opening_bars]
    current = bars[-1]
    range_high = max(b.high for b in opening)
    range_low = min(b.low for b in opening)
    avg_vol = sum(b.volume for b in opening) / float(opening_bars)
    if avg_vol <= 0 or current.volume <= avg_vol * volume_mult:
        return None
    risk = max(range_high - range_low, 0.01) * risk_mult

    def metrics() -> dict[str, Any]:
        return {
            "range_high": round(range_high, 4),
            "range_low": round(range_low, 4),
            "avg_opening_volume": round(avg_vol, 0),
            "bar_volume": round(current.volume, 0),
            "opening_bars": opening_bars,
            "volume_mult": volume_mult,
        }

    if current.close > range_high and current.close > current.open:
        entry = current.close
        stop = range_low
        target = entry + risk * reward_mult
        return RuleSignal(
            rule_id="opening_range_break",
            side="long",
            entry_price=round(entry, 4),
            stop_price=round(stop, 4),
            target_price=round(target, 4),
            metrics=metrics(),
        )
    if current.close < range_low and current.close < current.open:
        entry = current.close
        stop = range_high
        target = entry - risk * reward_mult
        return RuleSignal(
            rule_id="opening_range_break",
            side="short",
            entry_price=round(entry, 4),
            stop_price=round(stop, 4),
            target_price=round(target, 4),
            metrics=metrics(),
        )
    return None


__all__ = ["evaluate_opening_range_break"]
