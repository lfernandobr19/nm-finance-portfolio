"""Swing Desk cycle: ingest D → derive W → score → Top N suggestions."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.models import (
    AssetClass,
    DividendFrequency,
    InvestmentAccount,
    StrategyKind,
    Suggestion,
    SuggestionStatus,
)
from app.services.brapi_client import BrapiClient
from app.services.notify import notify_suggestion
from app.services.swing.indicators import (
    BREAKOUT_LOOKBACK,
    atr,
    atr_pct,
    daily_breakout_long,
    derive_weekly,
    hourly_confirmation_status,
    recent_swing_low,
    trend_context_allows_long,
    volume_vs_sma,
    weekly_trend_bullish,
)
from app.services.studies.apply import swing_force_review
from app.services.swing.score import SetupSignals, rank_key, score_setup
from app.services.swing.universe import swing_tickers

logger = logging.getLogger("fiidesk.swing")
settings = get_settings()


def _pending_swing(db: Session, account_id: str, ticker: str) -> bool:
    return (
        db.query(Suggestion)
        .filter(
            Suggestion.account_id == account_id,
            Suggestion.ticker == ticker,
            Suggestion.strategy_kind == StrategyKind.swing,
            Suggestion.status == SuggestionStatus.pending,
        )
        .count()
        > 0
    )


def _is_brl_account(account: InvestmentAccount) -> bool:
    """Swing runs on BRL accounts only (B3 tickers via BRAPI, sized in BRL)."""
    currency = getattr(account, "currency", None)
    currency_val = currency.value if hasattr(currency, "value") else str(currency or "BRL")
    broker = (getattr(account, "broker_code", None) or "inter").lower()
    return currency_val.upper().endswith("BRL")


def _position_size_brl(
    account: InvestmentAccount,
    *,
    letter: str,
    entry: float,
    stop: float,
) -> float:
    equity = float(getattr(account, "cash_brl", None) or account.swing_equity_brl or 0)
    if equity <= 0 or entry <= stop:
        return 0.0
    if letter == "A":
        risk_pct = float(account.swing_risk_pct_a)
    elif letter == "B":
        risk_pct = float(account.swing_risk_pct_b)
    else:
        # C → paper-sized small ticket for review only
        return min(float(account.max_ticket_brl), equity * 0.02)

    risk_budget = equity * (risk_pct / 100.0)
    per_share_risk = entry - stop
    if per_share_risk <= 0:
        return 0.0
    shares = math.floor(risk_budget / per_share_risk)
    amount = shares * entry
    # Respect cash floor when sizing: leave floor of equity as cash
    floor = equity * (float(account.swing_cash_floor_pct) / 100.0)
    max_deploy = max(0.0, equity - floor)
    amount = min(amount, max_deploy, float(account.max_ticket_brl))
    return round(amount, 2)


def analyze_ticker(
    ticker: str, client: BrapiClient, stats: dict | None = None
) -> dict | None:
    bars = client.fetch_daily_bars(ticker)
    if len(bars) < 40:
        return None
    weekly = derive_weekly(bars)
    if len(weekly) < 12:
        return None

    # 1) Trend: price > weekly SMA AND SMA rising (rejects dead-cat after long dump)
    bull = weekly_trend_bullish(weekly, 10)
    # 2) Entry: break recent highs only (~2 weeks), not the whole 3mo window
    broke, level = daily_breakout_long(bars, BREAKOUT_LOOKBACK)
    # 3) Context: older range says whether this bounce is continuation or hope
    context_ok, context_detail = trend_context_allows_long(bars, weekly)
    if not bull or not broke or not context_ok:
        return None

    last = bars[-1]
    entry = round(float(last.close), 2)
    # Stop: recent swing low and/or 1.5×ATR — not anchored on stale highs
    a = atr(bars, 14)
    stop_atr = entry - 1.5 * a if a else entry * 0.97
    swing_low = recent_swing_low(bars, BREAKOUT_LOOKBACK)
    stop_swing = (swing_low * 0.995) if swing_low is not None else stop_atr
    stop_level = (level * 0.995) if level else stop_atr
    stop = round(min(stop_atr, stop_swing, stop_level), 2)
    if stop >= entry:
        stop = round(entry * 0.97, 2)
    risk = entry - stop
    target = round(entry + 2.0 * risk, 2)  # aim R:R 2 for A path; score may downgrade

    atrp = atr_pct(bars, 14)
    volr = volume_vs_sma(bars, 20)
    scored = score_setup(
        SetupSignals(
            weekly_bullish=bull,
            daily_breakout=broke,
            breakout_level=round(level, 2) if level is not None else None,
            atr_pct=round(atrp, 2) if atrp is not None else None,
            volume_ratio=round(volr, 2) if volr is not None else None,
            entry=entry,
            stop=stop,
            target=target,
        )
    )
    if not scored:
        return None

    scored.reasons.append(
        {"rule": "trend_context", "passed": True, "detail": context_detail}
    )

    h1_status = "h1_skip"
    if getattr(settings, "swing_h1_enabled", True):
        try:
            hourly = client.fetch_hourly_bars(ticker)
        except Exception:
            logger.exception("Swing hourly fetch failed for %s", ticker)
            hourly = None
        h1_status = hourly_confirmation_status(
            hourly, breakout_level=float(level), stop=stop
        )
        if stats is not None and h1_status in stats:
            stats[h1_status] += 1
        if h1_status == "h1_fail":
            logger.info("Swing skip %s: h1_fail", ticker)
            return None

    return {
        "ticker": ticker,
        "scored": scored,
        "entry": entry,
        "stop": stop,
        "target": target,
        "atr_pct": round(atrp, 2) if atrp is not None else None,
        "volume_ratio": round(volr, 2) if volr is not None else None,
        "breakout_level": round(level, 2) if level is not None else None,
        "context": context_detail,
        "rank": rank_key(scored, atrp, volr),
        "h1_status": h1_status,
    }


def run_swing_cycle(db: Session) -> list[Suggestion]:
    if not settings.swing_enabled:
        logger.info("Swing cycle skipped (SWING_ENABLED=false)")
        return []
    if not settings.brapi_token:
        logger.warning("Swing cycle skipped (BRAPI_TOKEN missing)")
        return []

    blocked, swing_guard_reason = swing_force_review()

    client = BrapiClient()
    candidates: list[dict] = []
    stats = {"h1_ok": 0, "h1_skip": 0, "h1_fail": 0}
    for ticker in swing_tickers():
        try:
            row = analyze_ticker(ticker, client, stats=stats)
            if row:
                candidates.append(row)
        except Exception:
            logger.exception("Swing analyze failed for %s", ticker)

    candidates.sort(key=lambda r: r["rank"], reverse=True)
    top = candidates[: settings.swing_top_n]
    logger.info("Swing candidates=%d top=%d", len(candidates), len(top))

    accounts = [a for a in db.query(InvestmentAccount).all() if _is_brl_account(a)]
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.swing_suggestion_ttl_hours)
    created: list[Suggestion] = []

    for account in accounts:
        for row in top:
            ticker = row["ticker"]
            if _pending_swing(db, account.id, ticker):
                continue
            if blocked:
                from app.services.desk_gate import log_scan

                log_scan(
                    db,
                    account,
                    StrategyKind.swing,
                    ticker,
                    "study_suppressed",
                    price=float(row["entry"]),
                    payload={"reason": swing_guard_reason},
                )
                continue
            if swing_guard_reason:
                # Advisory: the pattern is weak, but the desk decides — the
                # weakness travels with the trade instead of locking it out.
                row["study_note"] = swing_guard_reason
            scored = row["scored"]
            amount = _position_size_brl(
                account,
                letter=scored.letter,
                entry=row["entry"],
                stop=row["stop"],
            )
            if amount <= 0:
                # Not actionable: can't afford a single share. Hide instead of
                # surfacing a zero-amount suggestion the user can't trade.
                logger.info(
                    "Swing skip %s for %s: amount=0 (cash below one share)",
                    ticker,
                    account.name,
                )
                from app.services.desk_gate import log_scan

                log_scan(
                    db,
                    account,
                    StrategyKind.swing,
                    ticker,
                    "unaffordable",
                    price=float(row["entry"]),
                    notional=0.0,
                )
                continue
            suggestion = Suggestion(
                account_id=account.id,
                ticker=ticker,
                strategy_kind=StrategyKind.swing,
                asset_class=AssetClass.bdr_reit if ticker.endswith("34") else AssetClass.fii,
                dividend_frequency=DividendFrequency.other,
                score=scored.numeric_score,
                swing_score_letter=scored.letter,
                entry_price=row["entry"],
                stop_price=row["stop"],
                target_price=row["target"],
                r_multiple=scored.r_multiple,
                status=SuggestionStatus.pending,
                reasons=scored.reasons,
                metrics={
                    "price": row["entry"],
                    "entry": row["entry"],
                    "stop": row["stop"],
                    "target": row["target"],
                    "atr_pct": row["atr_pct"],
                    "volume_ratio": row["volume_ratio"],
                    "breakout_level": row["breakout_level"],
                    "score_letter": scored.letter,
                    "r_multiple": scored.r_multiple,
                    "strategy": "swing_recent_breakout_v3",
                    "context": row.get("context"),
                    "rule_version": 3,
                    "h1_status": row.get("h1_status", "h1_skip"),
                    "study_note": row.get("study_note"),
                },
                price_explanation=(
                    f"Swing {scored.letter}: entrada {row['entry']:.2f}, "
                    f"stop {row['stop']:.2f}, alvo {row['target']:.2f} "
                    f"(R:R {scored.r_multiple:.2f})"
                ),
                rule_version=3,
                proposed_amount_brl=amount,
                expires_at=expires_at,
            )
            db.add(suggestion)
            db.flush()
            try:
                notify_suggestion(db, suggestion)
            except Exception:
                logger.exception("notify swing failed")
            created.append(suggestion)

    db.commit()
    from app.services.intelligence import patch_intelligence_status

    patch_intelligence_status(
        {
            "swing_h1": {
                **stats,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        }
    )
    return created
