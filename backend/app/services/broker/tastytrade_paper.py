"""tastytrade sandbox/live paper broker adapter for NM USD desk."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from uuid import uuid4

from app.domain.models import Order, OrderStatus
from app.services.broker.base import BrokerResult
from app.services.fractional_cache import mark_fractional_blocked
from app.services.tastytrade_client import AmbiguousOrderSubmit, DryRunRejected, TastytradeClient

logger = logging.getLogger("fiidesk.tastytrade.broker")


def _err_text(exc: Exception) -> str:
    return str(exc).lower()


def _fractional_blocked(err: str) -> bool:
    return (
        "fractional" in err
        or "fractional_trading_invalid_symbol" in err
        or "preflight_check_failure" in err
    )


def _reject_unaffordable_whole_share(order: Order, *, price: float, notional: float) -> BrokerResult:
    mark_fractional_blocked(order.ticker)
    return BrokerResult(
        status=OrderStatus.rejected,
        error_message=(
            f"{order.ticker}: corretora não aceita fractional neste ticker; "
            f"1 ação = US$ {price:.2f} > ticket US$ {notional:.2f}"
        ),
    )


def ensure_client_order_id(order: Order) -> str:
    payload = dict(order.execution_payload or {})
    cid = payload.get("client_order_id")
    if not cid:
        cid = str(uuid4())
        payload["client_order_id"] = cid
        order.execution_payload = payload
    return str(cid)


def _merge_payload(order: Order, extra: dict) -> dict:
    prev = dict(order.execution_payload or {})
    cid = prev.get("client_order_id")
    out = {**prev, **extra}
    if cid and not out.get("client_order_id"):
        out["client_order_id"] = cid
    return out


def _parse_order_response(data: dict, order: Order, *, mode: str) -> BrokerResult:
    order_obj = data.get("data", data)
    if isinstance(order_obj, dict) and "order" in order_obj:
        order_obj = order_obj["order"]
    if not isinstance(order_obj, dict):
        order_obj = {}

    status_raw = str(order_obj.get("status") or "").lower()
    broker_id = str(order_obj.get("id") or order_obj.get("order-id") or "")
    legs = order_obj.get("legs") or []
    has_fills = False
    if legs and isinstance(legs[0], dict):
        fills = legs[0].get("fills") or []
        has_fills = bool(fills)
    filled = status_raw in ("filled", "partially_filled", "closed") or has_fills
    fill_px: float | None = order.limit_price
    if legs and isinstance(legs[0], dict):
        fills = legs[0].get("fills") or []
        if fills and isinstance(fills[0], dict) and fills[0].get("fill-price") is not None:
            fill_px = fills[0]["fill-price"]
        leg_qty = legs[0].get("quantity")
        if leg_qty is not None:
            try:
                order.quantity = float(leg_qty)
            except (TypeError, ValueError):
                pass

    return BrokerResult(
        status=OrderStatus.filled if filled else OrderStatus.submitted,
        broker_order_id=broker_id or f"TT-{uuid4().hex[:10].upper()}",
        filled_price=float(fill_px) if fill_px is not None else None,
        execution_payload=_merge_payload(
            order,
            {
                "mode": mode,
                "tastytrade": data,
                "submitted_at": datetime.now(timezone.utc).isoformat(),
            },
        ),
    )


def _parse_complex_order_response(data: dict, order: Order, *, mode: str) -> BrokerResult:
    """Parse an OCO complex-order response into a resting (submitted) result.

    The response nests `data` with a `group` and an `orders` array (the two legs).
    We surface the first leg id as `broker_order_id` and stash the full payload +
    leg ids in `execution_payload` for later reconcile.
    """
    outer = data.get("data", data)
    if isinstance(outer, dict) and "order" in outer:
        outer = outer["order"]
    group = {}
    legs: list = []
    if isinstance(outer, dict):
        group = outer.get("group") or {}
        legs = outer.get("orders") or []
        if not legs and isinstance(group, dict):
            legs = group.get("orders") or []
    if not isinstance(legs, list):
        legs = []

    group_id = ""
    leg_ids: list[str] = []
    if isinstance(group, dict):
        group_id = str(group.get("id") or group.get("order-id") or "")
    for leg in legs:
        if isinstance(leg, dict):
            lid = str(leg.get("id") or leg.get("order-id") or "")
            if lid:
                leg_ids.append(lid)

    broker_id = leg_ids[0] if leg_ids else group_id or f"TT-OCO-{uuid4().hex[:10].upper()}"
    return BrokerResult(
        status=OrderStatus.submitted,
        broker_order_id=broker_id,
        execution_payload=_merge_payload(
            order,
            {
                "mode": mode,
                "tastytrade": data,
                "oco_group_id": group_id,
                "oco_leg_ids": leg_ids,
                "submitted_at": datetime.now(timezone.utc).isoformat(),
            },
        ),
    )


def resolve_hv_dip_submit(
    order: Order,
    *,
    live_price: float,
    slippage_pct: float,
) -> tuple[float, float, str]:
    """Choose limit price, quantity, and submit mode hint for hv_dip hybrid execution."""
    notional = float(order.amount_brl or 0) or round(float(order.quantity) * live_price, 2)
    qty = float(order.quantity)
    if qty < 1.0:
        return live_price, qty, "notional_market"
    limit = round(live_price * (1.0 + slippage_pct / 100.0), 2)
    whole = math.floor(qty)
    if whole >= 1:
        return limit, whole, "limit_live"
    if live_price <= notional + 0.01:
        return live_price, 1.0, "limit_one_share"
    return live_price, qty, "reject_whole_share"


class TastytradeBrokerAdapter:
    def __init__(self, *, live: bool = False) -> None:
        self.live = live

    def _client(self) -> TastytradeClient:
        return TastytradeClient(live=self.live)

    def submit_order(self, order: Order) -> BrokerResult:
        client = self._client()
        if not client.configured():
            return BrokerResult(
                status=OrderStatus.rejected,
                error_message="tastytrade não configurado (client/refresh/account)",
            )
        if order.limit_price <= 0:
            return BrokerResult(
                status=OrderStatus.rejected,
                error_message="Invalid limit_price",
            )
        qty = float(order.quantity)
        notional = float(order.amount_brl or 0) or round(qty * float(order.limit_price), 2)
        if notional < 1.0 and qty <= 0:
            return BrokerResult(
                status=OrderStatus.rejected,
                error_message="Invalid quantity or notional",
            )

        mode = "tastytrade" if self.live else "tastytrade_sandbox"
        cid = ensure_client_order_id(order)
        payload = order.execution_payload or {}
        live_px = payload.get("approve_live_price")
        try:
            if live_px is not None and float(live_px) > 0:
                from app.config import get_settings

                slip = float(get_settings().hv_dip_approve_slippage_pct or 0.5)
                limit, submit_qty, hint = resolve_hv_dip_submit(
                    order,
                    live_price=float(live_px),
                    slippage_pct=slip,
                )
                order.limit_price = limit
                order.quantity = submit_qty
                payload = {**payload, "hv_dip_submit_mode": hint}
                order.execution_payload = payload
            qty = float(order.quantity)
            notional = float(order.amount_brl or 0) or round(qty * float(order.limit_price), 2)
            # Sub-1-share NM tickets: notional market (fractional by dollar amount).
            if qty < 1.0:
                try:
                    data = client.submit_equity_notional_market_buy(
                        symbol=order.ticker,
                        notional_usd=notional,
                        client_order_id=cid,
                    )
                except Exception as exc:
                    err = _err_text(exc)
                    price = float(order.limit_price)
                    if _fractional_blocked(err) and price <= notional + 0.01:
                        data = client.submit_equity_limit_buy(
                            symbol=order.ticker,
                            quantity=1,
                            limit_price=price,
                            client_order_id=cid,
                        )
                    elif _fractional_blocked(err):
                        mark_fractional_blocked(order.ticker)
                        return _reject_unaffordable_whole_share(
                            order, price=price, notional=notional
                        )
                    else:
                        raise
                return _parse_order_response(data, order, mode=mode)

            # Whole-share path; retry without fractional if symbol blocks it.
            submit_qty = qty
            if abs(submit_qty - round(submit_qty)) > 1e-6:
                submit_qty = math.floor(submit_qty)
                if submit_qty < 1:
                    data = client.submit_equity_notional_market_buy(
                        symbol=order.ticker,
                        notional_usd=notional,
                        client_order_id=cid,
                    )
                    return _parse_order_response(data, order, mode=mode)
            try:
                data = client.submit_equity_limit_buy(
                    symbol=order.ticker,
                    quantity=submit_qty,
                    limit_price=float(order.limit_price),
                    client_order_id=cid,
                )
            except Exception as exc:
                err = _err_text(exc)
                if _fractional_blocked(err) and submit_qty >= 1:
                    whole = math.floor(submit_qty)
                    if whole >= 1:
                        data = client.submit_equity_limit_buy(
                            symbol=order.ticker,
                            quantity=whole,
                            limit_price=float(order.limit_price),
                            client_order_id=cid,
                        )
                    else:
                        raise
                elif _fractional_blocked(err):
                    price = float(order.limit_price)
                    if price <= notional + 0.01:
                        data = client.submit_equity_limit_buy(
                            symbol=order.ticker,
                            quantity=1,
                            limit_price=price,
                            client_order_id=cid,
                        )
                    else:
                        return _reject_unaffordable_whole_share(
                            order, price=price, notional=notional
                        )
                else:
                    raise
            return _parse_order_response(data, order, mode=mode)
        except DryRunRejected as exc:
            logger.info("tastytrade dry-run rejected %s: %s", order.ticker, exc)
            return BrokerResult(
                status=OrderStatus.rejected,
                error_message=f"dry-run: {str(exc)[:400]}",
            )
        except AmbiguousOrderSubmit as exc:
            logger.warning("tastytrade submit ambiguous (no second POST): %s", exc)
            return BrokerResult(
                status=OrderStatus.submitted,
                broker_order_id=None,
                error_message=f"submit ambiguous (HTTP 502/503): {str(exc)[:300]}",
                execution_payload=_merge_payload(
                    order, {"mode": mode, "ambiguous_submit": True}
                ),
            )
        except Exception as exc:
            logger.exception("tastytrade submit failed")
            return BrokerResult(
                status=OrderStatus.rejected,
                error_message=str(exc)[:500],
            )

    def replace_open_limit(self, order: Order, *, limit_price: float) -> BrokerResult:
        """PUT the live order when editable+cancellable. Never a second POST."""
        from app.services.tastytrade_reconcile import _unwrap_order_payload

        remote = self.get_remote_order(order)
        if not isinstance(remote, dict):
            return BrokerResult(
                status=order.status,
                broker_order_id=order.broker_order_id,
                error_message="replace skipped: no remote payload",
            )
        if remote.get("editable") is not True or remote.get("cancellable") is not True:
            return BrokerResult(
                status=order.status,
                broker_order_id=order.broker_order_id,
                error_message=(
                    f"replace skipped: editable={remote.get('editable')} "
                    f"cancellable={remote.get('cancellable')}"
                ),
            )
        client = self._client()
        action = "Buy to Open"
        if str(getattr(order.side, "value", order.side)).lower().startswith("sell"):
            action = "Sell to Close"
        try:
            data = client.replace_equity_limit(
                str(order.broker_order_id),
                symbol=order.ticker,
                quantity=float(order.quantity),
                limit_price=float(limit_price),
                action=action,
            )
        except Exception as exc:
            logger.warning("tastytrade replace failed %s: %s", order.ticker, exc)
            return BrokerResult(
                status=order.status,
                broker_order_id=order.broker_order_id,
                error_message=f"replace failed: {str(exc)[:300]}",
            )
        payload = _unwrap_order_payload(data) or data
        order.limit_price = round(float(limit_price), 2)
        merged = _merge_payload(order, {"replaced": True, "tastytrade": data})
        order.execution_payload = merged
        return BrokerResult(
            status=order.status,
            broker_order_id=order.broker_order_id,
            execution_payload=merged,
        )

    def get_remote_order(self, order: Order) -> dict | None:
        """GET /orders/{id} for cancellable checks. Auth failures return None."""
        from app.services.tastytrade_client import TastytradeHttpError
        from app.services.tastytrade_reconcile import _is_auth_error, _unwrap_order_payload

        client = self._client()
        if not client.configured() or not order.broker_order_id:
            return None
        try:
            raw = client.get_order(str(order.broker_order_id))
        except TastytradeHttpError as exc:
            if _is_auth_error(exc):
                logger.error(
                    "tastytrade GET order token/auth failed %s %s HTTP %s: %s",
                    order.ticker,
                    order.broker_order_id,
                    exc.status_code,
                    exc,
                )
                return None
            logger.warning(
                "tastytrade GET order %s %s HTTP %s: %s",
                order.ticker,
                order.broker_order_id,
                exc.status_code,
                exc,
            )
            return None
        except Exception as exc:
            if _is_auth_error(exc):
                logger.error(
                    "tastytrade GET order token/auth failed %s %s: %s",
                    order.ticker,
                    order.broker_order_id,
                    exc,
                )
                return None
            logger.warning(
                "tastytrade GET order %s %s failed: %s",
                order.ticker,
                order.broker_order_id,
                exc,
            )
            return None
        payload = _unwrap_order_payload(raw) or (raw if isinstance(raw, dict) else None)
        return payload if isinstance(payload, dict) else None

    def cancel_order(self, order: Order) -> BrokerResult:
        client = self._client()
        if not client.configured() or not order.broker_order_id:
            return BrokerResult(
                status=OrderStatus.cancelled,
                broker_order_id=order.broker_order_id,
                execution_payload={"mode": "tastytrade_sim", "cancelled": True},
            )
        mode = (order.execution_payload or {}).get("mode") or (
            "tastytrade" if self.live else "tastytrade_sandbox"
        )
        try:
            client.cancel_order(order.broker_order_id)
            return BrokerResult(
                status=OrderStatus.cancelled,
                broker_order_id=order.broker_order_id,
                execution_payload={"mode": mode, "cancelled": True},
            )
        except Exception as exc:
            logger.exception("tastytrade cancel failed")
            return BrokerResult(
                status=OrderStatus.submitted,
                broker_order_id=order.broker_order_id,
                error_message=f"Falha ao cancelar na tastytrade: {str(exc)[:300]}",
            )

    def sell(self, order: Order) -> BrokerResult:
        """Sell to Close (limit when limit_price set, else market)."""
        client = self._client()
        if not client.configured():
            return BrokerResult(
                status=OrderStatus.rejected,
                error_message="tastytrade não configurado (client/refresh/account)",
            )
        qty = float(order.quantity)
        if qty <= 0:
            return BrokerResult(status=OrderStatus.rejected, error_message="Invalid quantity")
        mode = "tastytrade" if self.live else "tastytrade_sandbox"
        cid = ensure_client_order_id(order)
        try:
            limit = float(order.limit_price or 0)
            if limit > 0:
                data = client.submit_equity_limit_sell(
                    symbol=order.ticker,
                    quantity=qty,
                    limit_price=limit,
                    client_order_id=cid,
                )
            else:
                data = client.submit_equity_market_sell(
                    symbol=order.ticker, quantity=qty, client_order_id=cid
                )
            return _parse_order_response(data, order, mode=mode)
        except AmbiguousOrderSubmit as exc:
            logger.warning("tastytrade sell ambiguous (no second POST): %s", exc)
            return BrokerResult(
                status=OrderStatus.submitted,
                broker_order_id=None,
                error_message=f"sell ambiguous (HTTP 502/503): {str(exc)[:300]}",
                execution_payload=_merge_payload(
                    order, {"mode": mode, "ambiguous_submit": True}
                ),
            )
        except Exception as exc:
            logger.exception("tastytrade sell failed")
            return BrokerResult(status=OrderStatus.rejected, error_message=str(exc)[:500])

    def place_bracket(self, order: Order) -> BrokerResult:
        """Place an OCO bracket (target limit + stop) closing an open position.

        Legs rest GTC at the broker; submission is not a fill. Target/stop come
        from execution_payload (hv_dip) or limit_price / stop_price fallbacks.
        """
        client = self._client()
        if not client.configured():
            return BrokerResult(
                status=OrderStatus.rejected,
                error_message="tastytrade não configurado (client/refresh/account)",
            )
        payload = order.execution_payload or {}
        qty = float(order.quantity)
        target = payload.get("target_price")
        if target is None:
            target = order.limit_price
        stop = payload.get("stop_trigger")
        if stop is None:
            stop = payload.get("stop_price")
        try:
            target_f = float(target or 0)
            stop_f = float(stop or 0)
        except (TypeError, ValueError):
            target_f, stop_f = 0.0, 0.0
        if qty <= 0 or target_f <= 0 or stop_f <= 0:
            return BrokerResult(
                status=OrderStatus.rejected,
                error_message="bracket sem target_price/stop_trigger",
            )
        mode = "tastytrade" if self.live else "tastytrade_sandbox"
        cid = ensure_client_order_id(order)
        try:
            data = client.submit_oco_bracket(
                symbol=order.ticker,
                quantity=qty,
                target_price=target_f,
                stop_trigger=stop_f,
                client_order_id=cid,
            )
            return _parse_complex_order_response(data, order, mode=mode)
        except AmbiguousOrderSubmit as exc:
            logger.warning("tastytrade bracket ambiguous (no second POST): %s", exc)
            return BrokerResult(
                status=OrderStatus.submitted,
                broker_order_id=None,
                error_message=f"bracket ambiguous (HTTP 502/503): {str(exc)[:300]}",
                execution_payload=_merge_payload(
                    order, {"mode": mode, "ambiguous_submit": True}
                ),
            )
        except Exception as exc:
            logger.exception("tastytrade bracket failed")
            return BrokerResult(
                status=OrderStatus.rejected,
                error_message=str(exc)[:500],
            )
