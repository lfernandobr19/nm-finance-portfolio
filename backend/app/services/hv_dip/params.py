"""Typed parameter bounds + defaults for hv_dip learn loop.

The optimizer searches the *entry-threshold* params that are evaluable against
closed-trade evidence (dip depth, recovery-rate minimum, fresh-high rejection).
Scoring-only knobs (quality bonus, oscillation window/swing) are carried through
the versioned config but are not grid-searched (they require bar re-simulation,
which is out of scope for the evidence we persist). Bounds are the
anti-overfitting contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product


@dataclass(frozen=True)
class ParamSpec:
    name: str
    low: float
    high: float
    default: float
    step: float = 0.1
    kind: str = "float"  # "float" | "int" | "bool"


TUNABLE_SPECS: tuple[ParamSpec, ...] = (
    ParamSpec("dip_pct", 6.0, 12.0, 8.0, 1.0, "float"),
    ParamSpec("min_recovery_rate", 0.5, 0.7, 0.6, 0.05, "float"),
    ParamSpec("reject_fresh_high", 0.0, 1.0, 1.0, 1.0, "bool"),
)

# Scoring-only knobs (versioned but not grid-searched).
FIXED_DEFAULTS: dict[str, float] = {
    "quality_bonus": 5.0,
    "osc_swing_pct": 8.0,
    "osc_window": 84.0,
}

FIXED_KINDS: dict[str, str] = {
    "quality_bonus": "float",
    "osc_swing_pct": "float",
    "osc_window": "int",
}


def default_params() -> dict[str, float]:
    out: dict[str, float] = {}
    for s in TUNABLE_SPECS:
        out[s.name] = s.default
    out.update(FIXED_DEFAULTS)
    return out


def _coerce(spec_name: str, raw: float, spec: ParamSpec | None) -> float:
    if spec is None:
        kind = FIXED_KINDS.get(spec_name, "float")
        if kind == "int":
            return float(round(raw))
        return float(raw)
    v = float(raw)
    v = min(max(v, spec.low), spec.high)
    if spec.kind == "int":
        return float(round(v))
    if spec.kind == "bool":
        return 1.0 if v >= 0.5 else 0.0
    return v


_SPEC_MAP = {s.name: s for s in TUNABLE_SPECS}


def clamp_params(params: dict[str, float] | None) -> dict[str, float]:
    """Clamp to bounds and fill missing with defaults (never trust caller input)."""
    out: dict[str, float] = {}
    for s in TUNABLE_SPECS:
        raw = (params or {}).get(s.name, s.default)
        try:
            raw = float(raw)
        except (TypeError, ValueError):
            raw = s.default
        out[s.name] = _coerce(s.name, raw, s)
    for name, default in FIXED_DEFAULTS.items():
        raw = (params or {}).get(name, default)
        try:
            raw = float(raw)
        except (TypeError, ValueError):
            raw = default
        out[name] = _coerce(name, raw, None)
    return out


def grid_combos(max_combos: int = 64) -> list[dict[str, float]]:
    """Discrete grid over the tunable entry thresholds, capped to avoid blow-up."""
    axes: list[list[float]] = []
    for s in TUNABLE_SPECS:
        values: list[float] = []
        v = s.low
        while v <= s.high + 1e-9:
            values.append(_coerce(s.name, v, s))
            v += s.step
        axes.append(values)

    combos: list[dict[str, float]] = []
    for combo in product(*axes):
        if len(combos) >= max_combos:
            break
        params = {TUNABLE_SPECS[i].name: combo[i] for i in range(len(TUNABLE_SPECS))}
        params.update(FIXED_DEFAULTS)
        combos.append(params)
    return combos


__all__ = [
    "ParamSpec",
    "TUNABLE_SPECS",
    "FIXED_DEFAULTS",
    "default_params",
    "clamp_params",
    "grid_combos",
]
