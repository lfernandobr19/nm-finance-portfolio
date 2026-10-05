"""Deterministic USD-paper capital orchestrator (policy gate).

Engines propose a DeskIntent; evaluate_gate decides allow / deny / queue.
Deny never creates Suggestion or Order. Exits do not pass through this module.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.models import (
    AccountCurrency,
    AssetClass,
    DeskBudgetConfig,
    DeskDecision,
    ExecutionMode,
    InvestmentAccount,
    Order,
    OrderSide,
    OrderStatus,
    Position,
    PositionExitReason,
    PositionStatus,
    StrategyKind,
    Suggestion,
    SuggestionStatus,
)

logger = logging.getLogger("fiidesk.desk_gate")

_USD_AUTO_KINDS = frozenset(
    {StrategyKind.hv_dip, StrategyKind.index_core, StrategyKind.mega_rotation}
)
_TACTICAL_KINDS = frozenset({StrategyKind.hv_dip, StrategyKind.mega_rotation})
_DEFAULT_SLICES = {
    "hv_dip": 0.4,
    "index_core": 0.4,
    "mega_rotation": 0.0,
}


@dataclass
class DeskIntent:
    account: InvestmentAccount
    kind: StrategyKind
    ticker: str
    notional: float
    price: float
    score: float = 0.0
    r_multiple: float | None = None
    quantity: float | None = None
    explanation: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class GateVerdict:
    allow: bool
    reason: str
    enforce: bool
    queued: bool = False
    shadow: bool = False
    cash_before: float = 0.0
    decision: DeskDecision | None = None


def parse_slices(raw: str | None, learned: dict[str, Any] | None = None) -> dict[str, float]:
    out = dict(_DEFAULT_SLICES)
    if learned:
        for k, v in learned.items():
            try:
                out[str(k)] = max(0.0, float(v))
            except (TypeError, ValueError):
                continue
    text = (raw or "").strip()
    if not text:
        return out
    for part in text.split(","):
        if "=" not in part:
            continue
        key, val = part.split("=", 1)
        key = key.strip()
        try:
            out[key] = max(0.0, float(val.strip()))
        except (TypeError, ValueError):
            continue
    return out


def _kind_key(kind: StrategyKind | str) -> str:
    return kind.value if isinstance(kind, StrategyKind) else str(kind)


def _is_usd_paper(account: InvestmentAccount) -> bool:
    ccy = getattr(account, "currency", None)
    ccy_val = ccy.value if hasattr(ccy, "value") else str(ccy or "BRL")
    mode = getattr(account, "execution_mode", None)
    mode_val = mode.value if hasattr(mode, "value") else str(mode or "")
    return str(ccy_val).upper().endswith("USD") and mode_val == ExecutionMode.paper.value


def _is_usd_live(account: InvestmentAccount) -> bool:
    ccy = getattr(account, "currency", None)
    ccy_val = ccy.value if hasattr(ccy, "value") else str(ccy or "BRL")
    mode = getattr(account, "execution_mode", None)
    mode_val = mode.value if hasattr(mode, "value") else str(mode or "")
    return str(ccy_val).upper().endswith("USD") and mode_val == ExecutionMode.live.value


def _safe_count(result: Any) -> int:
    if isinstance(result, bool):
        return int(result)
    if isinstance(result, (int, float)):
        return int(result)
    return 0


def _safe_rows(result: Any) -> list:
    if isinstance(result, list):
        return result
    if isinstance(result, tuple):
        return list(result)
    return []


def _cash_usd(account: InvestmentAccount) -> float:
    cash = float(getattr(account, "cash_usd", None) or 0)
    equity = float(getattr(account, "hv_dip_equity_usd", None) or 0)
    return cash if cash > 0 else equity


def _open_positions(db: Session, account_id: str, kind: StrategyKind | None = None) -> list[Position]:
    try:
        q = db.query(Position).filter(
            Position.account_id == account_id,
            Position.status == PositionStatus.open,
        )
        if kind is not None:
            q = q.filter(Position.strategy_kind == kind)
        return _safe_rows(q.all())
    except Exception:
        return []


def deployed_kind_usd(db: Session, account_id: str, kind: StrategyKind) -> float:
    rows = _open_positions(db, account_id, kind)
    return float(sum(float(p.entry_price) * float(p.quantity) for p in rows))


def account_equity_usd(db: Session, account: InvestmentAccount) -> float:
    cash = _cash_usd(account)
    invested = float(
        sum(float(p.entry_price) * float(p.quantity) for p in _open_positions(db, account.id))
    )
    return cash + invested


def _slice_pct(account: InvestmentAccount, kind: StrategyKind, slices: dict[str, float]) -> float:
    """Budget share for this account/kind.

    The dedicated mega-rotation paper account is a single-strategy pool. A global
    `mega_rotation=0` slice must not starve it — that is how NVDA dipped 5%+ and
    still never bought.
    """
    settings = get_settings()
    rot_id = (settings.mega_rotation_account_id or "").strip()
    if (
        rot_id
        and str(account.id) == rot_id
        and _kind_key(kind) == "mega_rotation"
    ):
        return 1.0
    return float(slices.get(_kind_key(kind), 0.0) or 0.0)


def remaining_slice_usd(db: Session, account: InvestmentAccount, kind: StrategyKind) -> float:
    """USD still available in this kind's budget slice (equity × slice − deployed)."""
    settings = get_settings()
    equity = account_equity_usd(db, account)
    slices = parse_slices(settings.desk_gate_usd_budgets, _learned_slices(db))
    cap = equity * _slice_pct(account, kind, slices)
    deployed = deployed_kind_usd(db, account.id, kind)
    return max(0.0, cap - deployed)


