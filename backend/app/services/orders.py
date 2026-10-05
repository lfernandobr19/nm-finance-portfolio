from __future__ import annotations

import math
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.domain.models import (
    ExecutionMode,
    InvestmentAccount,
    Order,
    OrderSide,
    OrderStatus,
    Position,
    PositionStatus,
    StrategyKind,
    Suggestion,
)
from app.config import get_settings
from app.services.broker import get_broker_adapter
from app.services.hv_dip.sizing import (
    account_sizing_basis,
    deployed_on_ticker_usd,
    usd_cash,
)
from app.services.positions import count_open_hv_dip_tickers, open_position_from_fill

settings = get_settings()


def _limit_price(suggestion: Suggestion) -> float:
    if suggestion.entry_price is not None:
        return float(suggestion.entry_price)
    metrics = suggestion.metrics or {}
    price = metrics.get("price") or metrics.get("entry")
    if price is None:
        raise ValueError("Suggestion metrics missing price")
    return float(price)


def _quantity(amount: float, price: float, *, fractional: bool) -> float:
    if price <= 0:
        return 0.0
    if fractional:
        qty = round(amount / price, 6)
        return qty if qty * price >= 0.01 else 0.0
    qty = math.floor(amount / price)
    if qty < 1 and amount >= price:
        return 1.0
    return float(max(qty, 0))


def _strategy_kind(suggestion: Suggestion) -> StrategyKind:
    kind = getattr(suggestion, "strategy_kind", None) or StrategyKind.income
    if not isinstance(kind, StrategyKind):
        try:
            return StrategyKind(str(kind))
        except ValueError:
            return StrategyKind.income
    return kind


def _sizing_equity(account: InvestmentAccount) -> float:
    cash = float(getattr(account, "cash_brl", None) or 0)
    legacy = float(account.swing_equity_brl or 0)
    return cash if cash > 0 else legacy


def _usd_cash(account: InvestmentAccount) -> float:
    return usd_cash(account)


def count_open_swing_positions(db: Session, account_id: str) -> int:
    return (
        db.query(Position)
        .filter(
            Position.account_id == account_id,
            Position.strategy_kind == StrategyKind.swing,
            Position.status == PositionStatus.open,
        )
        .count()
    )


def deployed_hv_dip_usd_on_ticker(db: Session, account_id: str, ticker: str) -> float:
    return deployed_on_ticker_usd(db, account_id, ticker)


def assert_swing_guards(
    db: Session,
    account: InvestmentAccount,
    suggestion: Suggestion,
    *,
    amount_brl: float,
) -> None:
    """Raise ValueError if swing freios block the order."""
    letter = (suggestion.swing_score_letter or "").upper()
    mode = account.execution_mode
    if not isinstance(mode, ExecutionMode):
        mode = ExecutionMode(str(mode))

    if letter == "C" and mode == ExecutionMode.live:
        raise ValueError("Score C só em paper — mude execution_mode ou rejeite")

    open_n = count_open_swing_positions(db, account.id)
    max_n = int(account.swing_max_positions or 5)
    if open_n >= max_n:
        raise ValueError(f"Limite de {max_n} posições swing abertas atingido ({open_n})")

    equity = _sizing_equity(account)
    floor_pct = float(account.swing_cash_floor_pct or 20.0)
    equity_ref = float(account.swing_equity_brl or equity or 0)
    floor = equity_ref * (floor_pct / 100.0)
    cash = float(getattr(account, "cash_brl", None) or equity)
    if cash - amount_brl < floor - 1e-6:
        raise ValueError(
            f"Piso de caixa {floor_pct:.0f}%: caixa R$ {cash:.2f}, "
            f"ordem R$ {amount_brl:.2f}, piso R$ {floor:.2f}"
        )


