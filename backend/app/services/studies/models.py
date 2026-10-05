"""Pydantic models for active learn studies.

The 7B model may *propose* a ``StudyQuery``: its JSON must parse against these
schemas with extra keys rejected (``extra='forbid'``) so it cannot stretch the
contract. Probabilities are computed only from bars, never from the LLM.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Channels mirror the desk's existing data sources.
CHANNELS = ("hv_dip", "swing", "day_trade")
FINGERPRINTS = ("deep_dip", "breakout_h1", "orb", "vwap_reclaim")
METRICS = ("p_higher", "p_stop_first", "recovery", "gap_hit", "p_recover")


class StudyQuery(BaseModel):
    """A computable question the desk asks over cached bars."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Identificador único, ex: 'deep_dip'")
    label: str = Field(description="Pergunta em PT, ex: 'Dip profundo costuma recuperar?'")
    channel: str = Field(description="Canal de dados: hv_dip | swing | day_trade")
    fingerprint: str = Field(
        description="Padrão a casar nos bares: deep_dip | breakout_h1 | orb | vwap_reclaim"
    )
    horizon: int = Field(default=10, ge=1, le=60, description="Barras à frente para medir o desfecho")
    metric: str = Field(
        default="p_higher",
        description="Métrica principal: p_higher | p_stop_first | recovery | gap_hit",
    )
    target_r: float = Field(
        default=2.0, gt=0.0, le=10.0, description="Alvo em múltiplos de R (risk = entry - stop)"
    )
    stop_pct: float | None = Field(
        default=None, ge=0.1, le=60.0, description="Stop em % abaixo da entrada (quando o fingerprint não define)"
    )
    params: dict[str, float] = Field(default_factory=dict, description="Parâmetros extras do fingerprint")


class StudyResult(BaseModel):
    """One study run: per-ticker or universe aggregate (``ticker == 'UNIVERSE'``)."""

    query_id: str
    label: str = ""
    channel: str = "hv_dip"
    fingerprint: str = ""
    ticker: str = "UNIVERSE"
    n: int = 0
    p_higher: float | None = None  # P(alvo dentro do horizonte)
    p_stop_first: float | None = None  # P(stop antes do alvo)
    expectancy_r: float | None = None  # retorno médio em R
    trend_up: float | None = None  # fração dos analogados com tendência a favor
    vs_universe: float | None = None  # p_higher ticker - p_higher universo
    recovery: float | None = None  # P(preço recupera metade do dip no horizonte)
    gap_hit: float | None = None  # P(gap material fecha), None se não houve gap
    p_recover: float | None = None  # P(fecha acima da entrada após `horizon` pregões) — a régua do usuário
    # Trecho final da série, nunca usado para descobrir o padrão: é onde a
    # descoberta é confirmada ou desmentida.
    oos_n: int = 0
    oos_p_higher: float | None = None
    oos_p_stop_first: float | None = None
    oos_expectancy_r: float | None = None
    oos_recovery: float | None = None
    oos_gap_hit: float | None = None
    oos_p_recover: float | None = None
    applied: bool = False
    note: str | None = None


class InsightEvidence(BaseModel):
    """One grounded fact cited by an LLM insight (value comes from the digest)."""

    model_config = ConfigDict(extra="forbid")

    fact: str = Field(default="", description="Fato em PT, ex: 'P(alvo antes do stop)'")
    value: str = Field(default="", description="Valor textual, ex: '0.33 (n=3700)'")

    @field_validator("fact", "value", mode="before")
    @classmethod
    def _coerce_text(cls, v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, (int, float, bool)):
            return str(v)
        return v


class Insight(BaseModel):
    """A qualitative, grounded insight the LLM wrote from a numeric digest.

    The LLM only phrases what the pre-computed digest already contains; it never
    invents probabilities. ``extra='forbid'`` keeps it inside the contract, while
    the coercing validators absorb the model's loose typing (null ticker, numeric
    evidence values) instead of dropping every insight.
    """

    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(default="UNIVERSE", description="Ticker alvo ou 'UNIVERSE'")
    kind: str = Field(default="universe", description="universe | ticker")
    text: str = Field(default="", description="Insight em PT, curto e fundamentado")
    evidence: list[InsightEvidence] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    channel: str = Field(default="hv_dip", description="hv_dip | swing | day_trade")

    @field_validator("ticker", mode="before")
    @classmethod
    def _coerce_ticker(cls, v: Any) -> str:
        if v is None or v == "":
            return "UNIVERSE"
        return v

    @field_validator("kind", mode="before")
    @classmethod
    def _coerce_kind(cls, v: Any) -> str:
        if v is None or v == "":
            return "universe"
        return v

    @field_validator("text", "channel", mode="before")
    @classmethod
    def _coerce_str(cls, v: Any) -> str:
        if v is None:
            return ""
        return v

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, v: Any) -> float:
        if v is None:
            return 0.0
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                return 0.0
        return v

    @field_validator("evidence", mode="before")
    @classmethod
    def _coerce_evidence(cls, v: Any) -> Any:
        return [] if v is None else v


class StudySnapshot(BaseModel):
    ts: str | None = None
    queries: list[StudyQuery] = Field(default_factory=list)
    results: list[StudyResult] = Field(default_factory=list)
    guards: dict[str, Any] = Field(default_factory=dict)
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    insights: list[Insight] = Field(default_factory=list)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "CHANNELS",
    "FINGERPRINTS",
    "METRICS",
    "StudyQuery",
    "StudyResult",
    "InsightEvidence",
    "Insight",
    "StudySnapshot",
    "now_iso",
]
