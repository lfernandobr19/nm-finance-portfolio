"""VWAP reclaim with confirmation candle, parametrized + volatility/regime gates."""

from __future__ import annotations

from typing import Any

from app.services.day_trade.bars import IntradayBar
from app.services.day_trade.indicators import atr_pct, session_vwap, vwap_slope_normalized
from app.services.day_trade.rules.signal import RuleSignal


def evaluate_vwap_reclaim(
    bars: list[IntradayBar],
    params: dict[str, Any] | None = None,
) -> RuleSignal | None:
    p = params or {}
    risk_mult = float(p.get("risk_mult", 1.0))
    reward_mult = float(p.get("reward_mult", 2.0))
    min_atr_pct = float(p.get("min_atr_pct", 0.0))
    slope_gate = float(p.get("vwap_slope_gate", 0.0))

    if len(bars) < 3:
        return None

    # Volatility floor: skip dead/quiet names (ATR% below threshold).
    if min_atr_pct > 0:
        atrp = atr_pct(bars, 14)
        if atrp is None or atrp < min_atr_pct:
            return None

    # Directional gate: require |normalized VWAP slope| above threshold to avoid
    # fading a flat/balanced session. slope_gate == 0 disables (default).
    if slope_gate > 0:
        slope = vwap_slope_normalized(bars, 10)
        if slope is None or abs(slope) < slope_gate:
            return None

    prev = bars[-2]
    current = bars[-1]
    vwap = session_vwap(bars[:-1])
    prev_below = prev.close < vwap
    prev_above = prev.close > vwap
    curr_above = current.close > vwap and current.close > current.open
    curr_below = current.close < vwap and current.close < current.open
    risk = max(abs(current.close - vwap), 0.05) * risk_mult
    metrics = {"vwap": round(vwap, 4), "confirm_close": round(current.close, 4)}
    if prev_below and curr_above:
        entry = current.close
        stop = entry - risk
        target = entry + risk * reward_mult
        return RuleSignal(
            rule_id="vwap_reclaim",
            side="long",
            entry_price=round(entry, 4),
            stop_price=round(stop, 4),
            target_price=round(target, 4),
            metrics=metrics,
        )
    if prev_above and curr_below:
        entry = current.close
        stop = entry + risk
        target = entry - risk * reward_mult
        return RuleSignal(
            rule_id="vwap_reclaim",
            side="short",
            entry_price=round(entry, 4),
            stop_price=round(stop, 4),
            target_price=round(target, 4),
            metrics=metrics,
        )
    return None


__all__ = ["evaluate_vwap_reclaim"]
