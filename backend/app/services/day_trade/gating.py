"""Rule/ticker gating from live closed-signal performance.

Suppresses signals from rules or tickers whose realized expectancy is negative
once a minimum sample size is reached. Re-evaluated from the DB each call (cheap
at paper scale, and always reflects the latest closed signals).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.day_trade.analytics import _r_multiple, closed_signals

logger = logging.getLogger("fiidesk.day_trade.gating")


def compute_gates(db: Session, account_id: str | None = None) -> dict[str, set[str]]:
    """Expectancy gate from the whole simulated lab.

    The observer writes the same bars onto every USD account, so a per-account
    filter never reaches ``min_n`` even when the rule is already refuted.
    ``account_id`` stays on the signature for the observer call site.
    """
    settings = get_settings()
    min_n = int(settings.day_trade_gate_min_n or 10)
    rows = closed_signals(db)

    by_rule: dict[str, list[float]] = {}
    by_ticker: dict[str, list[float]] = {}
    for s in rows:
        r = _r_multiple(s)
        if r is None:
            continue
        by_rule.setdefault(s.rule_id, []).append(r)
        by_ticker.setdefault(s.ticker, []).append(r)

    disabled_rules = {
        k for k, v in by_rule.items() if len(v) >= min_n and sum(v) <= 0
    }
    disabled_tickers = {
        k for k, v in by_ticker.items() if len(v) >= min_n and sum(v) <= 0
    }
    return {"rules": disabled_rules, "tickers": disabled_tickers}


def rule_is_gated(gates: dict[str, set[str]], rule_id: str) -> bool:
    return rule_id in gates.get("rules", set())


def ticker_is_gated(gates: dict[str, set[str]], ticker: str) -> bool:
    return ticker.upper() in gates.get("tickers", set())


__all__ = ["compute_gates", "rule_is_gated", "ticker_is_gated"]
