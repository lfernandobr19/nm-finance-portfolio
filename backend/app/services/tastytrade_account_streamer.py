"""tastytrade Account Streamer — Order events over the account websocket.

This is not DXLink. Context7 (streaming-account-data): connect with the OAuth
access token, heartbeat, then consume ``type: Order`` payloads that match GET
/orders. Fills enqueue ``job_tasty_reconcile`` with a stable ``_job_id``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

import websockets

from app.services.tastytrade_client import TastytradeClient, TastytradeHttpError
from app.services.tastytrade_reconcile import classify_remote_status, _is_auth_error, _unwrap_order_payload

logger = logging.getLogger("fiidesk.tastytrade.account_streamer")

TASTY_RECONCILE_JOB_ID = "tasty-reconcile"
TASTY_RECONCILE_JOB_NAME = "job_tasty_reconcile"
TASTY_RECONCILE_EXPIRES_SECONDS = 300
_HEARTBEAT_SECONDS = 20.0
_AUTH_MARKERS = (
    "not a customer",
    "not a tastytrade customer",
    "unauthorized",
    "invalid_token",
    "invalid token",
)


def connect_ack_ok(message: dict[str, Any] | None) -> bool:
    """True when the server acknowledged the connect action."""
    if not isinstance(message, dict):
        return False
    status = str(message.get("status") or "").lower()
    action = str(message.get("action") or "").lower()
    return status == "ok" and action == "connect"


def unwrap_order_event(message: dict[str, Any] | None) -> dict[str, Any] | None:
    """Extract the order payload from a websocket Order notification."""
    if not isinstance(message, dict):
        return None
    msg_type = str(message.get("type") or message.get("action") or "")
    if msg_type.lower() != "order":
        return None
    data = message.get("data")
    if isinstance(data, dict):
        return _unwrap_order_payload(data) or data
    return None


def classify_order_event(message: dict[str, Any] | None) -> tuple[str | None, bool]:
    """Map a streamer Order event to (kind, should_enqueue)."""
    payload = unwrap_order_event(message)
    if payload is None:
        return None, False
    kind = classify_remote_status(payload)
    return kind, kind in {"filled", "cancelled", "rejected"}


def stream_event_should_enqueue(message: dict[str, Any]) -> bool:
    """Order fill/cancel, CurrentPosition, or Balance → reconcile."""
    kind, should = classify_order_event(message)
    if should:
        return True
    raw = str(message.get("type") or message.get("action") or "").lower().replace("-", "").replace("_", "")
    return raw in {"currentposition", "balance", "accountbalance"}


async def enqueue_tasty_reconcile(*, redis: Any | None = None) -> bool:
    """Enqueue unique reconcile. Second call returns False while queued/running."""
    own = redis is None
    if own:
        from arq import create_pool
        from app.workers.arq_settings import redis_settings

        redis = await create_pool(redis_settings())
    try:
        job = await redis.enqueue_job(
            TASTY_RECONCILE_JOB_NAME,
            _job_id=TASTY_RECONCILE_JOB_ID,
            _expires=TASTY_RECONCILE_EXPIRES_SECONDS,
        )
        if job is None:
            logger.info("tastytrade reconcile already queued/running — skip duplicate")
            return False
        logger.info("tastytrade reconcile enqueued job_id=%s", TASTY_RECONCILE_JOB_ID)
        return True
    finally:
        if own:
            close = getattr(redis, "close", None)
            if close is not None:
                result = close(close_connection_pool=True)
                if asyncio.iscoroutine(result):
                    await result


class AccountStreamer:
    """Long-lived account websocket. Reconnects with backoff on drop or auth 400."""

    def __init__(
        self,
        *,
        client: TastytradeClient | None = None,
        live: bool = False,
        on_order: Callable[[dict[str, Any], str], Awaitable[None] | None] | None = None,
    ) -> None:
        self._tt = client or TastytradeClient(live=live)
        self._on_order = on_order
        self._stop = asyncio.Event()
        self._request_id = 0
        self._redis: Any | None = None

    def _next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        from arq import create_pool
        from app.workers.arq_settings import redis_settings

        self._redis = await create_pool(redis_settings())
        backoff = 2.0
        try:
            while not self._stop.is_set():
                try:
                    token = self._tt.access_token()
                    backoff = 2.0
                except Exception as exc:
                    if _is_auth_error(exc) or any(m in str(exc).lower() for m in _AUTH_MARKERS):
                        logger.error(
                            "tastytrade account streamer token/auth failed — backoff, not expiring orders: %s",
                            exc,
                        )
                    else:
                        logger.exception("tastytrade account streamer token failed")
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60.0)
                    continue
                try:
                    await self._connect_once(token)
                    backoff = 2.0
                except asyncio.CancelledError:
                    raise
                except TastytradeHttpError as exc:
                    if _is_auth_error(exc):
                        logger.error(
                            "tastytrade account streamer HTTP auth %s — backoff, not expiring: %s",
                            exc.status_code,
                            exc,
                        )
                    else:
                        logger.warning("tastytrade account streamer HTTP %s: %s", exc.status_code, exc)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60.0)
                except Exception as exc:
                    if _is_auth_error(exc) or any(m in str(exc).lower() for m in _AUTH_MARKERS):
                        logger.error(
                            "tastytrade account streamer auth failed — backoff, not expiring: %s",
                            exc,
                        )
                    else:
                        logger.exception("tastytrade account streamer dropped; reconnect in %.0fs", backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60.0)
        finally:
            redis = self._redis
            self._redis = None
            if redis is not None:
                closer = getattr(redis, "close", None)
                if closer is not None:
                    result = closer(close_connection_pool=True)
                    if asyncio.iscoroutine(result):
                        await result

    async def _connect_once(self, token: str) -> None:
        url = self._tt.account_streamer_url
        account = self._tt.account_number
        logger.info("account streamer connecting %s account=%s", url, account)
        async with websockets.connect(url, ping_interval=None, close_timeout=5) as ws:
            await ws.send(
                json.dumps(
                    {
                        "action": "connect",
                        "value": [account],
                        "auth-token": f"Bearer {token}",
                        "request-id": self._next_request_id(),
                    }
                )
            )
            heartbeat = None
            try:
                async for raw in ws:
                    if self._stop.is_set():
                        break
                    try:
                        message = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(message, dict):
                        continue
                    if heartbeat is None:
                        if connect_ack_ok(message):
                            heartbeat = asyncio.create_task(self._heartbeat(ws, token))
                            logger.info("account streamer connect ack ok session=%s", message.get("web-socket-session-id"))
                        else:
                            status = str(message.get("status") or "").lower()
                            if status in {"error", "failed"}:
                                raise RuntimeError(
                                    f"account streamer connect failed: {message.get('message') or message}"
                                )
                        continue
                    await self._handle_message(message)
            finally:
                if heartbeat is not None:
                    heartbeat.cancel()

    async def _heartbeat(self, ws: Any, token: str) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(_HEARTBEAT_SECONDS)
            try:
                await ws.send(
                    json.dumps(
                        {
                            "action": "heartbeat",
                            "auth-token": f"Bearer {token}",
                            "request-id": self._next_request_id(),
                        }
                    )
                )
            except Exception:
                return

    async def _handle_message(self, message: dict[str, Any]) -> None:
        kind, should = classify_order_event(message)
        enqueue = stream_event_should_enqueue(message)
        if kind is None and not enqueue:
            status = str(message.get("status") or "").lower()
            if status in {"error", "failed"}:
                err = str(message.get("message") or message.get("reason") or message)
                if any(m in err.lower() for m in _AUTH_MARKERS):
                    raise RuntimeError(f"account streamer auth failed: {err}")
            return
        if kind is not None:
            payload = unwrap_order_event(message) or {}
            logger.info(
                "account streamer Order %s status=%s kind=%s remaining=%s",
                payload.get("id"),
                payload.get("status"),
                kind,
                (payload.get("legs") or [{}])[0].get("remaining-quantity")
                if isinstance(payload.get("legs"), list) and payload.get("legs")
                else payload.get("remaining-quantity"),
            )
            if self._on_order is not None:
                maybe = self._on_order(payload, kind)
                if asyncio.iscoroutine(maybe):
                    await maybe
        elif enqueue:
            logger.info("account streamer %s — enqueue reconcile", message.get("type"))
        if enqueue:
            await enqueue_tasty_reconcile(redis=self._redis)


__all__ = [
    "TASTY_RECONCILE_EXPIRES_SECONDS",
    "TASTY_RECONCILE_JOB_ID",
    "TASTY_RECONCILE_JOB_NAME",
    "AccountStreamer",
    "classify_order_event",
    "connect_ack_ok",
    "enqueue_tasty_reconcile",
    "stream_event_should_enqueue",
    "unwrap_order_event",
]