def _learned_slices(db: Session) -> dict[str, Any] | None:
    try:
        row = (
            db.query(DeskBudgetConfig)
            .filter(DeskBudgetConfig.is_active.is_(True))
            .order_by(DeskBudgetConfig.version.desc())
            .first()
        )
    except Exception:
        return None
    if row is None or not isinstance(getattr(row, "slices", None), dict):
        return None
    return dict(row.slices)


def _peak_and_touch(db: Session, equity: float) -> float:
    try:
        row = (
            db.query(DeskBudgetConfig)
            .filter(DeskBudgetConfig.is_active.is_(True))
            .order_by(DeskBudgetConfig.version.desc())
            .first()
        )
    except Exception:
        return equity
    if row is None:
        return equity
    peak = float(getattr(row, "peak_equity_usd", 0) or 0)
    if equity > peak:
        try:
            row.peak_equity_usd = equity
        except Exception:
            pass
        return equity
    return peak if peak > 0 else equity


def spy_regime(db: Session | None = None) -> str:
    """trend | chop | warmup | unknown — uses day_trade SPY bars when present."""
    settings = get_settings()
    ticker = (settings.desk_gate_regime_ticker or "SPY").upper()
    try:
        from app.services.day_trade.bars import IntradayBar
        from app.services.day_trade.cache import DayTradeBarCache
        from app.services.day_trade.regime import classify_regime

        bars = DayTradeBarCache().get_bars(ticker)
        if not bars and db is not None:
            from app.domain.models import DayTradeBar

            rows = _safe_rows(
                db.query(DayTradeBar)
                .filter(DayTradeBar.ticker == ticker)
                .order_by(DayTradeBar.ts.asc())
                .all()
            )
            bars = [
                IntradayBar(
                    ts=r.ts,
                    open=float(r.open),
                    high=float(r.high),
                    low=float(r.low),
                    close=float(r.close),
                    volume=float(r.volume or 0),
                )
                for r in rows
            ]
        if not bars:
            return "unknown"
        return classify_regime(bars).regime
    except Exception:
        logger.exception("desk_gate regime lookup failed")
        return "unknown"


