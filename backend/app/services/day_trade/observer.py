"""Evaluate rules and persist simulated day trade signals."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.models import (
    AccountCurrency,
    DayTradeSide,
    DayTradeSignal,
    DayTradeSignalStatus,
    InvestmentAccount,
)
from app.services.day_trade.bars import IntradayBar
from app.services.day_trade.configs import get_active_params
from app.services.day_trade.gating import compute_gates, rule_is_gated, ticker_is_gated
from app.services.day_trade.regime import classify_regime
from app.services.day_trade.risk import (
    concurrent_exceeded,
    daily_loss_exceeded,
    expire_stale_signals,
    is_time_window_ok,
)
from app.services.day_trade.rules import RuleSignal, build_evaluators
from app.services.learn.ledger import record_forecast
from app.services.market_hours import us_session_date
from app.services.studies.apply import day_trade_rule_notes

logger = logging.getLogger("fiidesk.day_trade.observer")


def _valid_bar(bar: IntradayBar) -> bool:
    vals = (bar.open, bar.high, bar.low, bar.close, bar.volume)
    return all(
        isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in vals
    )


def _session_bars(bars: list[IntradayBar], session_date) -> list[IntradayBar]:
    return [
        b
        for b in bars
        if _valid_bar(b) and us_session_date(b.ts) == session_date
    ]


def _simulate_exit_pnl(side: str, entry: float, stop: float, target: float, bar: IntradayBar) -> tuple[str, float]:
    if side == "long":
        if bar.low <= stop:
            return DayTradeSignalStatus.closed.value, stop - entry
        if bar.high >= target:
            return DayTradeSignalStatus.closed.value, target - entry
    else:
        if bar.high >= stop:
            return DayTradeSignalStatus.closed.value, entry - stop
        if bar.low <= target:
            return DayTradeSignalStatus.closed.value, entry - target
    return DayTradeSignalStatus.open.value, 0.0


def _signal_exists(
    db: Session,
    *,
    account_id: str,
    session_date,
    ticker: str,
    rule_id: str,
) -> bool:
    # One signal per (ticker, rule, session) regardless of open/closed status.
    # Checking only `open` lets a rule re-fire on the same forming candle after
    # the simulated exit closes the signal, producing duplicate spam.
    row = (
        db.query(DayTradeSignal)
        .filter(
            DayTradeSignal.account_id == account_id,
            DayTradeSignal.session_date == session_date,
            DayTradeSignal.ticker == ticker,
            DayTradeSignal.rule_id == rule_id,
        )
        .first()
    )
    return row is not None


def _rule_prior(db: Session, account_id: str, rule_id: str) -> float:
    """Laplace-smoothed historical win rate for a rule: the desk's implicit belief.

    ``(wins + 1) / (n + 2)`` so a rule with no history lands on 0.5 instead of
    0 or 1, and a single lucky trade cannot assert 100%.
    """
    rows = (
        db.query(DayTradeSignal)
        .filter(
            DayTradeSignal.account_id == account_id,
            DayTradeSignal.rule_id == rule_id,
            DayTradeSignal.status == DayTradeSignalStatus.closed,
        )
        .all()
    )
    wins = sum(1 for r in rows if (r.simulated_pnl_usd or 0) > 0)
    return (wins + 1.0) / (len(rows) + 2.0)


def _persist_signal(
    db: Session,
    *,
    account_id: str,
    session_date,
    ticker: str,
    signal: RuleSignal,
    study_note: str | None = None,
) -> DayTradeSignal | None:
    if _signal_exists(
        db,
        account_id=account_id,
        session_date=session_date,
        ticker=ticker,
        rule_id=signal.rule_id,
    ):
        return None
    row = DayTradeSignal(
        account_id=account_id,
        session_date=session_date,
        ticker=ticker.upper(),
        rule_id=signal.rule_id,
        side=DayTradeSide(signal.side),
        entry_price=signal.entry_price,
        stop_price=signal.stop_price,
        target_price=signal.target_price,
        status=DayTradeSignalStatus.open,
        # The study's verdict rides with the sample, so a weak pattern is
        # visible wherever the signal is read instead of only in a JSON file.
        metrics={**signal.metrics, "study_note": study_note} if study_note
        else signal.metrics,
    )
    db.add(row)
    db.flush()

    # Record the claim before the session plays out. Resolution reads this
    # signal's simulated exit back, so the outcome is observed rather than
    # inferred from a daily close.
    record_forecast(
        db,
        source="day_trade",
        kind=signal.rule_id,
        ticker=ticker,
        p_pred=_rule_prior(db, account_id, signal.rule_id),
        horizon_days=1,
        ref_id=str(row.id),
        features={
            "direction": "down" if signal.side == "short" else "up",
            "rule_id": signal.rule_id,
            "side": signal.side,
            "entry": float(signal.entry_price),
            "stop": float(signal.stop_price),
            "target": float(signal.target_price),
        },
    )

    logger.info(
        "Day trade signal %s %s %s %s entry=%.2f",
        signal.rule_id,
        ticker,
        signal.side,
        row.id,
        signal.entry_price,
    )
    return row


def update_open_signals(db: Session, *, account_id: str, ticker: str, bar: IntradayBar) -> int:
    session_date = us_session_date(bar.ts)
    open_rows = (
        db.query(DayTradeSignal)
        .filter(
            DayTradeSignal.account_id == account_id,
            DayTradeSignal.session_date == session_date,
            DayTradeSignal.ticker == ticker.upper(),
            DayTradeSignal.status == DayTradeSignalStatus.open,
        )
        .all()
    )
    closed = 0
    for row in open_rows:
        status, pnl = _simulate_exit_pnl(
            row.side,
            float(row.entry_price),
            float(row.stop_price),
            float(row.target_price),
            bar,
        )
        if status == DayTradeSignalStatus.closed.value:
            row.status = DayTradeSignalStatus.closed
            row.simulated_pnl_usd = round(pnl, 4)
            row.closed_at = datetime.now(timezone.utc)
            closed += 1
    return closed


def run_observer_for_bar(
    db: Session,
    *,
    account_id: str,
    ticker: str,
    bars: list[IntradayBar],
) -> list[DayTradeSignal]:
    if len(bars) < 2:
        logger.debug("Observer skip %s: bars=%d", ticker, len(bars))
        return []
    session_date = us_session_date(bars[-1].ts)
    clean = _session_bars(bars, session_date)
    if len(clean) < 2:
        logger.debug("Observer skip %s: clean bars=%d", ticker, len(clean))
        return []
    update_open_signals(db, account_id=account_id, ticker=ticker, bar=clean[-1])

    # --- Learn loop hooks: risk, regime, gating, active params ---
    settings = get_settings()
    if not is_time_window_ok(clean[-1].ts):
        logger.debug("Observer skip %s: outside time window", ticker)
        return []
    if concurrent_exceeded(db, account_id, session_date):
        logger.debug("Observer skip %s: max concurrent signals", ticker)
        return []
    if daily_loss_exceeded(db, account_id, session_date):
        logger.debug("Observer skip %s: daily loss limit", ticker)
        return []
    regime = classify_regime(clean)
    gates = compute_gates(db, account_id)
    params = get_active_params(db)
    evaluators = build_evaluators(params)
    study_notes = day_trade_rule_notes()

    created: list[DayTradeSignal] = []
    fired: list[str] = []
    for evaluate in evaluators:
        rule_id = getattr(evaluate, "rule_id", None)
        if rule_id is None:
            continue
        if rule_is_gated(gates, rule_id) or ticker_is_gated(gates, ticker):
            continue
        if rule_id == "vwap_reclaim" and regime.regime != "trend":
            continue
        signal = evaluate(clean)
        if not signal:
            continue
        fired.append(rule_id)
        row = _persist_signal(
            db,
            account_id=account_id,
            session_date=session_date,
            ticker=ticker,
            signal=signal,
            study_note=study_notes.get(rule_id),
        )
        if row:
            created.append(row)
    logger.info(
        "Observer %s bars=%d clean=%d regime=%s rules_fired=%s signals_new=%d",
        ticker,
        len(bars),
        len(clean),
        regime.regime,
        fired or "none",
        len(created),
    )
    return created


def run_observer_for_us_accounts(db: Session, *, ticker: str, bars: list[IntradayBar]) -> int:
    accounts = (
        db.query(InvestmentAccount)
        .filter(InvestmentAccount.currency == AccountCurrency.USD)
        .all()
    )
    # Account-agnostic and idempotent: a no-op once the session is clean, but it
    # self-heals after a restart or a skipped session.
    if bars:
        expire_stale_signals(db, session_date=us_session_date(bars[-1].ts))
    total = 0
    for account in accounts:
        created = run_observer_for_bar(db, account_id=account.id, ticker=ticker, bars=bars)
        total += len(created)
    return total
