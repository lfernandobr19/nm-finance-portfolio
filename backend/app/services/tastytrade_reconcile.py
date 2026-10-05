"""Reconcile submitted tastytrade orders against the broker (paper + live).

Polls GET /orders/{id}. Live / Routed / In Flight stay working unless
remaining-quantity is 0 with fills. Terminal Filled opens the local position;
Rejected / Canceled / Expired free the working lock. Fallback chain: GET id →
/orders/live → GET /orders history. Auth failures skip (do not expire).

Paper/sandbox orders stuck in `submitted` past ``order_stuck_expire_hours`` are
cancelled (best-effort at the broker) and freed, so a dead sandbox token can
never freeze the rotation. Live orders are never auto-expired on a token gap.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.domain.models import (
    ExecutionMode,
    InvestmentAccount,
    Order,
    OrderSide,
    OrderStatus,
    Suggestion,
    SuggestionStatus,
)
from app.services.positions import close_position, open_position_from_fill
from app.services.tastytrade_client import TastytradeClient, TastytradeHttpError

logger = logging.getLogger("fiidesk.tastytrade.reconcile")

_WORKING_REMOTE = frozenset(
    {
        "live",
        "routed",
        "in flight",
        "in-flight",
        "received",
        "pending",
        "cancel requested",
        "replace requested",
        "contingent",
    }
)
_FILLED_REMOTE = frozenset({"filled", "partially filled", "partially_filled", "closed"})
_CANCELLED_REMOTE = frozenset(
    {"canceled", "cancelled", "expired", "removed", "partially removed", "partially_removed"}
)
_REJECTED_REMOTE = frozenset({"rejected"})
_AUTH_MARKERS = (
    "not a customer",
    "not a tastytrade customer",
    "unauthorized",
    "invalid_token",
    "invalid token",
    "invalid refresh",
    "expired token",
)


def _norm_status(raw: str) -> str:
    return " ".join(str(raw or "").replace("_", " ").replace("-", " ").lower().split())


def _has_fills(payload: dict[str, Any]) -> bool:
    legs = payload.get("legs") or []
    if not isinstance(legs, list):
        return bool(payload.get("fills"))
    for leg in legs:
        if isinstance(leg, dict) and leg.get("fills"):
            return True
    fills = payload.get("fills")
    return bool(fills)


def _remaining_quantity(payload: dict[str, Any]) -> float | None:
    """Sum remaining-quantity across legs when the field is present."""
    found = False
    total = 0.0
    if payload.get("remaining-quantity") is not None or payload.get("remaining_quantity") is not None:
        found = True
        try:
            total = float(payload.get("remaining-quantity") or payload.get("remaining_quantity") or 0)
        except (TypeError, ValueError):
            total = 0.0
    legs = payload.get("legs") or []
    if isinstance(legs, list):
        leg_total = 0.0
        leg_found = False
        for leg in legs:
            if not isinstance(leg, dict):
                continue
            raw = leg.get("remaining-quantity")
            if raw is None:
                raw = leg.get("remaining_quantity")
            if raw is None:
                continue
            leg_found = True
            try:
                leg_total += float(raw)
            except (TypeError, ValueError):
                continue
        if leg_found:
            return leg_total
    return total if found else None


def classify_remote_status(payload: dict[str, Any]) -> str:
    """Map a Tastytrade order payload to filled / working / cancelled / rejected."""
    raw = _norm_status(payload.get("status") or "")
    fills = _has_fills(payload)
    remaining = _remaining_quantity(payload)
    if raw in _CANCELLED_REMOTE:
        return "cancelled"
    if raw in _REJECTED_REMOTE:
        return "rejected"
    if remaining is not None and remaining > 0 and raw not in _FILLED_REMOTE:
        return "working"
    if raw in _FILLED_REMOTE:
        return "filled"
    if remaining is not None and remaining <= 0 and fills:
        return "filled"
    if raw in _WORKING_REMOTE:
        return "working"
    if fills:
        return "filled"
    return "working"


def _unwrap_order_payload(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    inner = data.get("data", data)
    if isinstance(inner, dict) and "order" in inner and isinstance(inner["order"], dict):
        inner = inner["order"]
    if not isinstance(inner, dict):
        return None
    if inner.get("id") or inner.get("order-id") or inner.get("status") or inner.get("legs"):
        return inner
    return None


def _client_order_id(order: Order) -> str | None:
    payload = order.execution_payload or {}
    cid = (
        payload.get("client_order_id")
        or payload.get("external-identifier")
        or payload.get("ext-client-order-id")
    )
    return str(cid) if cid else None


def _match_remote_order(
    items: list[dict[str, Any]],
    *,
    broker_order_id: str | None,
    client_order_id: str | None,
) -> dict[str, Any] | None:
    want_id = str(broker_order_id) if broker_order_id else ""
    want_cid = str(client_order_id) if client_order_id else ""
    for item in items:
        payload = _unwrap_order_payload(item) or item
        oid = str(payload.get("id") or payload.get("order-id") or "")
        ext = str(
            payload.get("external-identifier")
            or payload.get("ext-client-order-id")
            or payload.get("client-order-id")
            or payload.get("client_order_id")
            or ""
        )
        if want_id and oid == want_id:
            return payload
        if want_cid and ext == want_cid:
            return payload
    return None


def _try_list(fetch, *, label: str, ticker: str, broker_id: str | None) -> tuple[list[dict[str, Any]] | None, bool]:
    """Run a list fetch. Returns (items, auth_failed). items is None on transport error."""
    try:
        return fetch(), False
    except TastytradeHttpError as exc:
        if _is_auth_error(exc):
            logger.error(
                "tastytrade reconcile token/auth failed %s %s HTTP %s: %s",
                label,
                ticker,
                exc.status_code,
                exc,
            )
            return None, True
        logger.warning(
            "tastytrade %s failed for %s %s HTTP %s: %s",
            label,
            ticker,
            broker_id,
            exc.status_code,
            exc,
        )
        return None, False
    except Exception as exc:
        if _is_auth_error(exc):
            logger.error("tastytrade reconcile token/auth failed %s %s: %s", label, ticker, exc)
            return None, True
        logger.warning("tastytrade %s failed for %s %s: %s", label, ticker, broker_id, exc)
        return None, False


def _is_auth_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    code = getattr(exc, "status_code", None)
    if code in (401, 403):
        return True
    return any(marker in text for marker in _AUTH_MARKERS)


def _client_for_order(order: Order) -> TastytradeClient:
    payload = order.execution_payload or {}
    mode = str(payload.get("mode") or "")
    if mode == "tastytrade":
        return TastytradeClient(live=True)
    if mode == "tastytrade_sandbox":
        return TastytradeClient(live=False)
    mode_val = order.execution_mode
    if hasattr(mode_val, "value"):
        mode_val = mode_val.value
    return TastytradeClient(live=str(mode_val) == ExecutionMode.live.value)


def _order_status(order: Order) -> dict | None:
    """Broker payload for this order, or None when the lookup must be skipped.

    GET /{id} first (when we have a broker id). On failure, GET /orders/live
    then GET /orders history, matching by broker id or ext-client-order-id.
    A successful list that does not contain the order is inferred Expired.
    Auth failures return None so we do not mark expired on a dead token.
    """
    client = _client_for_order(order)
    if not client.configured():
        logger.warning(
            "tastytrade reconcile skip %s %s: client not configured",
            order.ticker,
            order.broker_order_id,
        )
        return None

    broker_id = str(order.broker_order_id) if order.broker_order_id else None
    client_id = _client_order_id(order)
    if not broker_id and not client_id:
        logger.warning("tastytrade reconcile skip %s: no broker or client order id", order.ticker)
        return None

    if broker_id:
        try:
            raw = client.get_order(broker_id)
            payload = _unwrap_order_payload(raw) or raw
            if isinstance(payload, dict) and (
                payload.get("status") or payload.get("legs") or payload.get("id")
            ):
                return payload
        except TastytradeHttpError as exc:
            if _is_auth_error(exc):
                logger.error(
                    "tastytrade reconcile token/auth failed GET %s %s HTTP %s: %s",
                    order.ticker,
                    broker_id,
                    exc.status_code,
                    exc,
                )
                return None
            logger.warning(
                "tastytrade GET order %s %s HTTP %s: %s — trying lists",
                order.ticker,
                broker_id,
                exc.status_code,
                exc,
            )
        except Exception as exc:
            if _is_auth_error(exc):
                logger.error(
                    "tastytrade reconcile token/auth failed GET %s %s: %s",
                    order.ticker,
                    broker_id,
                    exc,
                )
                return None
            logger.warning(
                "tastytrade GET order %s %s failed: %s — trying lists",
                order.ticker,
                broker_id,
                exc,
            )

    live_items, live_auth = _try_list(
        client.list_live_orders,
        label="live list",
        ticker=order.ticker,
        broker_id=broker_id,
    )
    if live_auth:
        return None
    if live_items is not None:
        match = _match_remote_order(
            live_items, broker_order_id=broker_id, client_order_id=client_id
        )
        if match is not None:
            logger.info(
                "tastytrade reconcile %s %s matched via /orders/live",
                order.ticker,
                broker_id or client_id,
            )
            return match

    hist_items, hist_auth = _try_list(
        lambda: client.list_orders(start_at=datetime.now(timezone.utc) - timedelta(days=2)),
        label="order history",
        ticker=order.ticker,
        broker_id=broker_id,
    )
    if hist_auth:
        return None
    if hist_items is not None:
        match = _match_remote_order(
            hist_items, broker_order_id=broker_id, client_order_id=client_id
        )
        if match is not None:
            logger.info(
                "tastytrade reconcile %s %s matched via /orders history",
                order.ticker,
                broker_id or client_id,
            )
            return match

    if live_items is None and hist_items is None:
        return None

    logger.info(
        "tastytrade reconcile %s %s not in live/history → expired",
        order.ticker,
        broker_id or client_id,
    )
    return {
        "id": broker_id,
        "status": "Expired",
        "inferred_expired": True,
        "ext-client-order-id": client_id,
        "external-identifier": client_id,
    }


def _position_as_fill(order: Order) -> dict | None:
    """If the broker already shows an equity position, treat submitted as filled."""
    client = _client_for_order(order)
    if not client.configured():
        return None
    items, auth = _try_list(
        client.list_positions,
        label="positions",
        ticker=order.ticker,
        broker_id=order.broker_order_id,
    )
    if auth or not items:
        return None
    want = (order.ticker or "").upper()
    for item in items:
        inner = item if isinstance(item, dict) else {}
        if isinstance(inner.get("data"), dict):
            inner = inner["data"]
        inst = inner.get("instrument") if isinstance(inner.get("instrument"), dict) else {}
        sym = str(
            inner.get("symbol")
            or inner.get("underlying-symbol")
            or inst.get("symbol")
            or ""
        ).upper()
        if sym != want:
            continue
        try:
            qty = float(inner.get("quantity") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        if qty <= 0:
            continue
        px = inner.get("average-open-price") or inner.get("close-price") or order.limit_price
        try:
            fill_px = float(px)
        except (TypeError, ValueError):
            fill_px = float(order.limit_price or 0)
        return {
            "id": order.broker_order_id,
            "status": "Filled",
            "from_position": True,
            "legs": [
                {
                    "remaining-quantity": 0,
                    "quantity": qty,
                    "fills": [{"fill-price": fill_px}],
                }
            ],
        }
    return None


def _fill_price(order: Order, payload: dict) -> float:
    legs = payload.get("legs") or []
    if legs and isinstance(legs[0], dict):
        fills = legs[0].get("fills") or []
        if fills and isinstance(fills[0], dict) and fills[0].get("fill-price") is not None:
            try:
                return float(fills[0]["fill-price"])
            except (TypeError, ValueError):
                pass
        qty = legs[0].get("quantity")
        if qty is not None:
            try:
                order.quantity = float(qty)
            except (TypeError, ValueError):
                pass
    return float(order.filled_price or order.limit_price or 0)


def _refetch_filled_without_fills(order: Order, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Filled can land before fills are written — one re-GET, then use local limit."""
    broker_id = str(order.broker_order_id or payload.get("id") or payload.get("order-id") or "")
    if not broker_id:
        return payload
    client = _client_for_order(order)
    try:
        raw = client.get_order(broker_id)
    except Exception as exc:
        logger.warning("tastytrade re-GET filled %s %s failed: %s", order.ticker, broker_id, exc)
        return payload
    inner = _unwrap_order_payload(raw) or raw
    if isinstance(inner, dict):
        return inner
    return payload


