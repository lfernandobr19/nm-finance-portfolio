from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.models import AccountRule, AssetClass, DividendFrequency, MarketSnapshot


@dataclass
class ScoreResult:
    score: float
    reasons: list[dict[str, Any]]
    passed: bool
    effective_yield: float


def effective_yield(snapshot: MarketSnapshot) -> float:
    """FII: gross DY. BDR REIT: net after withholding."""
    if snapshot.asset_class == AssetClass.bdr_reit:
        return round(snapshot.dividend_yield * (1.0 - float(snapshot.withholding_rate or 0)), 4)
    return float(snapshot.dividend_yield)


def score_snapshot(snapshot: MarketSnapshot, rule: AccountRule) -> ScoreResult:
    reasons: list[dict[str, Any]] = []
    points = 0.0
    max_points = 0.0
    eff = effective_yield(snapshot)
    min_eff = float(getattr(rule, "min_effective_yield", None) or rule.min_dividend_yield)

    def check(name: str, passed: bool, detail: str, weight: float) -> None:
        nonlocal points, max_points
        max_points += weight
        if passed:
            points += weight
        reasons.append({"rule": name, "passed": passed, "detail": detail})

    allowed_classes = [str(c).lower() for c in (getattr(rule, "allowed_asset_classes", None) or [])]
    if not allowed_classes:
        allowed_classes = ["fii", "bdr_reit"]
    class_ok = snapshot.asset_class.value in allowed_classes
    check(
        "allowed_asset_classes",
        class_ok,
        f"Classe {snapshot.asset_class.value} "
        + (f"(filtro: {', '.join(allowed_classes)})" if allowed_classes else ""),
        15,
    )

    check(
        "min_effective_yield",
        eff >= min_eff,
        f"Yield efetivo {eff:.2f}% (mín {min_eff:.2f}%)"
        + (
            f" — bruto {snapshot.dividend_yield:.2f}% × (1−{snapshot.withholding_rate:.0%})"
            if snapshot.asset_class == AssetClass.bdr_reit
            else " — DY bruto FII"
        ),
        30,
    )
    check(
        "max_p_vp",
        snapshot.p_vp <= rule.max_p_vp,
        f"P/VP {snapshot.p_vp:.2f} (máx {rule.max_p_vp:.2f})",
        20,
    )
    check(
        "min_avg_volume",
        snapshot.avg_volume >= rule.min_avg_volume,
        f"Volume médio R$ {snapshot.avg_volume:,.0f} (mín {rule.min_avg_volume:,.0f})",
        15,
    )

    excluded = {t.upper() for t in (rule.excluded_tickers or [])}
    check(
        "excluded_tickers",
        snapshot.ticker.upper() not in excluded,
        f"Ticker {snapshot.ticker} {'bloqueado' if snapshot.ticker.upper() in excluded else 'permitido'}",
        5,
    )

    allowed = [s.lower() for s in (rule.allowed_sectors or [])]
    sector_ok = (not allowed) or (snapshot.sector.lower() in allowed)
    check(
        "allowed_sectors",
        sector_ok,
        f"Setor '{snapshot.sector or 'n/d'}'"
        + (f" (filtro: {', '.join(allowed)})" if allowed else " (sem filtro)"),
        5,
    )

    prefer_monthly = bool(getattr(rule, "prefer_monthly_dividends", True))
    is_monthly = snapshot.dividend_frequency == DividendFrequency.monthly
    if prefer_monthly:
        check(
            "prefer_monthly_dividends",
            is_monthly,
            f"Frequência {snapshot.dividend_frequency.value} (exige mensal)",
            10,
        )
    else:
        # Soft boost only: always "pass" but only awards points if monthly
        max_points += 10
        if is_monthly:
            points += 10
        reasons.append(
            {
                "rule": "prefer_monthly_dividends",
                "passed": True,
                "detail": f"Frequência {snapshot.dividend_frequency.value} (preferência desligada)",
            }
        )

    score = round((points / max_points) * 100, 2) if max_points else 0.0
    # Hard block: asset class must match rule filter when classes are configured.
    passed = score >= rule.score_threshold and class_ok
    return ScoreResult(
        score=score,
        reasons=reasons,
        passed=passed,
        effective_yield=eff,
    )


def build_price_explanation(snapshot: MarketSnapshot, reasons: list[dict[str, Any]]) -> str:
    eff = effective_yield(snapshot)
    lines = [
        f"{snapshot.ticker} ({snapshot.asset_class.value}) cotado a R$ {snapshot.price:.2f} na {snapshot.venue}.",
        f"Frequência de dividendo: {snapshot.dividend_frequency.value} | exposição: {snapshot.currency_exposure.value}.",
        f"Variação dia: {snapshot.change_day_pct:+.2f}% | mês: {snapshot.change_month_pct:+.2f}%.",
        f"DY bruto: {snapshot.dividend_yield:.2f}% | yield efetivo: {eff:.2f}% | P/VP: {snapshot.p_vp:.2f} | Vol.: R$ {snapshot.avg_volume:,.0f}.",
    ]
    if snapshot.underlying_ticker:
        lines.append(f"Underlying: {snapshot.underlying_ticker}.")
    lines.append("Critérios:")
    for r in reasons:
        mark = "OK" if r["passed"] else "FALHOU"
        lines.append(f"- [{mark}] {r['rule']}: {r['detail']}")
    return "\n".join(lines)
