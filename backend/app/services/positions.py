"""Open/close positions and cash ledger for P&L."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.domain.models import (
    InvestmentAccount,
    Order,
    OrderSide,
    OrderStatus,
    Position,
    PositionExitReason,
    PositionStatus,
    StrategyKind,
    Suggestion,
)

from app.services.hv_dip.settlement import reserve_proceeds
from app.services.market_hours import us_session_date

from app.config import get_settings

logger = logging.getLogger("fiidesk.positions")


def open_position_from_fill(db: Session, order: Order, suggestion: Suggestion | None = None) -> Position:
    """Create an open position and debit cash after a buy fill. Idempotent per order."""
    existing = db.query(Position).filter(Position.order_id == order.id).one_or_none()
    if existing:
        return existing

    account = db.get(InvestmentAccount, order.account_id)
    if not account:
        raise ValueError("Account not found")

    sug = suggestion or db.get(Suggestion, order.suggestion_id)
    entry = float(order.filled_price or order.limit_price)
    qty = float(order.quantity)
    cost = round(qty * entry, 2)

    currency = str(getattr(account, "currency", "BRL") or "BRL")
    is_usd = currency.endswith("USD")
    if is_usd:
        cash = float(getattr(account, "cash_usd", None) or getattr(account, "hv_dip_equity_usd", None) or 0)
        if cost > cash + 1e-6:
            raise ValueError(f"Caixa insuficiente: US$ {cash:.2f} < custo US$ {cost:.2f}")
    else:
        cash = float(getattr(account, "cash_brl", None) or account.swing_equity_brl or 0)
        if cost > cash + 1e-6:
            raise ValueError(f"Caixa insuficiente: R$ {cash:.2f} < custo R$ {cost:.2f}")

    stop = float(sug.stop_price) if sug and sug.stop_price is not None else None
    target = float(sug.target_price) if sug and sug.target_price is not None else None
    setup_low = float(sug.setup_low) if sug and getattr(sug, "setup_low", None) is not None else None
    tranche = int(getattr(sug, "tranche_index", 1) or 1) if sug else 1
    kind = order.strategy_kind
    if not isinstance(kind, StrategyKind):
        kind = StrategyKind(str(kind))

    pos_metrics: dict = {}
    if sug:
        sm = sug.metrics or {}
        rh = sm.get("recent_high") or sm.get("recovery_high")
        if rh is not None:
            pos_metrics["recovery_high_price"] = float(rh)

    opened_at = order.filled_at or datetime.now(timezone.utc)
    if kind == StrategyKind.hv_dip:
        from app.services.hv_dip.exit_engine import (
            compute_must_review_by,
            init_hv_dip_position_metrics,
        )

        first = (
            db.query(Position)
            .filter(
                Position.account_id == order.account_id,
                Position.ticker == order.ticker,
                Position.strategy_kind == StrategyKind.hv_dip,
                Position.status == PositionStatus.open,
            )
            .order_by(Position.opened_at.asc())
            .first()
        )
        first_at = first.opened_at if first else opened_at
        if first_at and first_at.tzinfo is None:
            first_at = first_at.replace(tzinfo=timezone.utc)
        review_by = compute_must_review_by(first_at or opened_at)
        if first and first.metrics and first.metrics.get("must_review_by"):
            pos_metrics["must_review_by"] = first.metrics["must_review_by"]
        else:
            pos_metrics = init_hv_dip_position_metrics(pos_metrics, must_review_by=review_by)

    pos = Position(
        account_id=order.account_id,
        order_id=order.id,
        suggestion_id=order.suggestion_id,
        ticker=order.ticker,
        strategy_kind=kind,
        quantity=qty,
        entry_price=entry,
        stop_price=stop,
        target_price=target,
        setup_low=setup_low,
        tranche_index=tranche,
        avg_entry_price=entry,
        status=PositionStatus.open,
        opened_at=opened_at,
        metrics=pos_metrics,
    )
    if is_usd:
        account.cash_usd = round(cash - cost, 2)
    else:
        account.cash_brl = round(cash - cost, 2)
    db.add(pos)
    db.flush()

    # Auto (news-catalyst) fill → push "compra efetuada" notification.
    if kind == StrategyKind.hv_dip:
        try:
            from app.services.notify import notify_order_filled

            notify_order_filled(db, order, pos, suggestion=sug)
        except Exception:  # noqa: BLE001
            logger.exception("notify_order_filled failed for %s", order.ticker)

        # Quick Target: resting OCO on tastytrade live *and* sandbox after fill.
        # Mega rotation never takes this path (kind != hv_dip).
        try:
            from app.services.hv_dip.bracket import place_oco_bracket

            place_oco_bracket(db, pos)
        except Exception:  # noqa: BLE001
            logger.exception("place_oco_bracket failed for %s", order.ticker)

    return pos


def _submit_real_sell(db: Session, position: Position, exit_price: float) -> Order | None:
    """Submit a real broker sell order for a live USD position.

    Returns the sell Order (added to the session) or None when the account/broker
    does not support real sells. The caller uses a filled price when available;
    a `submitted`/`awaiting_broker` result is reconciled later.
    """
    from app.services.broker import get_broker_adapter

    account = db.get(InvestmentAccount, position.account_id)
    if account is None:
        return None
    broker = (account.broker_code or "").lower()
    mode = getattr(account, "execution_mode", None)
    mode_val = mode.value if hasattr(mode, "value") else str(mode)
    # Tastytrade sandbox (paper) and live both speak REST. Simulated paper does not.
    if broker != "tastytrade" and mode_val != "live":
        return None
    adapter = get_broker_adapter(account)
    if not hasattr(adapter, "sell"):
        return None

    proceeds = round(float(position.quantity) * exit_price, 2)
    order = Order(
        account_id=position.account_id,
        suggestion_id=None,
        ticker=position.ticker,
        strategy_kind=position.strategy_kind,
        side=OrderSide.sell,
        quantity=float(position.quantity),
        amount_brl=proceeds,
        limit_price=round(float(exit_price), 2),
        status=OrderStatus.queued,
        broker=(account.broker_code or "inter"),
        execution_mode=account.execution_mode,
        position_id=position.id,
    )
    result = adapter.sell(order)
    order.status = result.status
    order.broker_order_id = result.broker_order_id
    order.filled_price = result.filled_price
    order.error_message = result.error_message
    order.execution_payload = result.execution_payload
    db.add(order)
    db.flush()
    if result.error_message:
        logger.warning("real sell submitted with note: %s", result.error_message[:200])
    return order


def close_position(
    db: Session,
    position: Position,
    *,
    reason: PositionExitReason | str,
    manual_price: float | None = None,
    skip_broker_sell: bool = False,
) -> Position:
    if position.status != PositionStatus.open and str(position.status) != "open":
        raise ValueError("Position is not open")

    account = db.get(InvestmentAccount, position.account_id)
    if not account:
        raise ValueError("Account not found")
    currency = str(getattr(account, "currency", "BRL") or "BRL")
    is_usd = currency.endswith("USD")

    # Anti-GFV (US cash account): never sell a position opened on the same
    # session day — the opening buy has not settled (T+2), so selling now is
    # free-riding. Hard invariant, checked before any state mutation.
    if is_usd and us_session_date(position.opened_at) == us_session_date():
        raise ValueError(
            "GFV: venda no mesmo pregão da compra é proibida (liquidação T+2)"
        )

    if not isinstance(reason, PositionExitReason):
        reason = PositionExitReason(str(reason))

    try:
        from app.services.hv_dip.bracket import cancel_open_oco

        cancel_open_oco(db, position)
    except Exception:
        logger.exception("cancel_open_oco before close failed %s", position.ticker)

    if reason == PositionExitReason.stop:
        if position.stop_price is None:
            raise ValueError("Posição sem stop cadastrado")
        exit_price = float(position.stop_price)
    elif reason == PositionExitReason.target:
        if position.target_price is None:
            raise ValueError("Posição sem alvo cadastrado")
        exit_price = float(position.target_price)
    elif reason == PositionExitReason.manual:
        if manual_price is None or float(manual_price) <= 0:
            raise ValueError("Informe o preço de saída para fechamento manual")
        exit_price = float(manual_price)
    elif reason == PositionExitReason.protect:
        if manual_price is None or float(manual_price) <= 0:
            raise ValueError("Informe o preço de saída para fechamento protect")
        exit_price = float(manual_price)
    else:
        raise ValueError("Motivo de saída inválido")

    entry = float(position.entry_price)
    qty = float(position.quantity)

    # Real-money sell: submit the broker order first, before any local mutation.
    # A filled sell may give us a truer exit price than the requested one.
    # `skip_broker_sell` is set by the reconcile layer, which closes a position
    # because the broker sell (or an OCO leg) has already filled.
    if is_usd and not skip_broker_sell:
        sell_order = _submit_real_sell(db, position, exit_price)
        if sell_order is not None and sell_order.filled_price:
            exit_price = float(sell_order.filled_price)

    proceeds = round(qty * exit_price, 2)
    pnl = round((exit_price - entry) * qty, 2)
    cost = entry * qty
    pnl_pct = round((pnl / cost) * 100.0, 2) if cost > 0 else 0.0
    risk = entry - float(position.stop_price) if position.stop_price is not None else None
    r_mult = None
    if risk and risk > 0:
        r_mult = round((exit_price - entry) / risk, 2)

    position.status = PositionStatus.closed
    position.exit_reason = reason
    position.exit_price = round(exit_price, 2)
    position.realized_pnl_brl = pnl
    position.realized_pnl_pct = pnl_pct
    position.r_multiple_realized = r_mult
    position.closed_at = datetime.now(timezone.utc)
    if is_usd:
        account.cash_usd = round(float(account.cash_usd or 0) + proceeds, 2)
        # T+2: sell proceeds are reserved until they settle (buying power
        # stays reduced), preventing a Good Faith Violation on the next buy.
        reserve_proceeds(
            account,
            proceeds,
            days=int(get_settings().hv_dip_settlement_days or 2),
        )
    else:
        account.cash_brl = round(float(account.cash_brl or 0) + proceeds, 2)
    db.flush()
    return position


def count_open_positions(
    db: Session,
    account_id: str,
    *,
    strategy_kind: StrategyKind | None = None,
) -> int:
    q = db.query(Position).filter(
        Position.account_id == account_id,
        Position.status == PositionStatus.open,
    )
    if strategy_kind is not None:
        q = q.filter(Position.strategy_kind == strategy_kind)
    return q.count()


def count_open_hv_dip_tickers(db: Session, account_id: str) -> int:
    rows = (
        db.query(Position.ticker)
        .filter(
            Position.account_id == account_id,
            Position.strategy_kind == StrategyKind.hv_dip,
            Position.status == PositionStatus.open,
        )
        .distinct()
        .all()
    )
    return len(rows)


def open_invested_brl(
    db: Session,
    account_id: str,
    *,
    strategy_kind: StrategyKind | None = None,
) -> float:
    q = db.query(Position).filter(
        Position.account_id == account_id,
        Position.status == PositionStatus.open,
    )
    if strategy_kind is not None:
        q = q.filter(Position.strategy_kind == strategy_kind)
    rows = q.all()
    return round(sum(float(p.entry_price) * float(p.quantity) for p in rows), 2)


def list_open_positions(
    db: Session,
    account_id: str,
    *,
    strategy_kind: StrategyKind | None = None,
) -> list[Position]:
    q = db.query(Position).filter(
        Position.account_id == account_id,
        Position.status == PositionStatus.open,
    )
    if strategy_kind is not None:
        q = q.filter(Position.strategy_kind == strategy_kind)
    return q.order_by(Position.opened_at.desc()).all()


def mark_open_positions(
    db: Session,
    account_id: str,
    *,
    strategy_kind: StrategyKind | None = None,
    prices: dict[str, float] | None = None,
) -> tuple[list[dict], dict[str, float]]:
    """Return open positions enriched with mark-to-market fields + price map used."""
    from app.config import get_settings
    from app.services.market_data import MarketDataClient
    from app.services.brapi_client import BrapiClient

    settings = get_settings()

    rows = list_open_positions(db, account_id, strategy_kind=strategy_kind)
    tickers = [p.ticker for p in rows]
    quote_sources: dict[str, str] = {}
    if prices is not None:
        px = prices
        quote_sources = {str(t).upper(): "injected" for t in px}
    else:
        account = db.get(InvestmentAccount, account_id)
        currency = str(getattr(account, "currency", "BRL") or "BRL") if account else "BRL"
        is_usd = currency.endswith("USD")
        if is_usd:
            md = MarketDataClient()
            px = md.fetch_last_prices(tickers)
            quote_sources = dict(getattr(md, "last_quote_sources", {}) or {})
        else:
            px = BrapiClient().fetch_last_prices(tickers)
            quote_sources = {str(t).upper(): "brapi" for t in px}
    enriched: list[dict] = []
    for p in rows:
        entry = float(p.entry_price)
        qty = float(p.quantity)
        cost = round(entry * qty, 2)
        mark_raw = px.get(p.ticker.upper()) if hasattr(px, "get") else None
        if mark_raw is None:
            mark_raw = px.get(p.ticker) if hasattr(px, "get") else None
        metrics = dict(p.metrics or {})
        use_v2 = (
            settings.hv_dip_exit_v2_enabled
            and p.strategy_kind == StrategyKind.hv_dip
        )
        if use_v2 and not metrics.get("must_review_by"):
            from app.services.hv_dip.exit_engine import compute_must_review_by

            opened = p.opened_at
            if opened and opened.tzinfo is None:
                opened = opened.replace(tzinfo=timezone.utc)
            deadline = compute_must_review_by(opened or datetime.now(timezone.utc))
            metrics["must_review_by"] = deadline.isoformat()
            p.metrics = metrics
            db.flush()

        if mark_raw is None:
            logger.info("exit_skip no_mark %s", p.ticker)
            enriched.append(
                {
                    "position": p,
                    "mark_price": None,
                    "cost_brl": cost,
                    "market_value_brl": cost,
                    "unrealized_pnl_brl": 0.0,
                    "unrealized_pnl_pct": 0.0,
                    "peak_unrealized_pct": float(metrics.get("peak_unrealized_pct") or 0.0),
                    "price_alert": None,
                    "exit_state": "no_mark",
                    "latched_5": bool(metrics.get("latched_5")),
                    "protect_active": bool(metrics.get("protect_active")),
                    "must_review_by": metrics.get("must_review_by"),
                    "days_until_review": None,
                    "auto_close": False,
                    "quote_source": "none",
                    "no_mark": True,
                }
            )
            continue

        mark = float(mark_raw)
        source = quote_sources.get(p.ticker.upper()) or quote_sources.get(p.ticker) or "live"
        mv = round(mark * qty, 2)
        upnl = round(mv - cost, 2)
        upnl_pct = round((upnl / cost) * 100.0, 2) if cost > 0 else 0.0

        stored_peak = metrics.get("peak_unrealized_pct")
        peak = float(stored_peak) if stored_peak is not None else upnl_pct
        if upnl_pct > peak:
            peak = upnl_pct

        price_alert: str | None = None
        exit_state = "normal"
        days_until_review: int | None = None
        auto_close = False

        if use_v2:
            from app.services.hv_dip.exit_engine import (
                days_until_review as calc_days_review,
                evaluate_hv_dip_exit,
            )

            recovery_high = metrics.get("recovery_high_price")
            days_since_high = metrics.get("days_since_recent_high")
            if (recovery_high is None or days_since_high is None) and p.suggestion_id:
                sug = db.get(Suggestion, p.suggestion_id)
                if sug:
                    sm = sug.metrics or {}
                    if recovery_high is None:
                        rh = sm.get("recent_high") or sm.get("recovery_high")
                        if rh is not None:
                            recovery_high = float(rh)
                            metrics["recovery_high_price"] = recovery_high
                    if days_since_high is None:
                        dsh = sm.get("days_since_recent_high")
                        if dsh is not None:
                            days_since_high = int(dsh)
                            metrics["days_since_recent_high"] = days_since_high

            opened = p.opened_at
            if opened and opened.tzinfo is None:
                opened = opened.replace(tzinfo=timezone.utc)
            ev = evaluate_hv_dip_exit(
                metrics,
                upnl_pct=upnl_pct,
                mark=mark,
                entry=entry,
                stop=float(p.stop_price) if p.stop_price is not None else None,
                target=float(p.target_price) if p.target_price is not None else None,
                opened_at=opened or datetime.now(timezone.utc),
                recovery_high=recovery_high,
                days_since_recent_high=days_since_high,
            )
            metrics = ev.metrics
            peak = ev.peak_unrealized_pct
            price_alert = ev.price_alert
            exit_state = ev.exit_state
            days_until_review = calc_days_review(metrics)
            auto_close = ev.auto_close
            from app.services.desk_judgment import consider_exit, load_memories, load_news

            judged = consider_exit(
                ticker=p.ticker,
                entry=entry,
                price=mark,
                peak=None,
                trigger=str(exit_state) if auto_close else "none",
                news=load_news(db, p.ticker),
                memories=load_memories(p.ticker),
                pnl_pct=upnl_pct,
            )
            if judged is not None:
                metrics["judgment"] = judged.as_dict()
                if judged.action == "hold" and auto_close:
                    auto_close = False
                    price_alert = None
                    exit_state = "judgment_hold"
                    logger.info("hv_dip HOLD %s %s", p.ticker, judged.thesis[:160])
                    try:
                        from app.services.desk_judgment import record_exit_forecast
                        from app.services.hv_dip.bracket import cancel_open_oco

                        record_exit_forecast(db, p, judged)
                        cancel_open_oco(db, p)
                    except Exception:
                        logger.exception("hv_dip hold oco-cancel failed %s", p.ticker)
                elif judged.action == "sell" and not auto_close:
                    auto_close = True
                    price_alert = "judgment_cut"
                    exit_state = "judgment_cut"
                    logger.info("hv_dip CUT %s %s", p.ticker, judged.thesis[:160])
                    try:
                        from app.services.desk_judgment import record_exit_forecast
                        from app.services.hv_dip.bracket import cancel_open_oco

                        record_exit_forecast(db, p, judged)
                        cancel_open_oco(db, p)
                    except Exception:
                        logger.exception("hv_dip cut oco-cancel failed %s", p.ticker)
            p.metrics = metrics
            db.flush()
        else:
            # Legacy (V1) fallback: hard stop/target only (Quick Target semantics).
            # Trailing/recovery alerts were removed with the old thesis.
            if stored_peak is None or upnl_pct > float(stored_peak):
                metrics["peak_unrealized_pct"] = upnl_pct
                p.metrics = metrics
                db.flush()

            if p.stop_price is not None and mark <= float(p.stop_price):
                price_alert = "stop"
                auto_close = True
            elif p.target_price is not None and mark >= float(p.target_price):
                price_alert = "target"
                auto_close = True

        enriched.append(
            {
                "position": p,
                "mark_price": round(mark, 2),
                "cost_brl": cost,
                "market_value_brl": mv,
                "unrealized_pnl_brl": upnl,
                "unrealized_pnl_pct": upnl_pct,
                "peak_unrealized_pct": peak,
                "price_alert": price_alert,
                "exit_state": exit_state,
                "latched_5": bool(metrics.get("latched_5")),
                "protect_active": bool(metrics.get("protect_active")),
                "must_review_by": metrics.get("must_review_by"),
                "days_until_review": days_until_review,
                "auto_close": auto_close,
                "quote_source": source,
                "no_mark": False,
            }
        )
    return enriched, px


def _last_prices_for_account(db: Session, account_id: str, tickers: list[str]) -> dict[str, float]:
    from app.services.market_data import MarketDataClient
    from app.services.brapi_client import BrapiClient

    account = db.get(InvestmentAccount, account_id)
    currency = str(getattr(account, "currency", "BRL") or "BRL") if account else "BRL"
    is_usd = currency.endswith("USD")
    if is_usd:
        return MarketDataClient().fetch_last_prices(tickers)
    return BrapiClient().fetch_last_prices(tickers)


def close_position_at_market(db: Session, position: Position) -> Position:
    """Close using latest quote as manual exit price."""
    prices = _last_prices_for_account(db, position.account_id, [position.ticker])
    px = prices.get(position.ticker.upper()) or prices.get(position.ticker)
    if px is None or float(px) <= 0:
        raise ValueError(f"Sem cotação para {position.ticker}")
    return close_position(
        db,
        position,
        reason=PositionExitReason.manual,
        manual_price=float(px),
    )


def close_all_open_at_market(
    db: Session,
    account_id: str,
    *,
    strategy_kind: StrategyKind | None = None,
) -> list[Position]:
    rows = list_open_positions(db, account_id, strategy_kind=strategy_kind)
    if not rows:
        return []
    prices = _last_prices_for_account(db, account_id, [p.ticker for p in rows])
    closed: list[Position] = []
    for p in rows:
        px = prices.get(p.ticker.upper()) or prices.get(p.ticker)
        if px is None or float(px) <= 0:
            raise ValueError(f"Sem cotação para {p.ticker}")
        closed.append(
            close_position(
                db,
                p,
                reason=PositionExitReason.manual,
                manual_price=float(px),
            )
        )
    return closed


def portfolio_snapshot(db: Session, account: InvestmentAccount) -> dict:
    currency = str(getattr(account, "currency", "BRL") or "BRL")
    is_usd = currency.endswith("USD")
    if is_usd:
        cash = round(float(getattr(account, "cash_usd", None) or 0), 2)
    else:
        cash = round(float(getattr(account, "cash_brl", None) or 0), 2)
    invested = open_invested_brl(db, account.id)
    open_n = count_open_positions(db, account.id)
    open_swing = count_open_positions(db, account.id, strategy_kind=StrategyKind.swing)
    open_income = count_open_positions(db, account.id, strategy_kind=StrategyKind.income)
    open_hv = count_open_positions(db, account.id, strategy_kind=StrategyKind.hv_dip)
    open_hv_tickers = count_open_hv_dip_tickers(db, account.id)

    enriched, _ = mark_open_positions(db, account.id)
    market_value = round(sum(float(e["market_value_brl"]) for e in enriched), 2)
    unrealized = round(sum(float(e["unrealized_pnl_brl"]) for e in enriched), 2)
    equity = round(cash + market_value, 2)
    equity_cost = round(cash + invested, 2)
    cash_pct = round((cash / equity * 100.0), 2) if equity > 0 else 100.0

    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    day_pnl = (
        db.query(Position)
        .filter(
            Position.account_id == account.id,
            Position.status == PositionStatus.closed,
            Position.closed_at >= start,
        )
        .all()
    )
    pnl_day = round(sum(float(p.realized_pnl_brl or 0) for p in day_pnl), 2)
    return {
        "cash_brl": cash,
        "cash_usd": float(getattr(account, "cash_usd", None) or 0) if is_usd else None,
        "currency": "USD" if is_usd else "BRL",
        "invested_open_brl": invested,
        "market_value_open_brl": market_value,
        "unrealized_pnl_brl": unrealized,
        "equity_brl": equity,
        "equity_cost_brl": equity_cost,
        "open_positions": open_n,
        "open_swing": open_swing,
        "open_income": open_income,
        "open_hv_dip": open_hv,
        "open_hv_dip_tickers": open_hv_tickers,
        "hv_dip_max_positions": int(getattr(account, "hv_dip_max_positions", 4) or 4),
        "hv_dip_cash_floor_pct": float(getattr(account, "hv_dip_cash_floor_pct", 30.0) or 30.0),
        "hv_dip_max_ticker_pct": float(getattr(account, "hv_dip_max_ticker_pct", 80.0) or 80.0),
        "cash_pct_of_equity": cash_pct,
        "realized_pnl_day_brl": pnl_day,
    }


def _period_start(period: str) -> datetime:
    now = datetime.now(timezone.utc)
    period = (period or "day").lower()
    if period == "week":
        start = now - timedelta(days=now.weekday())
    elif period == "month":
        start = now.replace(day=1)
    elif period == "year":
        start = now.replace(month=1, day=1)
    else:
        start = now
    return start.replace(hour=0, minute=0, second=0, microsecond=0)


def _account_currency(account: InvestmentAccount | None) -> str:
    if account is None:
        return "BRL"
    raw = str(getattr(account, "currency", "BRL") or "BRL").upper()
    if raw.endswith("USD"):
        return "USD"
    return "BRL"


def _equity_ref(
    db: Session,
    account: InvestmentAccount | None,
    *,
    snap: dict | None = None,
) -> float:
    """Reference equity for % goals (cash + open market value)."""
    if account is None:
        return 100.0
    if snap is None:
        snap = portfolio_snapshot(db, account)
    eq = float(snap.get("equity_brl") or 0)
    if eq > 0:
        return round(eq, 2)
    # Seed fallback for empty desks
    if _account_currency(account) == "USD":
        return round(float(getattr(account, "cash_usd", None) or 100.0), 2)
    return round(float(getattr(account, "cash_brl", None) or account.swing_equity_brl or 100.0), 2)


def _period_day_count(start: datetime) -> int:
    today = datetime.now(timezone.utc).date()
    start_d = start.date()
    return max(1, (today - start_d).days + 1)


def _trade_return_pct(p: Position) -> float | None:
    entry = float(p.avg_entry_price or p.entry_price or 0)
    qty = abs(float(p.quantity or 0))
    invested = qty * entry
    if invested <= 0:
        return None
    return float(p.realized_pnl_brl or 0) / invested * 100.0


def _exit_reason_value(p: Position) -> str:
    r = p.exit_reason
    if r is None:
        return ""
    return r.value if hasattr(r, "value") else str(r)


def build_pnl_goals(
    db: Session,
    account: InvestmentAccount | None,
    *,
    period: str,
    start: datetime,
    period_pnl: float,
    equity_ref: float | None = None,
) -> dict:
    from app.config import get_settings

    settings = get_settings()
    daily_pct = float(settings.desk_daily_pnl_target_pct or 7.0)
    if equity_ref is None:
        equity_ref = _equity_ref(db, account) if account else 100.0
    days = _period_day_count(start)
    period_target = round(equity_ref * (daily_pct / 100.0) * days, 2)
    period_pnl_pct = round((period_pnl / equity_ref) * 100.0, 2) if equity_ref else 0.0
    period_target_pct = round(daily_pct * days, 2)
    progress = 0.0
    if period_target > 0:
        progress = round(max(0.0, period_pnl / period_target) * 100.0, 1)
    return {
        "daily_target_pct": daily_pct,
        "equity_ref": equity_ref,
        "days_in_period": days,
        "period_pnl": round(period_pnl, 2),
        "period_pnl_pct": period_pnl_pct,
        "period_target_pnl": period_target,
        "period_target_pct": period_target_pct,
        "progress_pct": progress,
        "hit": period_pnl >= period_target and period_target > 0,
        "currency": _account_currency(account),
    }


def build_stretch_scorecard(
    db: Session,
    account: InvestmentAccount | None,
    *,
    strategy_kind: StrategyKind | None = None,
    equity_now: float | None = None,
) -> dict:
    """Exit V2 stretch scorecard vs playbook targets (beat first paper batch)."""
    from app.config import get_settings

    settings = get_settings()
    if equity_now is None:
        equity_now = _equity_ref(db, account) if account else 0.0
    q = db.query(Position).filter(Position.status == PositionStatus.closed)
    if account is not None:
        q = q.filter(Position.account_id == account.id)
    if strategy_kind is not None:
        q = q.filter(Position.strategy_kind == strategy_kind)
    closed = q.order_by(Position.closed_at.asc()).all()

    rets: list[float] = []
    rs: list[float] = []
    wins = 0
    losses = 0
    protect_or_2r = 0
    latched_like = 0
    total_pnl = 0.0
    latch_floor = float(settings.hv_dip_latch_pct or 5.0)
    for p in closed:
        pnl = float(p.realized_pnl_brl or 0)
        total_pnl += pnl
        if pnl > 0:
            wins += 1
        elif pnl < 0:
            losses += 1
        ret = _trade_return_pct(p)
        if ret is not None:
            rets.append(ret)
        if p.r_multiple_realized is not None:
            rs.append(float(p.r_multiple_realized))
        reason = _exit_reason_value(p)
        if reason in {"target", "protect"}:
            protect_or_2r += 1
        metrics = p.metrics if isinstance(p.metrics, dict) else {}
        exit_state = str(metrics.get("exit_state") or "").lower()
        if (
            metrics.get("latched_5")
            or exit_state in {"latched", "protect"}
            or (ret is not None and ret >= latch_floor)
        ):
            latched_like += 1

    n = len(closed)
    avg_ret = round(sum(rets) / len(rets), 2) if rets else 0.0
    win_rate = round(wins / n * 100.0, 1) if n else 0.0
    expectancy = round(sum(rs) / len(rs), 2) if rs else None
    sys_exit_pct = round(protect_or_2r / n * 100.0, 1) if n else 0.0
    latch_pct = round(latched_like / n * 100.0, 1) if n else 0.0

    equity_target = float(settings.desk_stretch_equity_target or 130.0)
    return {
        "horizon_trades": int(settings.desk_stretch_horizon_trades or 40),
        "horizon_days": int(settings.desk_stretch_horizon_days or 60),
        "closed_trades": n,
        "equity_now": equity_now,
        "equity_target": equity_target,
        "equity_progress_pct": round(min(100.0, equity_now / equity_target * 100.0), 1)
        if equity_target
        else 0.0,
        "avg_return_pct": avg_ret,
        "avg_return_target_pct": float(settings.desk_stretch_avg_return_pct or 11.0),
        "realized_pnl": round(total_pnl, 2),
        "realized_pnl_target": float(settings.desk_stretch_realized_pnl_target or 25.0),
        "latched_pct": latch_pct,
        "latched_target_pct": float(settings.desk_stretch_latched_pct or 55.0),
        "protect_or_2r_pct": sys_exit_pct,
        "protect_or_2r_target_pct": float(settings.desk_stretch_protect_or_2r_pct or 40.0),
        "expectancy_r": expectancy,
        "expectancy_r_target": float(settings.desk_stretch_expectancy_r or 0.45),
        "win_rate_pct": win_rate,
        "win_rate_target_pct": float(settings.desk_stretch_win_rate_pct or 58.0),
        "max_drawdown_target_pct": float(settings.desk_stretch_max_drawdown_pct or 12.0),
        "wins": wins,
        "losses": losses,
    }


def pnl_report(
    db: Session,
    account_id: str,
    *,
    period: str = "day",
    strategy_kind: StrategyKind | None = None,
) -> dict:
    start = _period_start(period)
    q = db.query(Position).filter(
        Position.account_id == account_id,
        Position.status == PositionStatus.closed,
        Position.closed_at >= start,
    )
    if strategy_kind is not None:
        q = q.filter(Position.strategy_kind == strategy_kind)
    rows = q.order_by(Position.closed_at.desc()).all()
    total = round(sum(float(p.realized_pnl_brl or 0) for p in rows), 2)
    wins = sum(1 for p in rows if (p.realized_pnl_brl or 0) > 0)
    losses = sum(1 for p in rows if (p.realized_pnl_brl or 0) < 0)
    account = db.get(InvestmentAccount, account_id)
    equity_ref = _equity_ref(db, account) if account else 100.0
    goals = build_pnl_goals(
        db,
        account,
        period=period,
        start=start,
        period_pnl=total,
        equity_ref=equity_ref,
    )
    scorecard = build_stretch_scorecard(
        db, account, strategy_kind=strategy_kind, equity_now=equity_ref
    )
    return {
        "period": period,
        "strategy_kind": strategy_kind.value if strategy_kind else None,
        "from": start.isoformat(),
        "total_pnl_brl": total,
        "trades": len(rows),
        "wins": wins,
        "losses": losses,
        "items": rows,
        "goals": goals,
        "scorecard": scorecard,
    }


def pnl_series(
    db: Session,
    account_id: str,
    *,
    period: str = "month",
    strategy_kind: StrategyKind | None = None,
) -> dict:
    """Daily cumulative realized PnL + 7%/day target curve for the period."""
    from app.config import get_settings

    start = _period_start(period)
    q = db.query(Position).filter(
        Position.account_id == account_id,
        Position.status == PositionStatus.closed,
        Position.closed_at >= start,
        Position.closed_at.isnot(None),
    )
    if strategy_kind is not None:
        q = q.filter(Position.strategy_kind == strategy_kind)
    rows = q.order_by(Position.closed_at.asc()).all()
    by_day: dict[str, float] = {}
    for p in rows:
        closed = p.closed_at
        if closed is None:
            continue
        day = closed.date().isoformat()
        by_day[day] = round(by_day.get(day, 0.0) + float(p.realized_pnl_brl or 0), 2)

    account = db.get(InvestmentAccount, account_id)
    currency = _account_currency(account)
    equity_ref = _equity_ref(db, account)
    daily_pct = float(get_settings().desk_daily_pnl_target_pct or 7.0)
    day_target = round(equity_ref * (daily_pct / 100.0), 2)

    # Fill every calendar day so the target line advances even without trades.
    start_d = start.date()
    end_d = datetime.now(timezone.utc).date()
    points: list[dict] = []
    cumulative = 0.0
    target_cum = 0.0
    cursor = start_d
    day_i = 0
    while cursor <= end_d:
        day_i += 1
        key = cursor.isoformat()
        day_pnl = round(by_day.get(key, 0.0), 2)
        cumulative = round(cumulative + day_pnl, 2)
        target_cum = round(day_target * day_i, 2)
        day_pnl_pct = round((day_pnl / equity_ref) * 100.0, 2) if equity_ref else 0.0
        points.append(
            {
                "date": key,
                "cumulative_pnl": cumulative,
                "day_pnl": day_pnl,
                "target_cumulative_pnl": target_cum,
                "day_target_pnl": day_target,
                "day_pnl_pct": day_pnl_pct,
                "day_target_pct": daily_pct,
            }
        )
        cursor = cursor + timedelta(days=1)

    goals = build_pnl_goals(
        db,
        account,
        period=period,
        start=start,
        period_pnl=cumulative,
        equity_ref=equity_ref,
    )
    return {
        "period": period,
        "strategy_kind": strategy_kind.value if strategy_kind else None,
        "currency": currency,
        "from": start.isoformat(),
        "points": points,
        "goals": goals,
        "daily_target_pct": daily_pct,
        "equity_ref": equity_ref,
    }