def sync_live_tastytrade_balances(db: Session) -> int:
    """Mirror the live broker ``cash-balance`` into the live account's ledger.

    Ensures the displayed value tracks the actual deposit. Returns the number of
    live accounts updated. Never mutates anything when live creds are missing.
    """
    live = TastytradeClient(live=True)
    if not live.configured():
        return 0

    accounts = (
        db.query(InvestmentAccount)
        .filter(
            InvestmentAccount.broker_code == "tastytrade",
            InvestmentAccount.execution_mode == ExecutionMode.live,
        )
        .all()
    )
    updated = 0
    for account in accounts:
        cash = live.fetch_cash_balance()
        if cash is None:
            continue
        cash = round(cash, 2)
        if (
            abs((account.cash_usd or 0.0) - cash) < 0.005
            and abs((account.hv_dip_equity_usd or 0.0) - cash) < 0.005
        ):
            continue
        account.cash_usd = cash
        account.hv_dip_equity_usd = cash
        updated += 1
        logger.info("live balance mirrored %s cash_usd=%s", account.name, cash)
    if updated:
        db.flush()
    return updated


def _order_age_hours(order: Order) -> float | None:
    created = order.created_at
    if created is None:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - created).total_seconds() / 3600.0


def _is_live_order(order: Order) -> bool:
    payload = order.execution_payload or {}
    if payload.get("mode") == "tastytrade":
        return True
    mode = order.execution_mode
    mode_val = mode.value if hasattr(mode, "value") else str(mode or "")
    return str(mode_val) == ExecutionMode.live.value