_WORKING_STATUSES = (
    OrderStatus.queued,
    OrderStatus.submitted,
    OrderStatus.awaiting_broker,
)


def working_order(
    db: Session,
    account_id: str,
    ticker: str,
    kind: StrategyKind | str | None = None,
    *,
    side: OrderSide = OrderSide.buy,
) -> Order | None:
    """Open working buy (queued/submitted/awaiting_broker) for ticker+account+kind."""
    try:
        q = db.query(Order).filter(
            Order.account_id == account_id,
            Order.ticker == (ticker or "").upper(),
            Order.side == side,
            Order.status.in_(_WORKING_STATUSES),
        )
        if kind is not None:
            q = q.filter(Order.strategy_kind == kind)
        row = q.order_by(Order.created_at.desc()).first()
    except Exception:
        return None
    return row if isinstance(row, Order) else None


def _recent_auto_buys(db: Session, account_id: str, window_s: int) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(1, window_s))
    try:
        n = (
            db.query(Order)
            .filter(
                Order.account_id == account_id,
                Order.side == OrderSide.buy,
                Order.strategy_kind.in_(tuple(_USD_AUTO_KINDS)),
                Order.status.in_(
                    (
                        OrderStatus.queued,
                        OrderStatus.submitted,
                        OrderStatus.awaiting_broker,
                        OrderStatus.filled,
                    )
                ),
                Order.created_at >= cutoff,
            )
            .count()
        )
        return _safe_count(n)
    except Exception:
        return 0


def _cooldown_active(db: Session, account_id: str, ticker: str, hours: float) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(0.0, hours))
    try:
        n = (
            db.query(Position)
            .filter(
                Position.account_id == account_id,
                Position.ticker == ticker.upper(),
                Position.status == PositionStatus.closed,
                Position.closed_at.is_not(None),
                Position.closed_at >= cutoff,
            )
            .count()
        )
        return _safe_count(n) > 0
    except Exception:
        return False


def _stoploss_count(db: Session, account_id: str, hours: float) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(0.0, hours))
    try:
        rows = _safe_rows(
            db.query(Position)
            .filter(
                Position.account_id == account_id,
                Position.status == PositionStatus.closed,
                Position.exit_reason == PositionExitReason.stop,
                Position.closed_at.is_not(None),
                Position.closed_at >= cutoff,
            )
            .all()
        )
        return sum(1 for p in rows if (p.r_multiple_realized is not None and float(p.r_multiple_realized) < 0))
    except Exception:
        return 0


def _ticker_expectancy(db: Session, account_id: str, ticker: str, min_n: int) -> float | None:
    try:
        rows = _safe_rows(
            db.query(Position)
            .filter(
                Position.account_id == account_id,
                Position.ticker == ticker.upper(),
                Position.status == PositionStatus.closed,
                Position.r_multiple_realized.is_not(None),
            )
            .order_by(Position.closed_at.desc())
            .limit(20)
            .all()
        )
    except Exception:
        return None
    rs = [float(p.r_multiple_realized) for p in rows if p.r_multiple_realized is not None]
    if len(rs) < max(1, min_n):
        return None
    return sum(rs) / len(rs)