def assert_hv_dip_guards(
    db: Session,
    account: InvestmentAccount,
    suggestion: Suggestion,
    *,
    amount_usd: float,
    human_approved: bool = False,
) -> None:
    """Raise ValueError if hv_dip freios block the order."""
    if getattr(suggestion, "review_required", False) and not human_approved:
        raise ValueError(
            "Review NM obrigatória — confirme no app (auto-approve bloqueado)"
        )

    open_tickers = count_open_hv_dip_tickers(db, account.id)
    max_n = int(getattr(account, "hv_dip_max_positions", 4) or 4)
    already = (
        db.query(Position)
        .filter(
            Position.account_id == account.id,
            Position.ticker == suggestion.ticker,
            Position.strategy_kind == StrategyKind.hv_dip,
            Position.status == PositionStatus.open,
        )
        .count()
        > 0
    )
    if not already and open_tickers >= max_n:
        raise ValueError(f"Limite de {max_n} tickers High-Vol abertos atingido")

    tranche = int(getattr(suggestion, "tranche_index", 1) or 1)
    if tranche > int(settings.hv_dip_max_tranches):
        raise ValueError(
            f"Máximo de {settings.hv_dip_max_tranches} tranches (scale-in) por ticker"
        )

    basis = account_sizing_basis(db, account)
    letter = (getattr(suggestion, "swing_score_letter", None) or "").upper()
    if letter != "A" and basis.settled - amount_usd < basis.floor_cash - 1e-6:
        raise ValueError(
            f"Piso de caixa {basis.floor_pct:.0f}%: caixa liquidado US$ {basis.settled:.2f}, "
            f"ordem US$ {amount_usd:.2f}, piso US$ {basis.floor_cash:.2f}. "
            f"Score A pode ultrapassar (setup imperdível)."
        )

    deployed = deployed_on_ticker_usd(db, account.id, suggestion.ticker)
    if deployed + amount_usd > basis.ticker_cap + 1e-6:
        raise ValueError(
            f"Teto {basis.max_ticker_pct:.0f}% no ticker: já US$ {deployed:.2f} + "
            f"ordem US$ {amount_usd:.2f} > US$ {basis.ticker_cap:.2f}"
        )


def _hv_dip_live_price(suggestion: Suggestion) -> tuple[float, str]:
    """Return (price, source) for hv_dip approve — live quote with fallback."""
    from app.services.market_data import MarketDataClient

    client = MarketDataClient()
    prices = client.fetch_last_prices([suggestion.ticker])
    live = prices.get(suggestion.ticker.upper())
    if live is not None and live > 0:
        return float(live), "tastytrade_last"
    return _limit_price(suggestion), "suggestion_entry"


def _hv_dip_limit_with_slippage(live_price: float) -> float:
    slip = float(settings.hv_dip_approve_slippage_pct or 0.5)
    return round(live_price * (1.0 + slip / 100.0), 2)


