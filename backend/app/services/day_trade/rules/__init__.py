"""Rule registry for day trade study (parametrized)."""

from __future__ import annotations

from typing import Any, Callable

from app.services.day_trade.bars import IntradayBar
from app.services.day_trade.rules.opening_range_break import evaluate_opening_range_break
from app.services.day_trade.rules.signal import RuleSignal
from app.services.day_trade.rules.vwap_reclaim import evaluate_vwap_reclaim

_RULE_FNS: dict[str, Callable] = {
    "opening_range_break": evaluate_opening_range_break,
    "vwap_reclaim": evaluate_vwap_reclaim,
}


def build_evaluators(
    params: dict[str, dict[str, Any]] | None,
) -> list[Callable[[list[IntradayBar]], RuleSignal | None]]:
    """Return evaluators bound to the given params (one callable per rule)."""
    out: list[Callable[[list[IntradayBar]], RuleSignal | None]] = []
    for rule_id, fn in _RULE_FNS.items():
        rule_params = (params or {}).get(rule_id)

        def evaluator(bars: list[IntradayBar], _fn=fn, _rp=rule_params) -> RuleSignal | None:
            return _fn(bars, _rp)

        evaluator.rule_id = rule_id  # type: ignore[attr-defined]
        out.append(evaluator)
    return out


# Legacy default (no params -> each rule uses its own defaults).
RULE_EVALUATORS: list[Callable[[list[IntradayBar]], RuleSignal | None]] = build_evaluators(None)

__all__ = ["RULE_EVALUATORS", "RuleSignal", "build_evaluators"]
