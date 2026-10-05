"""Initial static catalog of StudyQuery questions (frequency/common/ticker/chance/trend/gap).

The catalog is a seed, not a closed list: the 7B proposes new queries via
``propose.py`` each night (capped), and any valid proposal is added to the
session's catalog.
"""

from __future__ import annotations

from app.services.studies.models import StudyQuery

CATALOG: list[StudyQuery] = [
    StudyQuery(
        id="hv_dip_deep_dip",
        label="Dip profundo costuma valorizar de novo em ~2 semanas?",
        channel="hv_dip",
        fingerprint="deep_dip",
        horizon=10,
        metric="p_recover",
        target_r=2.0,
        params={"min_dip_pct": 15.0, "stop_pct": 8.0, "lookback": 10},
    ),
    StudyQuery(
        id="swing_breakout_h1",
        label="Breakout com tendência semanal persegue o alvo?",
        channel="swing",
        fingerprint="breakout_h1",
        horizon=15,
        metric="p_higher",
        target_r=2.0,
        params={"lookback": 10},
    ),
    StudyQuery(
        id="daytrade_orb",
        label="Opening-range breakout persegue o alvo nas sessões?",
        channel="day_trade",
        fingerprint="orb",
        horizon=12,
        metric="p_higher",
        target_r=2.0,
        params={"orb_minutes": 15, "bar_minutes": 5},
    ),
    StudyQuery(
        id="daytrade_vwap",
        label="Recuperação do VWAP persegue o alvo?",
        channel="day_trade",
        fingerprint="vwap_reclaim",
        horizon=12,
        metric="p_higher",
        target_r=2.0,
        params={"bar_minutes": 5},
    ),
]


def catalog_queries() -> list[StudyQuery]:
    return [q.model_copy(deep=True) for q in CATALOG]


__all__ = ["CATALOG", "catalog_queries"]
