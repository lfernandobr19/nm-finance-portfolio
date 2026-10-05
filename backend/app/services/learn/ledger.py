"""Forecast ledger: record every asserted probability, score it against reality.

The desk constantly produces numbers that *look* like probabilities (hv_dip
scores, study ``p_higher``, news confidence). Until they are written down before
the outcome is known and graded afterwards, "the system is getting smarter" is
unfalsifiable. This module is that write-ahead log.

Scoring uses the Brier score, ``(p - y)^2``: lower is better, and the trivial
"always say 50%" baseline scores 0.25. Anything above that is worse than
admitting ignorance.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

from sqlalchemy.orm import Session

from app.domain.models import ForecastLedger

logger = logging.getLogger("fiidesk.learn.ledger")

SOURCES = frozenset({"hv_dip", "day_trade", "studies", "news", "mega_rotation", "judgment"})

# Calendar days of slack added on top of the horizon so a forecast is only
# graded once the market has actually had that many sessions to play out
# (weekends and holidays would otherwise resolve it early against stale bars).
_CALENDAR_SLACK = 1.6

# How long past its due date a forecast may stay unresolvable before being
# abandoned, so the pending queue cannot grow without bound.
_STALE_GRACE = timedelta(days=30)


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def brier_of(p_pred: float, outcome: bool) -> float:
    y = 1.0 if outcome else 0.0
    return (float(p_pred) - y) ** 2


def record_forecast(
    db: Session,
    *,
    source: str,
    kind: str,
    ticker: str,
    p_pred: float,
    horizon_days: int = 1,
    features: dict[str, Any] | None = None,
    ref_id: str | None = None,
    now: datetime | None = None,
) -> ForecastLedger:
    """Write an asserted probability before the outcome is known.

    ``p_pred`` is clamped to [0, 1] rather than rejected: callers derive it from
    scores and ratios, and a forecast that never gets recorded is worse than one
    recorded at the boundary.
    """
    if source not in SOURCES:
        raise ValueError(f"unknown forecast source: {source}")
    now = _as_utc(now) or datetime.now(timezone.utc)
    horizon = max(1, int(horizon_days))
    row = ForecastLedger(
        source=source,
        kind=kind,
        ticker=(ticker or "").upper(),
        ref_id=ref_id,
        p_pred=min(1.0, max(0.0, float(p_pred))),
        horizon_days=horizon,
        features=dict(features or {}),
        # Set explicitly rather than left to the column server_default: this is
        # the anchor the forward return is measured from, so it has to be the
        # decision instant and come from the same clock as resolve_after.
        created_at=now,
        resolve_after=now + timedelta(days=horizon * _CALENDAR_SLACK),
    )
    db.add(row)
    return row


def record_forecast_once(
    db: Session,
    *,
    ref_id: str,
    source: str,
    **kwargs: Any,
) -> ForecastLedger | None:
    """``record_forecast`` guarded by ``ref_id``, for producers that re-run.

    Studies recompute every cycle and would otherwise write a near-identical
    forecast each hour, inflating the sample count with correlated rows and
    making the Brier look more certain than the evidence warrants.
    """
    exists = (
        db.query(ForecastLedger.id)
        .filter(ForecastLedger.source == source, ForecastLedger.ref_id == ref_id)
        .first()
    )
    if exists is not None:
        return None
    return record_forecast(db, source=source, ref_id=ref_id, **kwargs)


def resolve_forecast(
    db: Session,
    row: ForecastLedger,
    *,
    outcome: bool,
    outcome_value: float | None = None,
    now: datetime | None = None,
) -> float | None:
    """Grade one forecast. Idempotent: an already-resolved row is left alone."""
    if row.resolved_at is not None:
        return row.brier
    row.outcome = bool(outcome)
    row.outcome_value = None if outcome_value is None else float(outcome_value)
    row.brier = brier_of(row.p_pred, outcome)
    row.resolved_at = _as_utc(now) or datetime.now(timezone.utc)
    return row.brier


def abandon_forecast(
    db: Session,
    row: ForecastLedger,
    *,
    reason: str,
    now: datetime | None = None,
) -> None:
    """Close a forecast whose outcome can never be observed.

    Scoring it either way would be a lie: the trade expired unfilled, the signal
    was swept, the ticker stopped reporting. Marking it resolved with a NULL
    outcome keeps it out of every score (``resolved_pairs`` and
    ``ledger_summary`` both skip NULL outcomes) while stopping it from being
    re-scanned forever.
    """
    if row.resolved_at is not None:
        return
    row.outcome = None
    row.brier = None
    row.resolved_at = _as_utc(now) or datetime.now(timezone.utc)
    features = dict(row.features or {})
    features["abandoned"] = reason
    row.features = features


def due_forecasts(
    db: Session,
    *,
    now: datetime | None = None,
    limit: int = 200,
    source: str | None = None,
) -> list[ForecastLedger]:
    now = _as_utc(now) or datetime.now(timezone.utc)
    q = (
        db.query(ForecastLedger)
        .filter(ForecastLedger.resolved_at.is_(None))
        .filter(ForecastLedger.resolve_after <= now)
    )
    if source is not None:
        q = q.filter(ForecastLedger.source == source)
    return q.order_by(ForecastLedger.resolve_after.asc()).limit(limit).all()


def forward_return(bars: Iterable[Any], anchor: datetime, sessions: int) -> float | None:
    """Close-to-close return over ``sessions`` sessions strictly after ``anchor``.

    Returns ``None`` when the history does not yet reach that far, which keeps
    the forecast pending instead of grading it against a bar that never came.
    """
    anchor = _as_utc(anchor)
    if anchor is None:
        return None
    dated = []
    for b in bars:
        d = getattr(b, "date", None)
        if d is None:
            continue
        dated.append((b, d if d.tzinfo else d.replace(tzinfo=timezone.utc)))
    if not dated:
        return None
    dated.sort(key=lambda x: x[1])

    anchor_day = anchor.date()
    base_close: float | None = None
    after: list[Any] = []
    for bar, dt in dated:
        if dt.date() <= anchor_day:
            base_close = float(bar.close)
            continue
        after.append(bar)
    if base_close is None or base_close <= 0 or len(after) < sessions:
        return None
    end_close = float(after[sessions - 1].close)
    return (end_close - base_close) / base_close


def _direction_outcome(row: ForecastLedger, ret: float) -> bool:
    """Did the move go the way the forecast claimed?

    ``features['direction']`` defaults to ``up`` because every current producer
    asserts "this will trade higher": hv_dip scores an entry, studies report
    ``p_higher``, bullish news implies upside.
    """
    direction = str((row.features or {}).get("direction") or "up").lower()
    return ret < 0 if direction == "down" else ret > 0


def _resolve_day_trade(db: Session, row: ForecastLedger) -> tuple[bool, float] | str | None:
    """Day trade outcomes are observed, not inferred.

    ``update_open_signals`` already simulated the exit against real bars, so the
    signal itself carries the answer — far more faithful than asking whether the
    daily close drifted up, which is a different question entirely.

    Returns the outcome, the string ``"abandon"`` when the signal was swept
    without an exit, or ``None`` to stay pending.
    """
    from app.domain.models import DayTradeSignal, DayTradeSignalStatus

    if not row.ref_id:
        return "abandon"
    sig = (
        db.query(DayTradeSignal).filter(DayTradeSignal.id == row.ref_id).first()
    )
    if sig is None:
        return "abandon"
    if sig.status == DayTradeSignalStatus.expired:
        # Swept by the stale-open sweep: no exit was ever observed, so scoring it
        # as a loss would invent data.
        return "abandon"
    if sig.status != DayTradeSignalStatus.closed or sig.simulated_pnl_usd is None:
        return None
    pnl = float(sig.simulated_pnl_usd)
    return (pnl > 0, pnl)


def _resolve_trade_ref(
    db: Session, row: ForecastLedger
) -> tuple[bool, float] | str | None:
    """Grade by realized PnL when ref_id is a closed position or filled order.

    Returns ``(outcome, pnl)``, ``"pending_open"`` while the position is still
    open, or ``None`` to fall through to forward-return.
    """
    if not row.ref_id:
        return None
    from app.domain.models import (
        DeskDecision,
        Order,
        Position,
        PositionStatus,
    )

    pos: Position | None = None
    try:
        pos = db.get(Position, row.ref_id)
    except Exception:
        pos = None
    if pos is None:
        try:
            order = db.get(Order, row.ref_id)
        except Exception:
            order = None
        if order is not None and getattr(order, "position_id", None):
            try:
                pos = db.get(Position, order.position_id)
            except Exception:
                pos = None
    if pos is None:
        try:
            dec = db.get(DeskDecision, row.ref_id)
        except Exception:
            dec = None
        if dec is not None:
            try:
                pos = (
                    db.query(Position)
                    .filter(
                        Position.account_id == dec.account_id,
                        Position.ticker == row.ticker,
                    )
                    .order_by(Position.opened_at.desc())
                    .first()
                )
            except Exception:
                pos = None
            if pos is not None and not isinstance(pos, Position):
                pos = None
    if pos is None or not isinstance(pos, Position):
        return None
    status = pos.status.value if hasattr(pos.status, "value") else str(pos.status)
    if status != PositionStatus.closed.value and status != "closed":
        return "pending_open"
    pnl = float(pos.realized_pnl_brl or 0.0)
    return (pnl > 0, pnl)


def resolve_pending(
    db: Session,
    *,
    now: datetime | None = None,
    limit: int = 200,
    bars_for: Callable[[str], list[Any]] | None = None,
) -> dict[str, Any]:
    """Grade every forecast whose horizon has elapsed.

    ``bars_for`` is injected so tests can run without network; in production it
    defaults to the shared daily-bar client, whose cache the rest of the desk
    already warms.
    """
    rows = due_forecasts(db, now=now, limit=limit)
    if not rows:
        return {"resolved": 0, "pending": 0, "skipped": 0, "abandoned": 0}

    if bars_for is None:
        from app.services.market_data import MarketDataClient

        client = MarketDataClient()
        cache: dict[str, list[Any]] = {}

        def bars_for(ticker: str) -> list[Any]:  # noqa: F811
            if ticker not in cache:
                try:
                    cache[ticker] = client.fetch_daily_bars(ticker)
                except Exception:
                    logger.exception("ledger bars failed for %s", ticker)
                    cache[ticker] = []
            return cache[ticker]

    resolved = 0
    skipped = 0
    abandoned = 0
    for row in rows:
        if row.source == "day_trade":
            verdict = _resolve_day_trade(db, row)
            if verdict is None:
                skipped += 1
                continue
            if verdict == "abandon":
                abandon_forecast(db, row, reason="signal_without_exit", now=now)
                abandoned += 1
                continue
            outcome, value = verdict
            resolve_forecast(db, row, outcome=outcome, outcome_value=value, now=now)
            resolved += 1
            continue

        trade = _resolve_trade_ref(db, row)
        if trade == "pending_open":
            skipped += 1
            continue
        if isinstance(trade, tuple):
            outcome, value = trade
            resolve_forecast(
                db, row, outcome=outcome, outcome_value=value, now=now
            )
            resolved += 1
            continue

        bars = bars_for(row.ticker)
        ret = forward_return(bars, row.created_at, int(row.horizon_days))
        if ret is None:
            # Long past due and still unpriceable — a delisted symbol, a market
            # this client cannot quote. Close it out so the pending queue stays
            # bounded instead of being rescanned forever.
            if _as_utc(row.resolve_after) < (_as_utc(now) or datetime.now(timezone.utc)) - _STALE_GRACE:
                abandon_forecast(db, row, reason="unresolvable_no_bars", now=now)
                abandoned += 1
            else:
                skipped += 1
            continue
        resolve_forecast(
            db,
            row,
            outcome=_direction_outcome(row, ret),
            outcome_value=ret,
            now=now,
        )
        resolved += 1

    if resolved or skipped or abandoned:
        logger.info(
            "ledger resolve resolved=%d skipped=%d abandoned=%d",
            resolved, skipped, abandoned,
        )
    return {
        "resolved": resolved,
        "pending": len(rows) - resolved - abandoned,
        "skipped": skipped,
        "abandoned": abandoned,
    }


def resolved_pairs(
    db: Session,
    *,
    source: str | None = None,
    kind: str | None = None,
    limit: int = 5000,
) -> list[tuple[float, bool]]:
    """``(p_pred, outcome)`` pairs, the input shape every calibration tool wants."""
    q = db.query(ForecastLedger).filter(ForecastLedger.resolved_at.is_not(None))
    if source is not None:
        q = q.filter(ForecastLedger.source == source)
    if kind is not None:
        q = q.filter(ForecastLedger.kind == kind)
    rows = q.order_by(ForecastLedger.resolved_at.desc()).limit(limit).all()
    return [(float(r.p_pred), bool(r.outcome)) for r in rows if r.outcome is not None]


def ledger_summary(db: Session) -> dict[str, Any]:
    """Per-source assertiveness, for the pulse and the calibration gate."""
    rows = db.query(ForecastLedger).all()
    by_source: dict[str, dict[str, Any]] = {}
    for r in rows:
        b = by_source.setdefault(
            r.source, {"n": 0, "resolved": 0, "hits": 0, "brier_sum": 0.0}
        )
        b["n"] += 1
        if r.resolved_at is None or r.outcome is None:
            continue
        b["resolved"] += 1
        if r.outcome:
            b["hits"] += 1
        if r.brier is not None:
            b["brier_sum"] += float(r.brier)

    empty = {"n": 0, "resolved": 0, "hits": 0, "brier_sum": 0.0}
    out: dict[str, Any] = {}
    sources = list(SOURCES) + [s for s in by_source if s not in SOURCES]
    for source in sources:
        b = by_source.get(source, empty)
        n = b["resolved"]
        out[source] = {
            "n": b["n"],
            "resolved": n,
            "hit_rate": round(b["hits"] / n, 4) if n else None,
            "brier": round(b["brier_sum"] / n, 4) if n else None,
        }
    return out


__all__ = [
    "SOURCES",
    "brier_of",
    "record_forecast",
    "record_forecast_once",
    "resolve_forecast",
    "abandon_forecast",
    "due_forecasts",
    "forward_return",
    "resolve_pending",
    "resolved_pairs",
    "ledger_summary",
]