def _deny_reason(intent: DeskIntent, db: Session, *, for_allocate: bool) -> str | None:
    settings = get_settings()
    account = intent.account
    if bool(getattr(account, "automation_paused", False)):
        return "paused"
    if intent.price <= 0 or intent.notional <= 0:
        return "invalid_notional"
    # Whole-share names: ticket must cover 1 share in cents. Sub-cent quote
    # vs rounded notional is not "unaffordable" — that was blocking NVDA.
    if intent.kind in _TACTICAL_KINDS and round(intent.price, 2) > round(intent.notional, 2):
        return "unaffordable"

    cash = _cash_usd(account)
    equity = account_equity_usd(db, account)
    floor_pct = float(getattr(account, "hv_dip_cash_floor_pct", 30.0) or 30.0)
    floor_cash = equity * (floor_pct / 100.0)

    slices = parse_slices(settings.desk_gate_usd_budgets, _learned_slices(db))
    slice_pct = _slice_pct(account, intent.kind, slices)
    cap = equity * slice_pct
    deployed = deployed_kind_usd(db, account.id, intent.kind)
    if intent.kind == StrategyKind.index_core:
        remaining = max(0.0, cap - deployed)
        if remaining <= 1e-6:
            return "budget"
        if intent.notional > remaining + 1e-6:
            intent.notional = round(remaining, 2)
            intent.quantity = None

    if cash - intent.notional < floor_cash - 1e-6:
        return "cash_floor"
    if deployed + intent.notional > cap + 1e-6:
        return "budget"

    existing = working_order(db, account.id, intent.ticker, intent.kind)
    if existing is not None:
        if intent.price:
            try:
                from app.services.broker import get_broker_adapter

                adapter = get_broker_adapter(account)
                repl = getattr(adapter, "replace_open_limit", None)
                if callable(repl):
                    repl(existing, limit_price=float(intent.price))
            except Exception:
                logger.debug("replace working_order skipped", exc_info=True)
        return "working_order"

    if not for_allocate:
        # Window is enforced at allocate time so several engines can propose.
        pass
    else:
        window = int(settings.desk_gate_window_seconds or 300)
        if _recent_auto_buys(db, account.id, window) >= 1:
            return "window_busy"

    if settings.desk_gate_protect_enabled:
        if _cooldown_active(db, account.id, intent.ticker, float(settings.desk_gate_cooldown_hours)):
            return "cooldown"
        if _stoploss_count(
            db, account.id, float(settings.desk_gate_stoploss_lookback_hours)
        ) >= int(settings.desk_gate_stoploss_limit):
            return "stoploss_guard"
        peak = _peak_and_touch(db, equity)
        if peak > 0:
            dd = (peak - equity) / peak
            if dd > float(settings.desk_gate_max_drawdown_pct) / 100.0 + 1e-12:
                return "max_drawdown"
        exp = _ticker_expectancy(
            db, account.id, intent.ticker, int(settings.desk_gate_low_profit_min_trades)
        )
        if exp is not None and exp < 0:
            return "low_profit_pair"

    if settings.desk_gate_regime_lock and intent.kind in _TACTICAL_KINDS:
        regime = spy_regime(db)
        if regime in ("chop", "warmup"):
            return "regime_lock"
        if regime == "unknown" and settings.desk_gate_regime_fail_closed:
            return "regime_lock"

    cal = _calibration_deny(db, intent.kind)
    if cal:
        return cal
    return None


def _calibration_deny(db: Session, kind: StrategyKind | str) -> str | None:
    """Block a source whose asserted probabilities are worse than chance."""
    settings = get_settings()
    if not bool(getattr(settings, "desk_gate_calibration_enabled", False)):
        return None
    source = _kind_key(kind)
    if source not in {"hv_dip", "day_trade", "news", "mega_rotation", "judgment"}:
        return None
    try:
        from app.domain.models import ForecastLedger

        rows = (
            db.query(ForecastLedger)
            .filter(ForecastLedger.source == source)
            .filter(ForecastLedger.resolved_at.is_not(None))
            .all()
        )
    except Exception:
        return None
    if not isinstance(rows, (list, tuple)):
        return None
    briers = [
        float(r.brier)
        for r in rows
        if getattr(r, "brier", None) is not None
    ]
    resolved = len(briers)
    min_n = int(getattr(settings, "desk_gate_calibration_min_resolved", 30) or 30)
    if resolved < min_n:
        return None
    brier = sum(briers) / resolved
    ceiling = float(getattr(settings, "desk_gate_calibration_max_brier", 0.30) or 0.30)
    if brier > ceiling:
        return "miscalibrated"

    pairs: list[tuple[float, bool]] = []
    for r in rows:
        p = getattr(r, "p_pred", None)
        y = getattr(r, "outcome", None)
        if p is None or y is None:
            continue
        try:
            pairs.append((float(p), bool(y)))
        except (TypeError, ValueError):
            continue
    if len(pairs) < min_n:
        return None

    from app.services.learn.calibration import reliability_curve

    max_gap = float(getattr(settings, "desk_gate_calibration_max_bucket_gap", 0.25) or 0.25)
    min_bucket = int(getattr(settings, "desk_gate_calibration_min_bucket_n", 8) or 8)
    for bucket in reliability_curve(pairs):
        if int(bucket["n"]) >= min_bucket and abs(float(bucket["gap"])) > max_gap:
            return "miscalibrated"
    return None


