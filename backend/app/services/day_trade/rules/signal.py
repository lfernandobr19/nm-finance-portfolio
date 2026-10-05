"""Shared RuleSignal dataclass for day trade rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RuleSignal:
    rule_id: str
    side: str
    entry_price: float
    stop_price: float
    target_price: float
    metrics: dict[str, Any]


__all__ = ["RuleSignal"]