def _expire_stale_submitted(db: Session, order: Order, hours: float) -> bool:
    """Free a paper/sandbox order stuck past the expiry window.

    Day-TIF limit buys are dead after one session; the only risk of leaving them
    is a frozen rotation (working_order → replace-only, never re-buy). Best-effort
    cancel first so a reachable broker stays consistent, then mark locally. Live
    orders are never auto-expired here — a token gap could hide a real fill.
    """
    if _is_live_order(order):
        return False
    client = _client_for_order(order)
    broker_id = str(order.broker_order_id) if order.broker_order_id else None
    if client.configured() and broker_id:
        try:
            client.cancel_order(broker_id)
        except Exception as exc:
            logger.warning(
                "tastytrade stale-cancel %s %s failed: %s",
                order.ticker,
                broker_id,
                exc,
            )
    order.status = OrderStatus.cancelled
    order.error_message = (
        f"stale submitted: no broker confirmation for {hours:.1f}h "
        "(Day order auto-expired / sandbox unreachable)"
    )
    logger.warning(
        "tastytrade expire stale submitted %s %s age=%.1fh",
        order.ticker,
        broker_id or order.id[:8],
        hours,
    )
    return True


def _alert_if_stuck(db: Session, order: Order, hours: float) -> None:
    """Notify once if an order has been stuck in `submitted` too long."""
    payload = order.execution_payload or {}
    if payload.get("stuck_notified"):
        return
    from app.config import get_settings
    from app.services.notify import notify_order_stuck

    threshold = float(get_settings().order_stuck_alert_hours or 2.0)
    if hours < threshold:
        return
    try:
        notify_order_stuck(db, order=order, hours=hours)
        payload["stuck_notified"] = True
        order.execution_payload = payload
    except Exception:
        logger.exception("order stuck notify failed %s", order.id)