def _apply_judgment(
    db: Session,
    intent: DeskIntent,
    deny: str,
    *,
    cash: float,
    enforce: bool,
) -> GateVerdict | None:
    """Override a numeric prior: courage (1 share) or observe (scandal)."""
    settings = get_settings()
    if not (enforce and bool(getattr(settings, "desk_judgment_enabled", True))):
        return None
    from app.services.desk_judgment import judge_intent

    judged = judge_intent(db, intent, deny)
    if judged is None:
        return None
    metrics = dict(intent.metrics or {})
    metrics["judgment"] = judged.as_dict()
    intent.metrics = metrics
    intent.explanation = judged.thesis
    if judged.action in {"allow", "resize"}:
        if deny == "ok":
            return None
        if judged.notional and judged.notional > 0:
            intent.notional = float(judged.notional)
            intent.quantity = 1.0
        logger.info(
            "desk_judgment courage %s was=%s now=%s 1sh=%.2f",
            intent.ticker,
            deny,
            judged.reason,
            intent.price,
        )
        return GateVerdict(
            allow=True,
            reason=judged.reason,
            enforce=True,
            shadow=False,
            cash_before=cash,
        )
    if judged.action == "observe":
        logger.info("desk_judgment observe %s %s", intent.ticker, judged.thesis[:160])
        return GateVerdict(
            allow=False,
            reason=judged.reason,
            enforce=True,
            shadow=False,
            cash_before=cash,
        )
    if judged.action == "deny":
        return GateVerdict(
            allow=False,
            reason=judged.reason,
            enforce=True,
            shadow=False,
            cash_before=cash,
        )
    return None


def evaluate_gate(
    db: Session,
    intent: DeskIntent,
    *,
    for_allocate: bool = False,
    as_paper: bool = False,
) -> GateVerdict:
    settings = get_settings()
    cash = _cash_usd(intent.account)
    if not settings.desk_gate_enabled:
        return GateVerdict(allow=True, reason="disabled", enforce=False, cash_before=cash)
    if intent.kind not in _USD_AUTO_KINDS:
        return GateVerdict(allow=True, reason="not_usd_auto", enforce=False, cash_before=cash)
    live_auto = _is_usd_live(intent.account) and bool(settings.hv_dip_live_auto_buy)
    if not _is_usd_paper(intent.account) and not as_paper and not live_auto:
        return GateVerdict(allow=True, reason="not_usd_paper", enforce=False, cash_before=cash)

    enforce = bool(settings.desk_gate_enforce)
    if as_paper and not _is_usd_paper(intent.account):
        enforce = False
    deny = _deny_reason(intent, db, for_allocate=for_allocate)
    always_block = {"invalid_notional", "paused"}
    if deny is None:
        veto = _apply_judgment(db, intent, "ok", cash=cash, enforce=enforce)
        if veto is not None:
            return veto
        return GateVerdict(
            allow=True,
            reason="ok",
            enforce=enforce,
            shadow=not enforce,
            cash_before=cash,
        )
    if deny in always_block:
        return GateVerdict(
            allow=False,
            reason=deny,
            enforce=enforce,
            shadow=not enforce,
            cash_before=cash,
        )

    judged = _apply_judgment(db, intent, deny, cash=cash, enforce=enforce)
    if judged is not None:
        return judged

    if not enforce:
        return GateVerdict(
            allow=True,
            reason=deny,
            enforce=False,
            shadow=True,
            cash_before=cash,
        )
    return GateVerdict(
        allow=False,
        reason=deny,
        enforce=True,
        shadow=False,
        cash_before=cash,
    )


