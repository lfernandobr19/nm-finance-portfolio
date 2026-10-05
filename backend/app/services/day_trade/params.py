"""Typed parameter bounds + defaults for day trade rules.

The optimizer searches only inside these bounds; the live observer clamps any
incoming params to the same bounds. Bounds are the anti-overfitting contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

RULE_ORB = "opening_range_break"
RULE_VWAP = "vwap_reclaim"
RULE_IDS = (RULE_ORB, RULE_VWAP)


@dataclass(frozen=True)
class ParamSpec:
    name: str
    low: float
    high: float
    default: float
    step: float = 0.1
    kind: str = "float"  # "float" | "int"


ORB_SPECS: tuple[ParamSpec, ...] = (
    ParamSpec("opening_bars", 2, 6, 3, 1.0, "int"),
    ParamSpec("volume_mult", 0.5, 2.5, 1.0, 0.1, "float"),
    ParamSpec("risk_mult", 0.5, 2.0, 1.0, 0.1, "float"),
    ParamSpec("reward_mult", 0.5, 3.0, 1.0, 0.1, "float"),
)

VWAP_SPECS: tuple[ParamSpec, ...] = (
    ParamSpec("risk_mult", 0.5, 2.0, 1.0, 0.1, "float"),
    ParamSpec("reward_mult", 1.0, 3.0, 2.0, 0.1, "float"),
    ParamSpec("min_atr_pct", 0.0, 5.0, 0.0, 0.1, "float"),
    ParamSpec("vwap_slope_gate", 0.0, 0.05, 0.0, 0.005, "float"),
)

RULE_SPECS: dict[str, tuple[ParamSpec, ...]] = {
    RULE_ORB: ORB_SPECS,
    RULE_VWAP: VWAP_SPECS,
}


def default_params() -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for rule_id, specs in RULE_SPECS.items():
        out[rule_id] = {s.name: s.default for s in specs}
    return out


def clamp_params(params: dict[str, dict[str, float]] | None) -> dict[str, dict[str, float]]:
    """Clamp to bounds and fill missing with defaults (never trust caller input)."""
    out: dict[str, dict[str, float]] = {}
    for rule_id, specs in RULE_SPECS.items():
        given = (params or {}).get(rule_id, {})
        clean: dict[str, float] = {}
        for s in specs:
            raw = given.get(s.name, s.default)
            try:
                v = float(raw)
            except (TypeError, ValueError):
                v = s.default
            v = min(max(v, s.low), s.high)
            if s.kind == "int":
                v = float(round(v))
            clean[s.name] = v
        out[rule_id] = clean
    return out


def grid_combos(rule_id: str, max_combos: int = 120) -> list[dict[str, float]]:
    """Discrete grid within bounds (cartesian), capped to avoid combinatorial blow-up."""
    specs = RULE_SPECS.get(rule_id)
    if not specs:
        return []
    axes: list[list[float]] = []
    for s in specs:
        values: list[float] = []
        v = s.low
        while v <= s.high + 1e-9:
            values.append(round(v, 6) if s.kind == "float" else float(round(v)))
            if s.kind == "int":
                v += 1.0
            else:
                v += s.step
        axes.append(values)
    combos: list[dict[str, float]] = []
    from itertools import product

    for combo in product(*axes):
        if len(combos) >= max_combos:
            break
        combos.append({s.name: combo[i] for i, s in enumerate(specs)})
    return combos


__all__ = [
    "RULE_ORB",
    "RULE_VWAP",
    "RULE_IDS",
    "RULE_SPECS",
    "ParamSpec",
    "default_params",
    "clamp_params",
    "grid_combos",
]