def create_order_from_suggestion(
    db: Session,
    suggestion: Suggestion,
    *,
    acted_by_user_id: str | None = None,
    human_approved: bool = False,
    amount_usd: float | None = None,
) -> Order:
    account = db.get(InvestmentAccount, suggestion.account_id)
    if not account:
        raise ValueError("Account not found")

    existing = (
        db.query(Order).filter(Order.suggestion_id == suggestion.id).order_by(Order.created_at.desc()).first()
    )
    if existing and existing.status not in (OrderStatus.rejected,):
        return existing

    kind = _strategy_kind(suggestion)
    live_source = "suggestion_entry"
    if kind == StrategyKind.hv_dip:
        price, live_source = _hv_dip_live_price(suggestion)
    else:
        price = _limit_price(suggestion)
    if amount_usd is not None and amount_usd > 0:
        amount = float(amount_usd)
    else:
        amount = float(suggestion.proposed_amount_brl or account.max_ticket_brl)

    if kind == StrategyKind.hv_dip and amount_usd is not None:
        from app.services.approve_options import validate_approve_amount

        validate_approve_amount(db, account, suggestion, amount)

    if kind == StrategyKind.swing:
        assert_swing_guards(db, account, suggestion, amount_brl=amount)
    elif kind == StrategyKind.hv_dip:
        # Auto path must pass human_approved=False → Review blocks
        assert_hv_dip_guards(
            db,
            account,
            suggestion,
            amount_usd=amount,
            human_approved=human_approved or acted_by_user_id is not None,
        )

    fractional = (account.broker_code or "").lower() == "tastytrade"
    if kind == StrategyKind.hv_dip:
        # Whole-lot (Quick Target): the engine computes the share count via
        # equal-risk sizing and stores it in metrics; reuse it so a float
        # rounding in `_quantity` can't drop a share.
        stored_qty = int((suggestion.metrics or {}).get("quantity") or 0)
        qty = float(stored_qty) if stored_qty > 0 else _quantity(amount, price, fractional=fractional)
    else:
        qty = _quantity(amount, price, fractional=fractional)
    limit_price = price
    if kind == StrategyKind.hv_dip and qty >= 1.0:
        limit_price = _hv_dip_limit_with_slippage(price)
    mode = account.execution_mode
    if not isinstance(mode, ExecutionMode):
        mode = ExecutionMode(str(mode))

    order = Order(
        account_id=account.id,
        suggestion_id=suggestion.id,
        ticker=suggestion.ticker,
        strategy_kind=kind,
        side=OrderSide.buy,
        quantity=qty,
        amount_brl=round(qty * limit_price, 2) if qty else amount,
        limit_price=limit_price,
        status=OrderStatus.queued,
        broker=account.broker_code or "inter",
        execution_mode=mode,
        acted_by_user_id=acted_by_user_id,
        execution_payload={
            "approve_live_price": price if kind == StrategyKind.hv_dip else None,
            "approve_live_source": live_source if kind == StrategyKind.hv_dip else None,
            "approve_at": datetime.now(timezone.utc).isoformat() if kind == StrategyKind.hv_dip else None,
        },
    )
    db.add(order)
    db.flush()

    if qty <= 0:
        ccy = "US$" if kind == StrategyKind.hv_dip else "R$"
        order.status = OrderStatus.rejected
        order.error_message = (
            f"Valor {ccy} {amount:.2f} insuficiente para ordem a {ccy} {limit_price:.2f}"
        )
        db.flush()
        return order

    adapter = get_broker_adapter(account)
    result = adapter.submit_order(order)
    order.status = result.status
    order.broker_order_id = result.broker_order_id
    order.error_message = result.error_message
    order.execution_payload = result.execution_payload or {}
    if result.status == OrderStatus.filled:
        order.filled_price = result.filled_price or order.limit_price
        order.filled_at = datetime.now(timezone.utc)
        open_position_from_fill(db, order, suggestion)
    db.flush()
    return order


def mark_order_filled(
    db: Session,
    order: Order,
    *,
    user_id: str,
    filled_price: float | None = None,
) -> Order:
    if order.execution_mode != ExecutionMode.live and str(order.execution_mode) != "live":
        raise ValueError("mark-filled only allowed in live mode")
    if order.status not in (OrderStatus.awaiting_broker, OrderStatus.submitted, OrderStatus.queued):
        raise ValueError("Order cannot be marked filled in current status")
    order.status = OrderStatus.filled
    order.filled_price = filled_price if filled_price is not None else order.limit_price
    order.filled_at = datetime.now(timezone.utc)
    order.acted_by_user_id = user_id
    payload = dict(order.execution_payload or {})
    payload["manual_fill"] = True
    order.execution_payload = payload
    sug = db.get(Suggestion, order.suggestion_id)
    open_position_from_fill(db, order, sug)
    db.flush()
    return order


def mark_order_cancelled(db: Session, order: Order, *, user_id: str) -> Order:
    if order.status in (OrderStatus.filled, OrderStatus.cancelled, OrderStatus.rejected):
        raise ValueError("Order already terminal")
    account = db.get(InvestmentAccount, order.account_id)
    adapter = get_broker_adapter(account) if account else None
    if adapter:
        result = adapter.cancel_order(order)
        if result.error_message and result.status != OrderStatus.cancelled:
            raise ValueError(result.error_message)
        order.status = result.status
        order.execution_payload = result.execution_payload or order.execution_payload
        if result.error_message:
            payload = dict(order.execution_payload or {})
            payload["cancel_warning"] = result.error_message
            order.execution_payload = payload
    else:
        order.status = OrderStatus.cancelled
    order.acted_by_user_id = user_id
    db.flush()
    return order