def persist_decision(
    db: Session,
    intent: DeskIntent,
    verdict: GateVerdict,
    stored_verdict: str,
) -> DeskDecision | None:
    row = DeskDecision(
        account_id=intent.account.id,
        strategy_kind=intent.kind,
        ticker=intent.ticker.upper(),
        verdict=stored_verdict,
        reason=verdict.reason,
        notional=float(intent.notional),
        price=float(intent.price),
        cash_before=float(verdict.cash_before),
        score=float(intent.score or 0),
        r_multiple=intent.r_multiple,
        enforce=bool(verdict.enforce),
        payload=dict(intent.metrics or {}),
        decided_at=None if stored_verdict == "pending" else datetime.now(timezone.utc),
    )
    try:
        db.add(row)
        db.flush()
    except Exception:
        logger.exception("desk_gate persist failed")
        return None
    verdict.decision = row
    _record_gate_forecast(db, intent, verdict, row)
    mode = "shadow" if verdict.shadow else ("enforce" if verdict.enforce else "off")
    logger.info(
        "desk_gate %s %s %s %s 1sh=%.2f ticket=%.2f",
        mode,
        stored_verdict,
        verdict.reason,
        intent.ticker,
        intent.price,
        intent.notional,
    )
    return row


def _record_gate_forecast(
    db: Session,
    intent: DeskIntent,
    verdict: GateVerdict,
    row: DeskDecision,
) -> None:
    """Write-ahead probability for courage / observe / mega_rotation allow."""
    try:
        from app.services.learn.ledger import record_forecast_once
    except Exception:
        return
    judgment = dict((intent.metrics or {}).get("judgment") or {})
    try:
        conf = float(judgment.get("confidence") or 0.6)
    except (TypeError, ValueError):
        conf = 0.6
    source_kind = _kind_key(intent.kind)
    ref_id = str(row.id)
    ticker = intent.ticker
    try:
        if verdict.allow and source_kind == "mega_rotation":
            record_forecast_once(
                db,
                ref_id=ref_id,
                source="mega_rotation",
                kind="entry",
                ticker=ticker,
                p_pred=conf,
                horizon_days=5,
                features={"direction": "up", "reason": verdict.reason},
            )
        if verdict.reason == "judgment_courage":
            record_forecast_once(
                db,
                ref_id=ref_id,
                source="judgment",
                kind="courage",
                ticker=ticker,
                p_pred=conf,
                horizon_days=5,
                features={"direction": "up", "strategy": source_kind},
            )
        if verdict.reason == "observe_structural":
            record_forecast_once(
                db,
                ref_id=ref_id,
                source="judgment",
                kind="observe",
                ticker=ticker,
                p_pred=conf,
                horizon_days=5,
                features={"direction": "down", "strategy": source_kind},
            )
    except Exception:
        logger.debug("desk_gate forecast record skipped", exc_info=True)