def reconcile_submitted_tastytrade_orders(db: Session) -> int:
    """Move `submitted` tastytrade orders to filled/rejected/cancelled. Returns updates."""
    from app.config import get_settings

    settings = get_settings()
    expire_hours = float(settings.order_stuck_expire_hours or 20.0)
    orders = (
        db.query(Order)
        .filter(
            Order.status.in_((OrderStatus.submitted, OrderStatus.awaiting_broker)),
            Order.broker.in_(("tastytrade", "tastytrade_sandbox")),
        )
        .all()
    )
    updated = 0
    for order in orders:
        payload_mode = (order.execution_payload or {}).get("mode")
        if payload_mode not in ("tastytrade", "tastytrade_sandbox") and (
            order.broker or ""
        ).lower() not in ("tastytrade", "tastytrade_sandbox"):
            continue
        age = _order_age_hours(order)
        if age is not None and age >= expire_hours:
            if _expire_stale_submitted(db, order, age):
                updated += 1
                continue
        elif age is not None:
            _alert_if_stuck(db, order, age)
        payload = _order_status(order)
        if not payload:
            continue
        kind = classify_remote_status(payload)
        if kind == "filled" and not _has_fills(payload):
            payload = _refetch_filled_without_fills(order, payload) or payload
            kind = classify_remote_status(payload)
        if kind == "working" or payload.get("inferred_expired"):
            pos_fill = _position_as_fill(order)
            if pos_fill is not None:
                payload = pos_fill
                kind = "filled"
        if payload.get("id") and not order.broker_order_id:
            order.broker_order_id = str(payload.get("id") or payload.get("order-id") or "")
        if kind == "working":
            logger.info(
                "tastytrade reconcile %s %s still %s",
                order.ticker,
                order.broker_order_id,
                payload.get("status"),
            )
            continue
        if kind == "filled":
            fill_px = _fill_price(order, payload)
            order.status = OrderStatus.filled
            order.filled_price = fill_px
            order.filled_at = datetime.now(timezone.utc)
            order.error_message = None
            updated += 1
            if order.side == OrderSide.sell and order.position_id:
                from app.domain.models import Position, PositionExitReason, PositionStatus

                pos = db.get(Position, order.position_id)
                if pos is not None and pos.status == PositionStatus.open:
                    try:
                        close_position(
                            db,
                            pos,
                            reason=PositionExitReason.manual,
                            manual_price=fill_px,
                            skip_broker_sell=True,
                        )
                    except ValueError as exc:
                        logger.warning(
                            "reconcile sell-fill close blocked %s: %s",
                            order.ticker,
                            exc,
                        )
            elif order.side != OrderSide.sell:
                sug = db.get(Suggestion, order.suggestion_id) if order.suggestion_id else None
                if sug is not None:
                    sug.status = SuggestionStatus.executed
                open_position_from_fill(db, order, sug)
            continue
        if kind == "cancelled":
            order.status = OrderStatus.cancelled
            inferred = payload.get("inferred_expired")
            order.error_message = (
                "expired: not in tastytrade live orders"
                if inferred
                else str(payload.get("status") or "cancelled")
            )
            updated += 1
            continue
        if kind == "rejected":
            order.status = OrderStatus.rejected
            order.error_message = str(
                payload.get("reject-reason")
                or payload.get("status")
                or "rejected"
            )
            updated += 1
    if updated:
        db.commit()
    return updated
