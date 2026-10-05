"""Mega Rotation (Fase C): single-cash rotation among liquid mega-caps (paper-first).

The user's own system, validated by walk-forward: one pool of cash that buys the
most discounted mega-cap (largest dip from its recent high, optionally requiring
a turn-up), holds while it rises, and sells when the thesis is done (giveback % is a prior, not a law).
peak) — immediately rotating the freed cash to the next target. It can re-buy the
same ticker later when it dips again.

This is the *rotational* strategy the per-ticker backtests missed. Paper-only by
default (`mega_rotation_enabled=False`); never enabled for live until validated
live-on-paper with intraday fills, costs and a longer walk-forward.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.models import (
    AccountCurrency,
    InvestmentAccount,
    Position,
    PositionExitReason,
    PositionStatus,
    StrategyKind,
)
from app.services.positions import close_position

logger = logging.getLogger("fiidesk.mega_rotation")

_PEAK_KEY = "peak_price"


def _resolve_account(db: Session) -> InvestmentAccount | None:
    """Return the target USD tastytrade account, or None when none exists."""
    settings = get_settings()
    if (settings.mega_rotation_account_id or "").strip():
        return db.get(InvestmentAccount, settings.mega_rotation_account_id.strip())
    return (
        db.query(InvestmentAccount)
        .filter(
            InvestmentAccount.currency == AccountCurrency.USD,
            InvestmentAccount.broker_code == "tastytrade",
        )
        .order_by(InvestmentAccount.created_at.asc())
        .first()
    )


def _open_position(db: Session, account_id: str) -> Position | None:
    return (
        db.query(Position)
        .filter(
            Position.account_id == account_id,
            Position.strategy_kind == StrategyKind.mega_rotation,
            Position.status == PositionStatus.open,
        )
        .order_by(Position.opened_at.desc())
        .first()
    )


def _daily_bars(ticker: str) -> list:
    """Daily bars (Yahoo history). Empty on failure."""
    from app.services.market_data import MarketDataClient

    try:
        return MarketDataClient().fetch_daily_bars(ticker)
    except Exception:  # noqa: BLE001
        logger.exception("mega_rotation bars failed for %s", ticker)
        return []


def _mark_prices(tickers: list[str]) -> dict[str, float]:
    """Latest prices for the universe (last trade / bar close)."""
    from app.services.market_data import MarketDataClient

    try:
        return MarketDataClient().fetch_last_prices(tickers)
    except Exception:  # noqa: BLE001
        logger.exception("mega_rotation prices failed")
        return {}


def _pick_entry(
    tickers: list[str],
    *,
    dip_pct: float,
    lookback: int,
    confirm: bool,
    prices: dict[str, float],
) -> tuple[str, float, float] | None:
    """Choose the most-discounted qualifying ticker. Returns (ticker, price, dip%) or None.

    Qualifying: current price <= recent-high * (1 - dip%) AND, when confirm is
    set, the price must have turned up vs. the prior completed close. The
    deepest dip wins (matches the walk-forward selection).
    """
    best: tuple[str, float, float] | None = None
    best_dip = 0.0
    for t in tickers:
        bars = _daily_bars(t)
        if len(bars) < lookback + 2:
            continue
        # recent high from the prior `lookback` completed closes (no lookahead:
        # exclude the last bar, which may be today's partial session).
        highs = [float(b.high) for b in bars[-(lookback + 1) : -1]]
        high = max(highs) if highs else 0.0
        if high <= 0:
            continue
        px = prices.get(t) or float(bars[-1].close)
        if px <= 0:
            continue
        dip = (high - px) / high * 100.0
        if dip < dip_pct:
            continue
        if confirm:
            prev = float(bars[-2].close)
            if prev > 0 and px <= prev:
                continue  # still falling; wait for the turn
        if dip > best_dip:
            best_dip = dip
            best = (t, px, dip)
    return best


def _whole_share_notional(account: InvestmentAccount, price: float) -> float:
    """Whole shares in cash. Ticket is a target, not a ceiling below 1 share."""
    settings = get_settings()
    ticket = float(settings.mega_rotation_position_usd or 0)
    px = round(float(price), 2)
    cash = float(getattr(account, "cash_usd", None) or 0)
    if px <= 0 or cash + 1e-6 < px:
        return 0.0
    if ticket <= 0:
        ticket = cash
    budget = min(max(ticket, px), cash)
    qty = int(budget // px)
    if qty < 1:
        return round(px, 2)
    return round(qty * px, 2)


def _buy(
    db: Session,
    account: InvestmentAccount,
    ticker: str,
    price: float,
    *,
    dip_pct: float | None = None,
) -> int:
    """Propose a whole-share buy; judgment may resize past a numeric floor."""
    notional = _whole_share_notional(account, price)
    if notional <= 0:
        logger.info(
            "mega_rotation skip %s: 1sh=%.2f > cash",
            ticker,
            float(price),
        )
        return 0
    from app.services.desk_gate import DeskIntent, load_pending, propose_or_place, working_order

    pending = [
        r
        for r in load_pending(db, account.id)
        if r.strategy_kind == StrategyKind.mega_rotation
    ]
    if pending:
        logger.info("mega_rotation skip %s: judgment already queued", ticker)
        return 0

    existing = working_order(db, account.id, ticker, StrategyKind.mega_rotation)
    if existing is not None:
        logger.info("mega_rotation skip %s: working order already open — try replace", ticker)
        try:
            from app.services.broker import get_broker_adapter

            adapter = get_broker_adapter(account)
            repl = getattr(adapter, "replace_open_limit", None)
            if callable(repl):
                repl(existing, limit_price=float(price))
        except Exception:
            logger.debug("mega_rotation replace skipped", exc_info=True)
        return 0

    intent = DeskIntent(
        account=account,
        kind=StrategyKind.mega_rotation,
        ticker=ticker,
        notional=notional,
        price=float(price),
        score=100.0,
        explanation="Mega Rotation: rotacao buy-dip / trailing stop (notional)",
        metrics={
            "mega_rotation": True,
            "notional_usd": round(notional, 2),
            **({"dip_pct": round(float(dip_pct), 2)} if dip_pct is not None else {}),
        },
    )
    return propose_or_place(db, intent)


def _maybe_sell(db: Session, account: InvestmentAccount, pos: Position) -> int:
    """Giveback % is a prior. Judgment decides hold vs cut."""
    settings = get_settings()
    giveback = float(settings.mega_rotation_giveback_pct or 3.0)
    prices = _mark_prices([pos.ticker])
    px = prices.get(pos.ticker)
    if px is None or px <= 0:
        return 0

    metrics = dict(pos.metrics or {})
    peak = float(metrics.get(_PEAK_KEY) or float(pos.entry_price))
    peak = max(peak, px)
    metrics[_PEAK_KEY] = round(peak, 4)
    pos.metrics = metrics
    db.flush()

    giveback_hit = px <= peak * (1.0 - giveback / 100.0)
    from app.services.desk_judgment import (
        consider_exit,
        load_memories,
        load_news,
        record_exit_forecast,
    )

    judged = consider_exit(
        ticker=pos.ticker,
        entry=float(pos.entry_price),
        price=float(px),
        peak=peak,
        trigger="giveback" if giveback_hit else "none",
        news=load_news(db, pos.ticker),
        memories=load_memories(pos.ticker),
    )
    if judged is not None:
        metrics["judgment"] = judged.as_dict()
        pos.metrics = metrics
        db.flush()
        if judged.action == "hold":
            logger.info("mega_rotation HOLD %s %s", pos.ticker, judged.thesis[:160])
            record_exit_forecast(db, pos, judged)
            return 0
        if judged.action != "sell":
            judged = None

    if judged is None and not giveback_hit:
        return 0

    try:
        if judged is not None:
            record_exit_forecast(db, pos, judged)
        close_position(db, pos, reason=PositionExitReason.protect, manual_price=px)
        why = judged.reason if judged is not None else f"giveback {giveback:.2f}%"
        logger.info("mega_rotation SELL %s @ %.2f (%s)", pos.ticker, px, why)
        return 1
    except ValueError as exc:
        logger.warning("mega_rotation sell blocked %s: %s", pos.ticker, exc)
        return 0


def run_mega_rotation_cycle(db: Session) -> int:
    """Run one rotation pass. Returns actions taken (buys + sells)."""
    settings = get_settings()
    if not settings.mega_rotation_enabled:
        return 0

    account = _resolve_account(db)
    if account is None:
        logger.info("mega_rotation: no USD tastytrade account — skip")
        return 0
    if bool(getattr(account, "automation_paused", False)):
        logger.info("mega_rotation: kill switch active for %s — skip", account.name)
        return 0

    tickers = [t.strip().upper() for t in (settings.mega_rotation_tickers or "").split(",") if t.strip()]
    if not tickers:
        return 0

    actions = 0

    # Exit first: free the cash before looking for the next target.
    open_pos = _open_position(db, account.id)
    if open_pos is not None:
        actions += _maybe_sell(db, account, open_pos)

    # Entry: only when flat (single-cash rotation).
    if _open_position(db, account.id) is None:
        prices = _mark_prices(tickers)
        pick = _pick_entry(
            tickers,
            dip_pct=float(settings.mega_rotation_dip_pct or 5.0),
            lookback=int(settings.mega_rotation_lookback or 20),
            confirm=bool(settings.mega_rotation_confirm),
            prices=prices,
        )
        if pick is not None:
            actions += _buy(db, account, pick[0], pick[1], dip_pct=pick[2])

    return actions


__all__ = ["run_mega_rotation_cycle"]