def apply_intent(
    db: Session,
    intent: DeskIntent,
    *,
    for_allocate: bool = False,
    as_paper: bool = False,
) -> GateVerdict:
    """Evaluate + persist. Queue passing intents when desk_gate_queue_enabled."""
    settings = get_settings()
    verdict = evaluate_gate(db, intent, for_allocate=for_allocate, as_paper=as_paper)
    if as_paper and not _is_usd_paper(intent.account):
        verdict.shadow = True
        verdict.enforce = False
    if not verdict.allow:
        persist_decision(db, intent, verdict, "deny")
        return verdict
    from_judgment = verdict.reason == "judgment_courage"
    queue = (
        bool(settings.desk_gate_queue_enabled)
        and not for_allocate
        and verdict.enforce
        and not verdict.shadow
        and not from_judgment
    )
    if queue:
        persist_decision(db, intent, verdict, "pending")
        verdict.allow = False
        verdict.queued = True
        verdict.reason = "queued"
        return verdict
    stored = "shadow_allow" if verdict.shadow else "allow"
    if verdict.shadow and verdict.reason not in ("ok", "disabled", "not_usd_auto", "not_usd_paper"):
        stored = "shadow_deny"
    persist_decision(db, intent, verdict, stored)
    return verdict


def log_scan(
    db: Session,
    account: InvestmentAccount,
    kind: StrategyKind,
    ticker: str,
    reason: str,
    *,
    price: float = 0.0,
    notional: float = 0.0,
    payload: dict[str, Any] | None = None,
) -> None:
    """Counterfactual: a scan that did not become a suggestion/order."""
    intent = DeskIntent(
        account=account,
        kind=kind,
        ticker=ticker,
        notional=float(notional or 0),
        price=float(price or 0),
        metrics=payload or {},
    )
    verdict = GateVerdict(
        allow=False,
        reason=reason,
        enforce=False,
        shadow=True,
        cash_before=_cash_usd(account),
    )
    persist_decision(db, intent, verdict, "scan_skip")


