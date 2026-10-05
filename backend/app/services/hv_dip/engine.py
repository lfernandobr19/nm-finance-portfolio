"""High-Vol Dip cycle: daily bars → dip score → suggestions on USD accounts."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.models import (
    AccountCurrency,
    AssetClass,
    DividendFrequency,
    ExecutionMode,
    HvDipObservation,
    InvestmentAccount,
    Position,
    PositionStatus,
    StrategyKind,
    Suggestion,
    SuggestionStatus,
)
from app.services.market_data import MarketDataClient
from app.services.hv_dip.indicators import (
    atr_pct,
    days_since_recent_high,
    dip_pct_from_high,
    is_52w_low,
    is_fresh_high,
    quality_tier,
    recent_high,
    recent_low,
    recovery_in_progress,
    recovery_rate,
    round_trips,
    volume_vs_sma,
    weekly_range_pct,
)
from app.services.hv_dip.configs import get_active_params
from app.services.hv_dip.exit_engine import quick_target_prices
from app.services.hv_dip.observation import evaluate_risky_recovery
from app.services.hv_dip.score import HvDipSignals, rank_key, score_hv_dip
from app.services.hv_dip.universe import hv_dip_tickers
from app.services.learn.ledger import record_forecast, record_forecast_once
from app.services.news_llm import active_bullish_events, active_recovery_events
from app.services.studies.apply import hv_dip_force_review
from app.services.notify import notify_suggestion
from app.services.orders import create_order_from_suggestion
from app.services.hv_dip.sizing import (
    SizingBasis,
    account_sizing_basis,
    deployed_on_ticker_usd,
    usd_cash,
)
from app.services.swing.indicators import (
    derive_weekly,
    higher_lows_recent,
    trend_context_allows_long,
)

logger = logging.getLogger("fiidesk.hv_dip")
settings = get_settings()


def _pending_hv(db: Session, account_id: str, ticker: str) -> bool:
    return (
        db.query(Suggestion)
        .filter(
            Suggestion.account_id == account_id,
            Suggestion.ticker == ticker,
            Suggestion.strategy_kind == StrategyKind.hv_dip,
            Suggestion.status == SuggestionStatus.pending,
        )
        .count()
        > 0
    )


def _open_position(db: Session, account_id: str, ticker: str) -> Position | None:
    return (
        db.query(Position)
        .filter(
            Position.account_id == account_id,
            Position.ticker == ticker,
            Position.strategy_kind == StrategyKind.hv_dip,
            Position.status == PositionStatus.open,
        )
        .order_by(Position.opened_at.desc())
        .first()
    )


def _usd_cash(account: InvestmentAccount) -> float:
    return usd_cash(account)


def _calibration_size_scale(p_raw: float | None) -> float:
    """Shrink size when the raw score is more confident than the calibrated p.

    Never increases size: an unfitted source (identity mapping) stays at 1.0.
    """
    if p_raw is None or p_raw <= 0:
        return 1.0
    try:
        from app.services.learn.calibration import calibrated_probability

        p_cal = calibrated_probability("hv_dip", float(p_raw))
    except Exception:
        return 1.0
    return max(0.25, min(1.0, float(p_cal) / float(p_raw)))


def _equal_risk_sizing(
    basis: SizingBasis,
    entry: float,
    stop: float,
    *,
    p_raw: float | None = None,
) -> int:
    """Whole-lot equal-risk sizing: qty = floor(risk_budget / (entry − stop)).

    risk_budget = settled_cash × hv_dip_qt_risk_pct. Every trade risks the same
    dollar amount, so the share count scales inversely with the stop distance.
    Returns a whole-share count (0 if even one share exceeds the risk budget).
    Inflated confidence is scaled down by Platt before the budget is applied.
    """
    risk_per_share = max(entry - stop, 1e-6)
    risk_budget = basis.settled * (float(settings.hv_dip_qt_risk_pct or 1.0) / 100.0)
    risk_budget *= _calibration_size_scale(p_raw)
    return int(risk_budget / risk_per_share)


def news_catalyst_bonus(
    confidence: float | None,
    event_type: str | None = None,
) -> float:
    """Continuous news bonus: cap × Platt p of the (event_type, confidence) pair.

    Replaces the old 0.7 door + flat +5. A type with no fit of its own falls
    back to the pooled ``news`` curve, then to the raw score. A poorly
    calibrated type shrinks its own bonus without a feature flag.
    """
    cap = float(settings.news_score_bonus or 5.0)
    raw = float(confidence or 0.0)
    try:
        from app.services.learn.calibration import (
            calibrated_probability,
            news_calibrator_key,
        )

        source = news_calibrator_key(event_type) if event_type else "news"
        p_cal = calibrated_probability(source, raw, fallback="news")
    except Exception:
        p_cal = raw
    return max(0.0, min(cap, cap * float(p_cal)))


def _pre_news_close(bars: list, published_at) -> float | None:
    """Close of the last bar at/before the news timestamp (gap-filter baseline)."""
    if not bars or published_at is None:
        return None
    prev: float | None = None
    for b in bars:
        if getattr(b, "date", None) is None:
            continue
        if b.date <= published_at:
            prev = float(b.close)
        else:
            break
    return prev


def _catalyst(db: Session, ticker: str):
    events = active_bullish_events(db, ticker)
    return events[0] if events else None


def _news_position_count(db: Session, account_id: str) -> int:
    """Open hv_dip positions that were opened from a news-catalyst suggestion."""
    rows = (
        db.query(Position)
        .filter(
            Position.account_id == account_id,
            Position.strategy_kind == StrategyKind.hv_dip,
            Position.status == PositionStatus.open,
        )
        .all()
    )
    n = 0
    for p in rows:
        sug = db.get(Suggestion, p.suggestion_id)
        if sug and (sug.metrics or {}).get("catalyst"):
            n += 1
    return n


def _auto_deployed_today_usd(db: Session, account_id: str) -> float:
    """USD already auto-deployed today (sum of auto_approved hv_dip suggestions)."""
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = (
        db.query(Suggestion)
        .filter(
            Suggestion.account_id == account_id,
            Suggestion.strategy_kind == StrategyKind.hv_dip,
            Suggestion.status == SuggestionStatus.auto_approved,
            Suggestion.acted_at >= start,
        )
        .all()
    )
    return float(sum(float(s.proposed_amount_brl or 0.0) for s in rows))


def _bars_with_live_close(bars: list, last_price: float | None):
    if last_price is None or not bars:
        return bars
    from app.services.brapi_client import Bar

    last = bars[-1]
    return [
        *bars[:-1],
        Bar(
            date=last.date,
            open=last.open,
            high=max(last.high, last_price),
            low=min(last.low, last_price),
            close=last_price,
            volume=last.volume,
        ),
    ]


def _append_reason(existing: str | None, addition: str) -> str:
    return f"{existing} · {addition}" if existing else addition


def _avg_dollar_volume(bars: list, n: int = 20) -> float | None:
    """20-bar average (close * volume) as a rough ADTV liquidity proxy."""
    window = bars[-n:]
    vals = [
        float(b.close) * float(b.volume or 0)
        for b in window
        if getattr(b, "volume", None) is not None
    ]
    if not vals:
        return None
    return sum(vals) / len(vals)


def build_hv_dip_setup(
    ticker: str,
    bars: list,
    *,
    last_price: float | None = None,
    min_dip_pct: float | None = None,
    min_recovery_rate: float | None = None,
    reject_fresh_high: bool | None = None,
) -> dict | None:
    """Build hv_dip setup from daily bars; optional last_price overrides last close.

    Aligned to the mean-reversion thesis: buy deep dips in liquid names that
    historically recover, avoid fresh 4-month tops and micro-caps.

    The three threshold overrides carry the active learn-loop config
    (`hv_dip/configs.py`). Leaving them as None falls back to settings, which
    keeps the standalone callers (scripts, tests) working unchanged.
    """
    lookback = int(settings.hv_dip_lookback or 10)
    floor_dip = float(min_dip_pct if min_dip_pct is not None else settings.hv_dip_min_dip_pct)
    osc_window = int(settings.hv_dip_osc_window or 84)
    osc_swing = float(settings.hv_dip_osc_swing_pct or 8.0)
    min_recovery = float(
        min_recovery_rate
        if min_recovery_rate is not None
        else (settings.hv_dip_min_recovery_rate or 0.6)
    )
    drop_fresh_high = (
        bool(reject_fresh_high)
        if reject_fresh_high is not None
        else bool(settings.hv_dip_reject_fresh_high)
    )

    work = _bars_with_live_close(bars, last_price)
    if len(work) < max(40, lookback + 5):
        return None

    dip = dip_pct_from_high(work, lookback)
    if dip is None or dip < floor_dip:
        return None

    hi = recent_high(work, lookback)
    setup_low = recent_low(work, lookback)
    if hi is None or setup_low is None:
        return None

    days_since_high = days_since_recent_high(work, lookback)

    entry = round(float(work[-1].close), 2)
    if entry < setup_low * 0.995 and not is_52w_low(work):
        return None

    # Whole-lot universe: skip names above the max entry price (no fractional).
    if entry > float(settings.hv_dip_qt_max_price or 20.0):
        return None

    # Quality/liquidity tier: micro-caps can break the strategy — reject them.
    tier = quality_tier(
        _avg_dollar_volume(work),
        price=entry,
        min_dollar_volume=float(settings.hv_dip_min_dollar_volume or 20_000_000.0),
        mega_dollar_volume=float(settings.hv_dip_mega_dollar_volume or 200_000_000.0),
    )
    if tier == "micro":
        return None

    # Quick Target: hard stop + small target, set by walk-forward config.
    stop, target = quick_target_prices(entry)
    risk = entry - stop

    atrp = atr_pct(work, 14)
    volr = volume_vs_sma(work, 20)
    wr = weekly_range_pct(work)
    at_52w = is_52w_low(work)
    review = False
    review_reason = None
    skip_reason: str | None = None

    if wr is not None and wr < 3.0 and (atrp or 0) < 2.0:
        return None

    weekly = derive_weekly(work)
    context_ok, context_detail = trend_context_allows_long(work, weekly)
    improving = higher_lows_recent(work)

    # HARD GATE (Quick Target): require confirmation of recovery before entering.
    # `recovery_in_progress` (rebound off the bottom + higher lows) implies
    # `higher_lows_recent`, so either signal confirms the turnaround. No recovery
    # confirmation → reject (this is what replaces the old "informative" flag).
    rip = recovery_in_progress(work)
    if not improving and not rip:
        return None

    # Mean-reversion: does this name historically recover from similar dips?
    recovery = recovery_rate(work, window=osc_window, swing_pct=osc_swing)
    trips = round_trips(work, window=osc_window, swing_pct=osc_swing)
    fresh_high = is_fresh_high(work, window=osc_window, recent_lookback=lookback)

    # Structural decline (falling knife) is no longer a binary rejection: it becomes
    # review/observation (Fase 5b owns the specialized observation state machine).
    month_ago_close: float | None = None
    if len(work) >= 22:
        month_ago_close = float(work[-22].close)
    structural_decline = (
        not context_ok
        and month_ago_close is not None
        and month_ago_close < setup_low * 0.90
    )

    # Quality names need a recovery track record; fresh tops need extra caution.
    if tier in ("mega", "large") and (recovery is None or recovery < min_recovery):
        review = True
        review_reason = _append_reason(
            review_reason,
            "Sem histórico de recuperação (mean-reversion não confirmado)"
            if recovery is None
            else f"Recupera só {recovery:.0%} das quedas similares",
        )
    # Mean-reversion thesis: a dip after a fresh ~4-month high is a momentum
    # pullback, not the setup we trade. The desk skips it — no HITL queue.
    if drop_fresh_high and fresh_high:
        skip_reason = "fresh_high"
    if structural_decline:
        review = True
        review_reason = _append_reason(review_reason, "Queda estrutural — em observação")

    scored = score_hv_dip(
        HvDipSignals(
            dip_pct=dip,
            atr_pct=atrp,
            volume_ratio=volr,
            entry=entry,
            stop=stop,
            target=target,
            review_required=review,
            review_reason=review_reason,
            recovery_rate=recovery,
            quality_tier=tier,
            is_fresh_high=bool(fresh_high),
            min_recovery_rate=min_recovery,
        )
    )
    if not scored:
        return None

    # Trend context is informational only (no longer an entry gate).
    if not context_ok and context_detail:
        review_reason = _append_reason(review_reason, context_detail)

    rank = rank_key(scored, atrp, dip)
    if improving and context_ok:
        rank += 0.05

    return {
        "ticker": ticker,
        "scored": scored,
        "entry": entry,
        "stop": stop,
        "target": target,
        "setup_low": round(setup_low, 2),
        "recent_high": round(hi, 2),
        "days_since_recent_high": days_since_high,
        "dip_pct": round(dip, 2),
        "atr_pct": round(atrp, 2) if atrp is not None else None,
        "volume_ratio": round(volr, 2) if volr is not None else None,
        "weekly_range_pct": round(wr, 2) if wr is not None else None,
        "review_required": review,
        "review_reason": review_reason,
        "trend_context_ok": context_ok,
        "higher_lows_recent": improving,
        "recovery_in_progress": rip,
        "structural_decline": structural_decline,
        "recovery_rate": round(recovery, 3) if recovery is not None else None,
        "round_trips": trips,
        "quality_tier": tier,
        "is_fresh_high": bool(fresh_high),
        "is_52w_low": bool(at_52w),
        "skip_reason": skip_reason,
        "rank": rank,
    }


def analyze_ticker(
    ticker: str,
    client: MarketDataClient,
    bars: list | None = None,
    last_price: float | None = None,
    thresholds: dict[str, float | None] | None = None,
) -> dict | None:
    if bars is None:
        bars = client.fetch_daily_bars(ticker)
    return build_hv_dip_setup(
        ticker, bars, last_price=last_price, **(thresholds or {})
    )


def active_thresholds(db: Session) -> dict[str, float | bool]:
    """Entry thresholds from the active learn-loop config (`hv_dip/configs.py`).

    Without this the versioned config was written and displayed but never read
    by the engine, so the learn loop could not affect a single decision.
    """
    params = get_active_params(db)
    return {
        "min_dip_pct": float(params["dip_pct"]),
        "min_recovery_rate": float(params["min_recovery_rate"]),
        "reject_fresh_high": bool(params["reject_fresh_high"] >= 0.5),
    }


def mark_thesis_skips(candidates: list[dict]) -> None:
    """52w lows without a news catalyst are skipped — no HITL queue."""
    for row in candidates:
        if row.get("skip_reason"):
            continue
        if row.get("is_52w_low") and not row.get("catalyst"):
            row["skip_reason"] = "low_52w"


def _apply_catalysts(db: Session, candidates: list[dict], bars_map: dict) -> None:
    """Attach bullish news catalysts to candidates: score/rank bonus + gap gate.

    News elevates score/rank (and C→B) but never creates a setup. If the ticker
    already gapped up past the post-news threshold, the candidate is skipped
    (``skip_reason=news_gap``) so auto-buy does not chase the move.
    """
    gap_pct = float(settings.news_gap_filter_pct or 5.0)
    for row in candidates:
        ticker = row["ticker"]
        ev = _catalyst(db, ticker)
        if ev is None:
            continue

        bonus = news_catalyst_bonus(ev.confidence, ev.event_type)
        pre_close = _pre_news_close(bars_map.get(ticker, []), ev.published_at)
        entry = float(row["entry"])
        gapped = (
            pre_close is not None
            and pre_close > 0
            and (entry - pre_close) / pre_close > gap_pct / 100.0
        )

        scored = row["scored"]
        row["rank"] = float(row["rank"]) + bonus
        scored.numeric_score = round(min(scored.numeric_score + bonus, 99.0), 1)
        if scored.letter == "C":
            scored.letter = "B"
        scored.reasons.append(
            {
                "rule": "news_catalyst",
                "passed": True,
                "detail": f"{ev.event_type} bullish (conf {float(ev.confidence or 0):.2f})",
            }
        )
        row["catalyst"] = {
            "event_type": ev.event_type,
            "sentiment": ev.sentiment,
            "confidence": float(ev.confidence or 0),
            "impact_score": float(ev.impact_score or 0),
            "title": ev.title,
            "url": ev.url,
        }
        row["news_event"] = ev

        # Principle: every buy must produce learning. The catalyst is about to
        # move the score, so the claim it implies goes on record at the horizon
        # the strategy actually holds — once per event, not once per scan.
        record_forecast_once(
            db,
            ref_id=f"news:{ev.id}",
            source="news",
            kind=str(ev.event_type or "other"),
            ticker=ticker,
            p_pred=float(ev.confidence or 0.5),
            horizon_days=int(settings.hv_dip_max_hold_days or 14),
            features={
                "direction": "down" if ev.sentiment == "bearish" else "up",
                "event_type": ev.event_type,
                "sentiment": ev.sentiment,
                "impact_score": float(ev.impact_score or 0),
                "gapped": bool(gapped),
                "score_bonus": bonus,
            },
        )

        if gapped:
            row["skip_reason"] = "news_gap"


def _upsert_observation(
    db: Session,
    account_id: str,
    ticker: str,
    *,
    recovery_probability: float | None,
    recovery_in_progress: bool,
    active_catalyst: bool,
    decision: str,
    note: str,
) -> None:
    now = datetime.now(timezone.utc)
    obs = (
        db.query(HvDipObservation)
        .filter(
            HvDipObservation.account_id == account_id,
            HvDipObservation.ticker == ticker,
        )
        .one_or_none()
    )
    if obs is None:
        obs = HvDipObservation(
            account_id=account_id,
            ticker=ticker,
            status="observing",
            first_seen_at=now,
        )
        db.add(obs)
    obs.last_evaluated_at = now
    obs.recovery_probability = recovery_probability
    obs.recovery_in_progress = recovery_in_progress
    obs.active_catalyst = active_catalyst
    obs.last_decision = decision
    obs.note = note


def _evaluate_structural_candidates(
    db: Session, structural: list[dict], bars_map: dict
) -> list[dict]:
    """Route structural-decline candidates: risky-recovery auto-buy or observation.

    Decision is per-ticker (technical + statistical + news confluence). Rows that
    qualify are promoted to a "risky recovery A" and returned for auto-buy; the
    rest stay in observation (persisted per-account in the cycle loop).
    """
    min_probability = float(settings.hv_dip_obs_probability_min or 0.6)
    risky: list[dict] = []
    for row in structural:
        ticker = row["ticker"]
        bars = bars_map.get(ticker, [])
        rip = recovery_in_progress(bars)
        rp = row.get("recovery_rate")
        recovery_events = active_recovery_events(db, ticker)
        has_cat = bool(recovery_events)
        ok, reason = evaluate_risky_recovery(
            recovery_in_progress=rip,
            recovery_probability=rp,
            has_recovery_catalyst=has_cat,
            min_probability=min_probability,
        )
        row["recovery_in_progress"] = rip
        row["recovery_probability"] = rp
        row["has_recovery_catalyst"] = has_cat
        row["risky_recovery"] = ok
        row["obs_note"] = reason
        if ok:
            row["review_required"] = False
            row["review_reason"] = None
            row["scored"].letter = "A"
            row["scored"].reasons.append(
                {"rule": "risky_recovery", "passed": True, "detail": reason}
            )
            risky.append(row)
        else:
            row["review_required"] = True
            row["review_reason"] = _append_reason(
                row.get("review_reason"), "Queda estrutural — em observação"
            )
    return risky


def run_hv_dip_cycle(db: Session) -> list[Suggestion]:
    if not settings.hv_dip_enabled:
        logger.info("HV Dip cycle skipped (HV_DIP_ENABLED=false)")
        return []

    client = MarketDataClient()
    tickers = hv_dip_tickers()
    # Batch-fetch daily bars (cache + Yahoo history).
    bars_map = client.fetch_daily_bars_many(tickers)
    # Best-effort live quotes so intraday setups reflect current price, not stale EOD close.
    live_prices: dict[str, float] = {}
    try:
        live_prices = client.fetch_last_prices(tickers)
    except Exception:
        logger.exception("HV Dip live prices failed — using EOD closes")

    thresholds = active_thresholds(db)
    candidates: list[dict] = []
    for ticker in tickers:
        try:
            row = analyze_ticker(
                ticker,
                client,
                bars=bars_map.get(ticker),
                last_price=live_prices.get(ticker),
                thresholds=thresholds,
            )
            if row:
                candidates.append(row)
        except Exception:
            logger.exception("HV Dip analyze failed for %s", ticker)

    # Apply news catalyst: elevate score/rank, and skip a post-news gap chase.
    _apply_catalysts(db, candidates, bars_map)
    mark_thesis_skips(candidates)

    # Partition structural declines (falling knives) from normal mean-reversion setups.
    structural = [r for r in candidates if r.get("structural_decline")]
    normal = [r for r in candidates if not r.get("structural_decline")]

    # Structural declines → observation, except when a recovery confluence qualifies
    # a "risky recovery A" auto-buy.
    risky_buys = _evaluate_structural_candidates(db, structural, bars_map)

    normal.sort(key=lambda r: r["rank"], reverse=True)
    top = normal[: settings.hv_dip_top_n] + risky_buys
    logger.info(
        "HV Dip candidates=%d top=%d structural=%d risky=%d",
        len(candidates), len(top), len(structural), len(risky_buys),
    )

    accounts = (
        db.query(InvestmentAccount)
        .filter(
            InvestmentAccount.currency == AccountCurrency.USD,
            InvestmentAccount.broker_code == "tastytrade",
        )
        .all()
    )
    # Also match string currency if enum weirdness
    if not accounts:
        accounts = [
            a
            for a in db.query(InvestmentAccount).all()
            if str(getattr(a, "currency", "BRL")).endswith("USD")
        ]

    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.hv_dip_suggestion_ttl_hours)
    created: list[Suggestion] = []

    for account in accounts:
        # Persist observation state for structural declines still under watch.
        for row in structural:
            if not row.get("risky_recovery"):
                _upsert_observation(
                    db,
                    account.id,
                    row["ticker"],
                    recovery_probability=row.get("recovery_probability"),
                    recovery_in_progress=bool(row.get("recovery_in_progress")),
                    active_catalyst=bool(row.get("has_recovery_catalyst")),
                    decision="observing",
                    note=row.get("obs_note") or "",
                )

        for row in top:
            ticker = row["ticker"]
            try:
                if _pending_hv(db, account.id, ticker):
                    continue
                open_pos = _open_position(db, account.id, ticker)
                tranche = 1
                if open_pos is not None:
                    tranche = int(getattr(open_pos, "tranche_index", 1) or 1) + 1
                    if tranche > int(settings.hv_dip_max_tranches):
                        continue
                suggestion = _create_suggestion(
                    db, account, row, tranche=tranche, expires_at=expires_at
                )
            except Exception:
                # One bad ticker must not cost the whole batch (the cycle-level
                # handler rolls back everything).
                logger.exception("HV Dip suggestion failed for %s", ticker)
                continue
            if suggestion is not None:
                created.append(suggestion)

    db.commit()
    return created


def _create_suggestion(
    db: Session,
    account: InvestmentAccount,
    row: dict,
    *,
    tranche: int,
    expires_at,
) -> Suggestion | None:
    """Persist one hv_dip suggestion (amount → affordability → auto-buy → notify).

    Returns None when skipped by a thesis guard (fresh high, 52w, news gap,
    refuted pattern), the $1 floor, or the affordability guard. Shared by the
    cycle and "comprar mais".
    """
    ticker = row["ticker"]
    scored = row["scored"]
    risky = bool(row.get("risky_recovery"))
    basis = account_sizing_basis(db, account)

    entry = float(row["entry"])
    stop = float(row["stop"])

    skip = row.get("skip_reason")
    from app.services.desk_gate import log_scan
    from app.services.desk_judgment import consider, load_memories, load_news

    judged = consider(
        ticker=ticker,
        price=entry,
        cash=float(getattr(account, "cash_usd", None) or 0),
        deny_reason=str(skip) if skip else "ok",
        news=load_news(db, ticker),
        memories=load_memories(ticker),
        dip_pct=float(row["dip_pct"]) if row.get("dip_pct") is not None else None,
    )
    if judged is not None and judged.action == "observe":
        log_scan(
            db,
            account,
            StrategyKind.hv_dip,
            ticker,
            judged.reason,
            price=entry,
            payload={"reason": skip or "ok", "judgment": judged.as_dict()},
        )
        return None
    if skip:
        if judged is not None and judged.action in {"allow", "resize"}:
            logger.info("hv_dip judgment lifted %s skip=%s", ticker, skip)
            row["skip_reason"] = None
            row["judgment"] = judged.as_dict()
            skip = None
        else:
            log_scan(
                db,
                account,
                StrategyKind.hv_dip,
                ticker,
                str(skip),
                price=entry,
                payload={"reason": skip},
            )
            return None
    elif judged is not None and judged.action in {"allow", "resize"}:
        row["judgment"] = judged.as_dict()

    blocked, study_reason = hv_dip_force_review()
    if blocked:
        from app.services.desk_gate import log_scan

        log_scan(
            db,
            account,
            StrategyKind.hv_dip,
            ticker,
            "study_suppressed",
            price=entry,
            payload={"reason": study_reason},
        )
        return None
    if study_reason:
        # Advisory: the pattern is weak, but the desk decides — the weakness
        # travels with the trade as evidence instead of locking it out.
        row["study_note"] = study_reason

    # Equal-risk whole-lot sizing (Quick Target). Replaces the tranche/dip
    # multiplier scheme: every trade risks the same dollar amount, and the
    # share count is a whole lot.
    qty = _equal_risk_sizing(
        basis,
        entry,
        stop,
        p_raw=float(scored.numeric_score or 0.0) / 100.0,
    )
    if risky:
        qty = int(qty * float(settings.hv_dip_obs_risky_size_mult or 0.5))
    if qty < 1:
        from app.services.desk_gate import log_scan

        log_scan(
            db,
            account,
            StrategyKind.hv_dip,
            ticker,
            "qty_below_lot",
            price=entry,
            notional=0.0,
            payload={"stop": stop},
        )
        return None
    amount = round(qty * entry, 2)

    # Affordability guard: the whole-lot order must fit within the deployable
    # cash, the per-ticker concentration cap, and the order-value ticket ceiling.
    spendable = basis.spendable(scored.letter)
    deployed = deployed_on_ticker_usd(db, account.id, ticker)
    ticker_room = max(0.0, basis.ticker_cap - deployed)
    ticket = float(account.max_ticket_brl or 0)
    ceiling = min(spendable, ticker_room)
    if ticket > 0:
        ceiling = min(ceiling, ticket)
    if amount > ceiling + 1e-6:
        logger.debug(
            "HV Dip skip %s: amount %.2f > ceiling %.2f (spendable %.2f, ticker_room %.2f, ticket %.2f)",
            ticker, amount, ceiling, spendable, ticker_room, ticket,
        )
        from app.services.desk_gate import log_scan

        log_scan(
            db,
            account,
            StrategyKind.hv_dip,
            ticker,
            "unaffordable_ceiling",
            price=entry,
            notional=amount,
            payload={"ceiling": ceiling, "spendable": spendable},
        )
        return None

    catalyst = row.get("catalyst")
    review = bool(row["review_required"])
    status = SuggestionStatus.pending
    acted_at = None
    auto = False
    mode = getattr(account, "execution_mode", None)
    mode_val = mode.value if hasattr(mode, "value") else str(mode or ExecutionMode.paper.value)
    paper_account = mode_val == ExecutionMode.paper.value
    live_account = mode_val == ExecutionMode.live.value

    if live_account and not bool(settings.hv_dip_live_auto_buy):
        from app.services.desk_gate import DeskIntent, apply_intent, log_scan

        if bool(settings.hv_dip_live_shadow) and not review:
            apply_intent(
                db,
                DeskIntent(
                    account=account,
                    kind=StrategyKind.hv_dip,
                    ticker=ticker,
                    notional=amount,
                    price=entry,
                    score=float(scored.numeric_score or 0),
                    r_multiple=scored.r_multiple,
                    quantity=float(qty),
                    explanation="live shadow",
                    metrics={"shadow": True, "amount": amount},
                ),
                as_paper=True,
            )
        log_scan(
            db,
            account,
            StrategyKind.hv_dip,
            ticker,
            "live_shadow" if settings.hv_dip_live_shadow else "live_hold",
            price=entry,
            notional=amount,
        )
        return None

    if live_account and bool(settings.hv_dip_live_auto_buy):
        amount = round(amount * float(settings.hv_dip_live_size_mult or 0.5), 2)
        qty = max(1, int(amount // entry)) if entry > 0 else 0
        if qty < 1:
            return None

    # Auto-buy: paper, or live only when hv_dip_live_auto_buy is on.
    if (
        settings.hv_dip_auto_buy_enabled
        and (paper_account or (live_account and settings.hv_dip_live_auto_buy))
        and not review
        and not account.automation_paused
    ):
        dip = float(row["dip_pct"] or 0.0)
        deep_dip = dip >= float(settings.hv_dip_auto_buy_min_dip_pct or 15.0)
        if deep_dip or catalyst or risky:
            daily_pct = float(settings.hv_dip_auto_buy_daily_cash_pct or 50.0)
            daily_budget = basis.settled * (daily_pct / 100.0)
            deployed_today = _auto_deployed_today_usd(db, account.id)
            if deployed_today + amount <= daily_budget + 1e-6:
                status = SuggestionStatus.auto_approved
                acted_at = datetime.now(timezone.utc)
                auto = True
            else:
                logger.info(
                    "HV Dip auto-buy cap reached: deployed %.2f + %.2f > %.2f (%.0f%%/day)",
                    deployed_today, amount, daily_budget, daily_pct,
                )

    suggestion = Suggestion(
        account_id=account.id,
        ticker=ticker,
        strategy_kind=StrategyKind.hv_dip,
        asset_class=AssetClass.us_equity,
        dividend_frequency=DividendFrequency.other,
        score=scored.numeric_score,
        swing_score_letter=scored.letter,
        entry_price=row["entry"],
        stop_price=row["stop"],
        target_price=row["target"],
        r_multiple=scored.r_multiple,
        setup_low=row["setup_low"],
        tranche_index=tranche,
        review_required=review,
        review_reason=row.get("review_reason"),
        status=status,
        acted_at=acted_at,
        reasons=scored.reasons,
        metrics={
            "price": row["entry"],
            "entry": row["entry"],
            "stop": row["stop"],
            "target": row["target"],
            "setup_low": row["setup_low"],
            "quantity": qty,
            "amount": amount,
            "recent_high": row.get("recent_high"),
            "recovery_high": row.get("recent_high"),
            "days_since_recent_high": row.get("days_since_recent_high"),
            "dip_pct": row["dip_pct"],
            "atr_pct": row.get("atr_pct"),
            "volume_ratio": row.get("volume_ratio"),
            "weekly_range_pct": row.get("weekly_range_pct"),
            "recovery_rate": row.get("recovery_rate"),
            "round_trips": row.get("round_trips"),
            "quality_tier": row.get("quality_tier"),
            "is_fresh_high": row.get("is_fresh_high"),
            "structural_decline": row.get("structural_decline"),
            "risky_recovery": risky,
            "recovery_in_progress": row.get("recovery_in_progress"),
            "recovery_probability": row.get("recovery_probability"),
            "has_recovery_catalyst": row.get("has_recovery_catalyst"),
            "study_note": row.get("study_note"),
            "score_letter": scored.letter,
            "r_multiple": scored.r_multiple,
            "tranche_index": tranche,
            "review_required": review,
            "strategy": "hv_dip_qt",
            "currency": "USD",
            "catalyst": catalyst,
        },
        price_explanation=(
            f"NM Quick Target {scored.letter}: dip {row['dip_pct']:.1f}% "
            f"entrada {row['entry']:.2f} stop {row['stop']:.2f} "
            f"alvo {row['target']:.2f} {qty} lotes"
            + (" [CATALISTA]" if catalyst else "")
            + (" [RISKY-RECOVERY]" if risky else "")
            + (" [REVIEW]" if review else "")
        ),
        rule_version=3,
        proposed_amount_brl=amount,
        expires_at=expires_at,
    )
    db.add(suggestion)
    db.flush()

    # The desk just asserted this setup is worth capital. Record the claim while
    # the outcome is still unknown — a suggestion without a forecast is a trade
    # the system can never learn from.
    record_forecast(
        db,
        source="hv_dip",
        kind="quick_target",
        ticker=ticker,
        # The 0-99 score is not a probability; it is the raw score Platt is
        # meant to map. Normalising keeps it in range without pretending.
        p_pred=float(scored.numeric_score or 0.0) / 100.0,
        horizon_days=int(settings.hv_dip_qt_max_hold_days or 3),
        ref_id=str(suggestion.id),
        features={
            "direction": "up",
            "raw_score": float(scored.numeric_score or 0.0),
            "letter": scored.letter,
            "dip_pct": row.get("dip_pct"),
            "atr_pct": row.get("atr_pct"),
            "catalyst": bool(catalyst),
            "risky_recovery": bool(risky),
            "auto": bool(auto),
            "review_required": bool(review),
        },
    )

    if auto:
        from app.services.desk_gate import DeskIntent, apply_intent

        verdict = apply_intent(
            db,
            DeskIntent(
                account=account,
                kind=StrategyKind.hv_dip,
                ticker=ticker,
                notional=amount,
                price=entry,
                score=float(scored.numeric_score or 0),
                r_multiple=scored.r_multiple,
                quantity=float(qty),
                explanation=suggestion.price_explanation,
                metrics={"quantity": qty, "amount": amount, "hv_dip": True},
            ),
        )
        if verdict.queued:
            logger.info("HV Dip auto-buy queued for %s", ticker)
            if verdict.decision is not None:
                verdict.decision.suggestion_id = suggestion.id
        elif verdict.allow:
            try:
                with db.begin_nested():
                    create_order_from_suggestion(db, suggestion, acted_by_user_id=None)
            except ValueError as exc:
                suggestion.status = SuggestionStatus.pending
                suggestion.acted_at = None
                suggestion.review_reason = _append_reason(
                    suggestion.review_reason, f"Auto-buy bloqueado: {exc}"
                )
                logger.info("HV Dip auto-buy blocked for %s: %s", ticker, exc)
        else:
            suggestion.status = SuggestionStatus.pending
            suggestion.acted_at = None
            suggestion.review_reason = _append_reason(
                suggestion.review_reason, f"desk_gate: {verdict.reason}"
            )
            logger.info("HV Dip auto-buy gate deny %s: %s", ticker, verdict.reason)
    if catalyst:
        ev = row.get("news_event")
        if ev is not None:
            ev.used_in_suggestion = True

    try:
        notify_suggestion(db, suggestion)
    except Exception:
        logger.exception("notify hv_dip failed")
    return suggestion


def suggest_more_for_ticker(
    db: Session,
    account: InvestmentAccount,
    ticker: str,
) -> Suggestion:
    """"Comprar mais" from the open positions list: re-analyze a held ticker and
    emit a new pending suggestion (tranche N+1) through the normal review/auto-buy
    flow. Raises ValueError when the setup no longer qualifies or the cap is hit.
    """
    ticker = ticker.upper()
    if _pending_hv(db, account.id, ticker):
        raise ValueError(f"{ticker} já tem sugestão pendente")

    max_tranche = 0
    open_rows = (
        db.query(Position)
        .filter(
            Position.account_id == account.id,
            Position.ticker == ticker,
            Position.strategy_kind == StrategyKind.hv_dip,
            Position.status == PositionStatus.open,
        )
        .all()
    )
    for p in open_rows:
        max_tranche = max(max_tranche, int(getattr(p, "tranche_index", 1) or 1))
    if max_tranche == 0:
        max_tranche = 1
    tranche = max_tranche + 1
    if tranche > int(settings.hv_dip_max_tranches):
        raise ValueError(
            f"Teto de {settings.hv_dip_max_tranches} tranches atingido para {ticker}"
        )

    client = MarketDataClient()
    bars = client.fetch_daily_bars(ticker)
    prices = client.fetch_last_prices([ticker])
    row = build_hv_dip_setup(
        ticker, bars, last_price=prices.get(ticker), **active_thresholds(db)
    )
    if row is None:
        raise ValueError(
            f"{ticker} não passa nos filtros de queda/liquidez agora "
            "(dip mínimo não atingido ou sem histórico de barras). "
            "Tente quando a queda voltar a se aprofundar."
        )

    _apply_catalysts(db, [row], {ticker: bars})

    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.hv_dip_suggestion_ttl_hours)
    suggestion = _create_suggestion(
        db, account, row, tranche=tranche, expires_at=expires_at
    )
    if suggestion is None:
        raise ValueError(f"{ticker}: caixa/limites insuficientes para nova tranche")
    db.commit()
    return suggestion