def place_auto_order(db: Session, intent: DeskIntent) -> int:
    """Single path for mega/index (and allocate) auto buys."""
    from app.services.broker import get_broker_adapter
    from app.services.positions import open_position_from_fill

    account = intent.account
    price = float(intent.price)
    notional = float(intent.notional)
    qty = float(intent.quantity) if intent.quantity and intent.quantity > 0 else round(notional / price, 6)
    if qty <= 0:
        return 0
    mode = account.execution_mode
    if not isinstance(mode, ExecutionMode):
        mode = ExecutionMode(str(mode))
    explanation = intent.explanation or f"{_kind_key(intent.kind)} auto buy"
    suggestion = Suggestion(
        account_id=account.id,
        ticker=intent.ticker.upper(),
        strategy_kind=intent.kind,
        asset_class=AssetClass.us_equity,
        score=float(intent.score or 100.0),
        swing_score_letter="A",
        status=SuggestionStatus.approved,
        entry_price=round(price, 2),
        proposed_amount_brl=round(notional, 2),
        price_explanation=explanation,
        reasons=[],
        metrics=dict(intent.metrics or {}),
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    db.add(suggestion)
    db.flush()

    order = Order(
        account_id=account.id,
        suggestion_id=suggestion.id,
        ticker=intent.ticker.upper(),
        strategy_kind=intent.kind,
        side=OrderSide.buy,
        quantity=qty,
        amount_brl=round(notional, 2),
        limit_price=round(price, 2),
        status=OrderStatus.queued,
        broker=account.broker_code or "tastytrade",
        execution_mode=mode,
    )
    db.add(order)
    db.flush()

    adapter = get_broker_adapter(account)
    result = adapter.submit_order(order)
    order.status = result.status
    order.broker_order_id = result.broker_order_id
    order.error_message = result.error_message
    order.execution_payload = {
        **(order.execution_payload or {}),
        **(result.execution_payload or {}),
    }
    if result.status == OrderStatus.filled:
        order.filled_price = result.filled_price or order.limit_price
        order.filled_at = datetime.now(timezone.utc)
        pos = open_position_from_fill(db, order, suggestion)
        if intent.kind == StrategyKind.mega_rotation and pos is not None:
            metrics = dict(pos.metrics or {})
            metrics["peak_price"] = round(float(pos.entry_price), 4)
            pos.metrics = metrics
    db.flush()
    logger.info(
        "desk_gate PLACE %s %s qty=%s @ %.2f status=%s",
        _kind_key(intent.kind),
        intent.ticker,
        qty,
        price,
        getattr(order.status, "value", order.status),
    )
    return 1


def propose_or_place(db: Session, intent: DeskIntent) -> int:
    """Engine entry: deny=0, queued=1 (no order), allow=place_auto_order."""
    verdict = apply_intent(db, intent)
    if verdict.queued:
        return 1
    if not verdict.allow:
        return 0
    return place_auto_order(db, intent)


def load_pending(db: Session, account_id: str | None = None) -> list[DeskDecision]:
    try:
        q = db.query(DeskDecision).filter(DeskDecision.verdict == "pending")
        if account_id:
            q = q.filter(DeskDecision.account_id == account_id)
        return _safe_rows(q.order_by(DeskDecision.created_at.asc()).all())
    except Exception:
        return []


def _intent_from_row(account: InvestmentAccount, row: DeskDecision) -> DeskIntent:
    payload = dict(row.payload or {})
    qty = payload.get("quantity")
    return DeskIntent(
        account=account,
        kind=row.strategy_kind,
        ticker=row.ticker,
        notional=float(row.notional),
        price=float(row.price),
        score=float(row.score or 0),
        r_multiple=row.r_multiple,
        quantity=float(qty) if qty else None,
        explanation=str(payload.get("explanation") or ""),
        metrics=payload,
    )


def allocate_pending(db: Session) -> int:
    """Pick at most one pending intent per account and place it (ARQ job)."""
    pending = load_pending(db)
    if not pending:
        return 0
    by_acct: dict[str, list[DeskDecision]] = {}
    for row in pending:
        by_acct.setdefault(row.account_id, []).append(row)

    placed = 0
    now = datetime.now(timezone.utc)
    for account_id, rows in by_acct.items():
        account = db.get(InvestmentAccount, account_id)
        if account is None:
            for row in rows:
                row.verdict = "expired"
                row.reason = "no_account"
                row.decided_at = now
            continue
        ranked = sorted(
            rows,
            key=lambda r: (float(r.score or 0), float(r.r_multiple or 0)),
            reverse=True,
        )
        winner: DeskDecision | None = None
        winner_intent: DeskIntent | None = None
        for row in ranked:
            intent = _intent_from_row(account, row)
            verdict = evaluate_gate(db, intent, for_allocate=True)
            if verdict.allow:
                winner = row
                winner_intent = intent
                break
            row.verdict = "deny"
            row.reason = verdict.reason
            row.decided_at = now
        if winner is None or winner_intent is None:
            continue
        if winner.suggestion_id:
            from app.services.orders import create_order_from_suggestion

            sug = db.get(Suggestion, winner.suggestion_id)
            if sug is not None:
                try:
                    create_order_from_suggestion(db, sug, acted_by_user_id=None)
                    placed += 1
                except ValueError as exc:
                    winner.verdict = "deny"
                    winner.reason = str(exc)[:120]
                    winner.decided_at = now
                    continue
            else:
                placed += place_auto_order(db, winner_intent)
        else:
            placed += place_auto_order(db, winner_intent)
        winner.verdict = "allow"
        winner.reason = "allocated"
        winner.decided_at = now
        for row in ranked:
            if row is winner:
                continue
            if row.verdict == "pending":
                row.verdict = "not_selected"
                row.reason = "not_selected"
                row.decided_at = now
        logger.info(
            "desk_gate allocate account=%s winner=%s %s",
            account_id,
            winner.ticker,
            _kind_key(winner.strategy_kind),
        )
    return placed


__all__ = [
    "DeskIntent",
    "GateVerdict",
    "allocate_pending",
    "apply_intent",
    "evaluate_gate",
    "log_scan",
    "parse_slices",
    "place_auto_order",
    "propose_or_place",
    "remaining_slice_usd",
    "spy_regime",
    "working_order",
]
