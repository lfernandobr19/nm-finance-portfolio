"""tastytrade Open API client (OAuth2 refresh + equity/option orders)."""

from __future__ import annotations

import logging
import random
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger("fiidesk.tastytrade")

_TOKEN_SKEW_SECONDS = 60
_USER_AGENT = "fiidesk/1.0"
_TRANSIENT_HTTP = frozenset({502, 503})
_RETRY_HTTP = frozenset({429, 502, 503})
_ORDER_RETRY_SLEEPS = (2.0, 4.0)
_TRADE_AUTHORITY_OK = frozenset(
    {
        "owner",
        "trade",
        "trade-only",
        "tradeonly",
        "read-trade",
        "readtrade",
        "full",
        "admin",
        "read-write",
        "readwrite",
    }
)
_TRADE_AUTHORITY_DENY = frozenset({"read", "read-only", "readonly", "viewer", "view"})
SANDBOX_AUTH_URL = "https://cert-my.staging-tasty.works/auth.html"
LIVE_AUTH_URL = "https://my.tastytrade.com/auth.html"
_CUSTOMER_MARKERS = (
    "not a customer",
    "not a tastytrade customer",
)
_TERMINAL_CANCEL_MARKERS = (
    "filled",
    "cancelled",
    "canceled",
    "expired",
    "rejected",
    "not live",
    "cannot be canceled",
    "cannot be cancelled",
    "already",
)


class TastytradeHttpError(RuntimeError):
    """HTTP error from the Tastytrade REST API, with status_code attached."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = int(status_code)


class AmbiguousOrderSubmit(RuntimeError):
    """POST of an order got a transient 502/503 after retries.

    The request may have created the order on the broker. Do not POST again;
    reconcile via GET /orders/live.
    """


class DryRunRejected(RuntimeError):
    """dry-run said the order would not be accepted (BP / warnings)."""


def occ_option_symbol(root: str, expiration: date, option_type: str, strike: float) -> str:
    """Build an OCC equity-option symbol for order submission.

    OCC format (Context7): root symbol padded to 6 chars, six-digit expiration
    (yymmdd), option type (P/C), and an eight-digit strike front-padded with
    zeros and multiplied by 1000. E.g. QQQ 2026-09-18 P 480.0 -> "QQQ   260918P00480000".
    """
    root = root.upper().strip()[:6].ljust(6)
    exp = expiration.strftime("%y%m%d")
    typ = "P" if str(option_type).upper().startswith("P") else "C"
    strike_int = int(round(float(strike) * 1000))
    return f"{root}{exp}{typ}{strike_int:08d}"


def _is_order_endpoint(url: str) -> bool:
    path = (url or "").lower()
    return "/orders" in path or "/complex-orders" in path


def _response_json(resp: httpx.Response) -> dict[str, Any]:
    if not resp.content:
        return {}
    try:
        parsed = resp.json()
    except Exception as exc:
        snippet = resp.text[:300] if resp.text else "(vazio)"
        raise RuntimeError(
            f"tastytrade resposta inválida HTTP {resp.status_code}: {snippet}"
        ) from exc
    if isinstance(parsed, dict):
        return parsed
    return {"data": parsed}


def _error_message(data: dict[str, Any], resp: httpx.Response) -> str:
    msg = data.get("error") or data.get("message") or resp.text or resp.reason_phrase
    if isinstance(msg, dict):
        msg = msg.get("message") or msg.get("code") or str(msg)
    return str(msg)[:500]


def _unwrap_order_list(data: dict[str, Any]) -> list[dict[str, Any]]:
    items: Any = data.get("data") if isinstance(data, dict) else data
    if isinstance(items, dict):
        items = items.get("items") or items.get("orders") or items.get("data") or []
    if not isinstance(items, list):
        return []
    return [i for i in items if isinstance(i, dict)]


def _write_env_refresh(env_key: str, refresh_token: str) -> None:
    from pathlib import Path

    env_path = Path(__file__).resolve().parents[2] / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    out: list[str] = []
    replaced = False
    for line in lines:
        if line.startswith(f"{env_key}="):
            out.append(f"{env_key}={refresh_token}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"{env_key}={refresh_token}")
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _already_terminal_cancel(msg: str) -> bool:
    text = (msg or "").lower()
    return any(marker in text for marker in _TERMINAL_CANCEL_MARKERS)


def _is_customer_error(status_code: int, message: str) -> bool:
    if int(status_code) not in (400, 401, 403):
        return False
    text = (message or "").lower()
    return any(m in text for m in _CUSTOMER_MARKERS)


def _backoff_seconds(attempt: int) -> float:
    base = _ORDER_RETRY_SLEEPS[min(attempt, len(_ORDER_RETRY_SLEEPS) - 1)]
    return base * (0.5 + random.random())


def _authority_allows_trade(level: str | None) -> bool:
    raw = (level or "").lower().replace("_", "-").replace(" ", "")
    compact = raw.replace("-", "")
    if compact in {x.replace("-", "") for x in _TRADE_AUTHORITY_DENY}:
        return False
    if not raw:
        return True
    if compact in {x.replace("-", "") for x in _TRADE_AUTHORITY_OK} or "trade" in compact:
        return True
    return True


def _apply_external_identifier(body: dict[str, Any], client_order_id: str | None) -> None:
    body.pop("ext-client-order-id", None)
    if client_order_id:
        body["external-identifier"] = str(client_order_id)


def _payload_identifier(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    return str(
        payload.get("external-identifier")
        or payload.get("ext-client-order-id")
        or payload.get("client-order-id")
        or payload.get("client_order_id")
        or ""
    )


def _customer_accounts(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    items = _unwrap_order_list(data or {})
    out: list[dict[str, Any]] = []
    for item in items:
        inner = item.get("account") if isinstance(item.get("account"), dict) else item
        if isinstance(inner, dict):
            out.append(
                {
                    "account-number": str(
                        inner.get("account-number") or inner.get("account_number") or ""
                    ),
                    "authority-level": str(
                        item.get("authority-level")
                        or inner.get("authority-level")
                        or ""
                    ),
                }
            )
    return out


def dry_run_block_reason(data: dict[str, Any] | None) -> str | None:
    """Return a reject reason if dry-run shows insufficient BP or blocking warnings."""
    if not isinstance(data, dict):
        return None
    inner = data.get("data") if isinstance(data.get("data"), dict) else data
    if not isinstance(inner, dict):
        return None
    warnings = inner.get("warnings") or []
    for raw in warnings:
        text = str(raw).lower()
        if any(k in text for k in ("insufficient", "buying power", "reject", "not accepted")):
            return str(raw)[:300]
    bp = inner.get("buying-power-effect") or {}
    if not isinstance(bp, dict):
        return None
    try:
        current = float(bp.get("current-buying-power") or 0)
        impact = abs(float(bp.get("impact") or bp.get("change-in-buying-power") or 0))
        effect = str(bp.get("change-in-buying-power-effect") or bp.get("effect") or "").lower()
    except (TypeError, ValueError):
        return None
    if effect == "debit" and impact > 0 and current + 1e-6 < impact:
        return f"buying-power insufficient (have {current:.2f}, need {impact:.2f})"
    return None


class TastytradeClient:
    def __init__(self, *, live: bool = False) -> None:
        self.settings = get_settings()
        self.live = live
        self._access_token: str | None = None
        self._expires_at: float = 0.0
        self._refresh_override: str | None = None
        self._http_client: httpx.Client | None = None
        self._authority_level: str | None = None

    # ---- credentials selection (sandbox vs production) ----
    @property
    def _client_id(self) -> str:
        if self.live:
            return (self.settings.tastytrade_live_client_id or "").strip()
        return (self.settings.tastytrade_client_id or "").strip()

    @property
    def _client_secret(self) -> str:
        if self.live:
            return (self.settings.tastytrade_live_client_secret or "").strip()
        return (self.settings.tastytrade_client_secret or "").strip()

    @property
    def _refresh_token(self) -> str:
        if self._refresh_override:
            return self._refresh_override
        if self.live:
            return (self.settings.tastytrade_live_refresh_token or "").strip()
        return (self.settings.tastytrade_refresh_token or "").strip()

    def _http(self) -> httpx.Client:
        client = self._http_client
        if client is None or getattr(client, "is_closed", False):
            self._http_client = httpx.Client(
                timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=5.0),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
                headers=self._base_headers(),
                transport=httpx.HTTPTransport(retries=1),
            )
            client = self._http_client
        return client

    def close(self) -> None:
        client = self._http_client
        if client is not None:
            closer = getattr(client, "close", None)
            if closer is not None:
                closer()
            self._http_client = None

    @property
    def account_number(self) -> str:
        if self.live:
            return (self.settings.tastytrade_live_account_number or "").strip()
        return (self.settings.tastytrade_account_number or "").strip()

    @property
    def base_url(self) -> str:
        if not self.live and self.settings.tastytrade_sandbox:
            return self.settings.tastytrade_sandbox_base_url.rstrip("/")
        return self.settings.tastytrade_base_url.rstrip("/")

    def configured(self) -> bool:
        return bool(
            self._client_id
            and self._client_secret
            and self._refresh_token
            and self.account_number
        )

    def _base_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "User-Agent": _USER_AGENT,
        }

    def _auth_headers(self) -> dict[str, str]:
        token = self._ensure_access_token()
        return {
            **self._base_headers(),
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _ensure_access_token(self) -> str:
        now = time.time()
        if self._access_token and now < self._expires_at - _TOKEN_SKEW_SECONDS:
            return self._access_token

        url = f"{self.base_url}/oauth/token"
        body = {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "scope": (self.settings.tastytrade_oauth_scopes or "read trade openid").strip(),
        }
        last_error: Exception | None = None
        payload: dict[str, Any] = {}
        for attempt in range(3):
            try:
                # Sandbox token endpoint expects form body (JSON often 502/400).
                resp = self._http().request(
                    "POST", url, headers=self._base_headers(), data=body
                )
            except httpx.HTTPError as exc:
                last_error = RuntimeError(str(exc))
                logger.exception("tastytrade token request failed")
                if attempt < 2:
                    time.sleep(_ORDER_RETRY_SLEEPS[min(attempt, len(_ORDER_RETRY_SLEEPS) - 1)])
                    continue
                raise last_error from exc
            if resp.status_code < 400:
                payload = _response_json(resp)
                break
            msg = resp.text[:300]
            logger.warning("tastytrade token HTTP %s: %s", resp.status_code, msg)
            err = RuntimeError(f"tastytrade token failed: {resp.text[:200]}")
            if _is_customer_error(resp.status_code, msg):
                raise err
            if resp.status_code in _RETRY_HTTP and attempt < 2:
                sleep_s = _backoff_seconds(attempt)
                logger.warning("tastytrade token retry %s in %.1fs", attempt + 1, sleep_s)
                time.sleep(sleep_s)
                last_error = err
                continue
            raise err
        else:
            raise last_error or RuntimeError("tastytrade token failed")

        token = str(payload.get("access_token") or "")
        if not token:
            raise RuntimeError("tastytrade token response missing access_token")
        expires_in = float(payload.get("expires_in") or 900)
        self._access_token = token
        self._expires_at = now + expires_in
        new_refresh = str(payload.get("refresh_token") or "").strip()
        if new_refresh and new_refresh != self._refresh_token:
            self._persist_refresh_token(new_refresh)
        return token

    def _persist_refresh_token(self, refresh_token: str) -> None:
        """Save rotated refresh: instance override + .env + drop Settings cache."""
        self._refresh_override = refresh_token
        env_key = "TASTYTRADE_LIVE_REFRESH_TOKEN" if self.live else "TASTYTRADE_REFRESH_TOKEN"
        try:
            _write_env_refresh(env_key, refresh_token)
            logger.info("tastytrade rotated refresh token persisted to .env")
        except OSError as exc:
            logger.warning("tastytrade could not persist rotated refresh token: %s", exc)
        try:
            get_settings.cache_clear()
            self.settings = get_settings()
        except Exception as exc:
            logger.warning("tastytrade could not reload settings after refresh rotate: %s", exc)

    def _post_order(self, body: dict[str, Any], *, client_order_id: str | None = None) -> dict[str, Any]:
        account = self.account_number
        url = f"{self.base_url}/accounts/{account}/orders"
        _apply_external_identifier(body, client_order_id)
        self._ensure_trade_authority()
        reason = self.evaluate_dry_run(body)
        if reason:
            raise DryRunRejected(reason)
        return self._post_order_with_recovery(url, body, client_order_id=client_order_id)

    def _post_complex_order(self, body: dict[str, Any], *, client_order_id: str | None = None) -> dict[str, Any]:
        account = self.account_number
        url = f"{self.base_url}/accounts/{account}/complex-orders"
        _apply_external_identifier(body, client_order_id)
        self._ensure_trade_authority()
        return self._post_order_with_recovery(url, body, client_order_id=client_order_id)

    def _post_order_with_recovery(
        self,
        url: str,
        body: dict[str, Any],
        *,
        client_order_id: str | None,
    ) -> dict[str, Any]:
        try:
            return self._post(url, body)
        except AmbiguousOrderSubmit:
            found = self.find_order_by_identifier(client_order_id)
            if found is not None:
                logger.info(
                    "tastytrade POST ambiguous — found order %s by identifier, no second POST",
                    found.get("id") or found.get("order-id"),
                )
                return {"data": found}
            logger.warning("tastytrade POST ambiguous — one extra POST same identifier")
            try:
                return self._request("POST", url, json_body=body, attempts=1)
            except TastytradeHttpError as exc:
                if exc.status_code in _TRANSIENT_HTTP:
                    raise AmbiguousOrderSubmit(str(exc)) from exc
                raise

    def _post(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", url, json_body=body)

    def _get(self, url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("GET", url, params=params)

    def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        attempts: int | None = None,
    ) -> dict[str, Any]:
        """HTTP call. Order POST/GET retry 502/503/429; 400 is never retried.

        After exhausting retries a POST to an order endpoint raises
        ``AmbiguousOrderSubmit`` so the caller looks up by identifier before
        a single extra POST. Quote endpoints do not go through this method.
        """
        retry = _is_order_endpoint(url)
        max_attempts = attempts if attempts is not None else (3 if retry else 1)
        last_error: Exception | None = None
        refreshed_401 = False
        attempt = 0
        while True:
            kwargs: dict[str, Any] = {"headers": self._auth_headers()}
            if json_body is not None:
                kwargs["json"] = json_body
            if params:
                kwargs["params"] = params
            resp = self._http().request(method, url, **kwargs)
            data = _response_json(resp)
            if resp.status_code < 400:
                return data
            msg = _error_message(data, resp)
            err = TastytradeHttpError(resp.status_code, msg)
            if (
                resp.status_code == 401
                and method.upper() in {"GET", "PUT"}
                and not refreshed_401
            ):
                logger.warning("tastytrade %s %s HTTP 401 — refresh token once", method, url)
                self._access_token = None
                self._expires_at = 0.0
                refreshed_401 = True
                last_error = err
                continue
            retry_429 = resp.status_code == 429 and attempt < 2
            retry_transient = (
                resp.status_code in _TRANSIENT_HTTP and retry and attempt < max_attempts - 1
            )
            if retry_429 or retry_transient:
                sleep_s = _backoff_seconds(attempt)
                logger.warning(
                    "tastytrade %s %s HTTP %s, retry %s in %.1fs",
                    method,
                    url,
                    resp.status_code,
                    attempt + 1,
                    sleep_s,
                )
                time.sleep(sleep_s)
                last_error = err
                attempt += 1
                continue
            if (
                method.upper() == "POST"
                and retry
                and resp.status_code in _TRANSIENT_HTTP
            ):
                raise AmbiguousOrderSubmit(str(err)) from err
            raise err

    def get_order(self, broker_order_id: str) -> dict[str, Any]:
        """GET /accounts/{n}/orders/{id}."""
        account = self.account_number
        url = f"{self.base_url}/accounts/{account}/orders/{broker_order_id}"
        return self._get(url)

    def list_live_orders(self) -> list[dict[str, Any]]:
        """GET /accounts/{n}/orders/live — Live/Filled/Rejected/Cancelled of the day."""
        account = self.account_number
        url = f"{self.base_url}/accounts/{account}/orders/live"
        data = self._get(url)
        return _unwrap_order_list(data)

    def list_orders(self, *, start_at: datetime | None = None) -> list[dict[str, Any]]:
        """GET /accounts/{n}/orders — history (not the live-only endpoint)."""
        account = self.account_number
        url = f"{self.base_url}/accounts/{account}/orders"
        params: dict[str, Any] = {}
        if start_at is not None:
            params["start-at"] = start_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        data = self._get(url, params=params or None)
        return _unwrap_order_list(data)

    def list_positions(self) -> list[dict[str, Any]]:
        """GET /accounts/{n}/positions."""
        account = self.account_number
        url = f"{self.base_url}/accounts/{account}/positions"
        data = self._get(url)
        return _unwrap_order_list(data)

    def find_order_by_identifier(self, identifier: str | None) -> dict[str, Any] | None:
        """GET live then history for external-identifier / ext-client-order-id."""
        want = str(identifier or "").strip()
        if not want:
            return None
        try:
            for item in self.list_live_orders():
                if _payload_identifier(item) == want:
                    return item
        except Exception as exc:
            logger.warning("tastytrade identifier lookup live failed: %s", exc)
        try:
            for item in self.list_orders(start_at=datetime.now(timezone.utc) - timedelta(days=2)):
                if _payload_identifier(item) == want:
                    return item
        except Exception as exc:
            logger.warning("tastytrade identifier lookup history failed: %s", exc)
        return None

    def _ensure_trade_authority(self) -> None:
        if self._authority_level is None:
            return
        if not _authority_allows_trade(self._authority_level):
            raise TastytradeHttpError(
                403,
                f"authority-level {self._authority_level} does not allow trade",
            )

    def probe_account(self) -> bool:
        """GET /customers/me/accounts. 400 customer is logged and never expires orders."""
        url = f"{self.base_url}/customers/me/accounts"
        try:
            data = self._get(url)
        except TastytradeHttpError as exc:
            if _is_customer_error(exc.status_code, str(exc)):
                logger.error(
                    "tastytrade probe token/auth failed GET /customers/me/accounts HTTP %s: %s",
                    exc.status_code,
                    exc,
                )
                return False
            logger.warning(
                "tastytrade probe GET /customers/me/accounts HTTP %s: %s",
                exc.status_code,
                exc,
            )
            return False
        except Exception as exc:
            if _is_customer_error(0, str(exc)):
                logger.error("tastytrade probe token/auth failed: %s", exc)
                return False
            logger.warning("tastytrade probe GET /customers/me/accounts failed: %s", exc)
            return False
        accounts = _customer_accounts(data)
        want = self.account_number
        for item in accounts:
            if item["account-number"] == want:
                self._authority_level = item["authority-level"] or "owner"
                logger.info(
                    "tastytrade probe GET /customers/me/accounts HTTP 200 account=%s authority=%s",
                    want,
                    self._authority_level,
                )
                return True
        if accounts:
            self._authority_level = accounts[0]["authority-level"] or None
            logger.warning(
                "tastytrade probe GET /customers/me/accounts HTTP 200 but %s not in list n=%s",
                want,
                len(accounts),
            )
            return False
        logger.warning("tastytrade probe GET /customers/me/accounts HTTP 200 empty list")
        return False

    def dry_run_order(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST /accounts/{n}/orders/dry-run — no send."""
        account = self.account_number
        url = f"{self.base_url}/accounts/{account}/orders/dry-run"
        return self._post(url, body)

    def evaluate_dry_run(self, body: dict[str, Any]) -> str | None:
        """None = proceed to POST. String = reject locally. 502 = proceed."""
        try:
            data = self.dry_run_order(body)
        except AmbiguousOrderSubmit:
            logger.warning("tastytrade dry-run ambiguous — proceeding to POST")
            return None
        except TastytradeHttpError as exc:
            if exc.status_code in _TRANSIENT_HTTP:
                logger.warning("tastytrade dry-run HTTP %s — proceeding to POST", exc.status_code)
                return None
            if _is_customer_error(exc.status_code, str(exc)):
                logger.error("tastytrade dry-run token/auth failed: %s", exc)
                raise
            logger.warning("tastytrade dry-run HTTP %s: %s", exc.status_code, exc)
            return None
        except Exception as exc:
            logger.warning("tastytrade dry-run failed — proceeding to POST: %s", exc)
            return None
        return dry_run_block_reason(data)

    def replace_equity_limit(
        self,
        broker_order_id: str,
        *,
        symbol: str,
        quantity: float,
        limit_price: float,
        action: str = "Buy to Open",
    ) -> dict[str, Any]:
        """PUT /orders/{id} — price / type / TIF only (Context7 replace)."""
        account = self.account_number
        url = f"{self.base_url}/accounts/{account}/orders/{broker_order_id}"
        debit = "buy" in action.lower()
        body = {
            "time-in-force": "Day",
            "order-type": "Limit",
            "price": round(float(limit_price), 2),
            "price-effect": "Debit" if debit else "Credit",
            "legs": [
                {
                    "instrument-type": "Equity",
                    "symbol": symbol.upper(),
                    "action": action,
                    "quantity": round(float(quantity), 6),
                }
            ],
        }
        return self._request("PUT", url, json_body=body)

    @property
    def account_streamer_url(self) -> str:
        if not self.live and self.settings.tastytrade_sandbox:
            return "wss://streamer.cert.tastyworks.com"
        return "wss://streamer.tastyworks.com"

    def access_token(self) -> str:
        return self._ensure_access_token()

    def submit_equity_limit_buy(
        self,
        *,
        symbol: str,
        quantity: float,
        limit_price: float,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        body = {
            "order-type": "Limit",
            "time-in-force": "Day",
            "price": round(float(limit_price), 2),
            "price-effect": "Debit",
            "legs": [
                {
                    "instrument-type": "Equity",
                    "symbol": symbol.upper(),
                    "action": "Buy to Open",
                    "quantity": round(float(quantity), 6),
                }
            ],
        }
        return self._post_order(body, client_order_id=client_order_id)

    def submit_equity_notional_market_buy(
        self,
        *,
        symbol: str,
        notional_usd: float,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """Buy ~notional USD of equity (fractional qty determined by market)."""
        body = {
            "order-type": "Notional Market",
            "time-in-force": "Day",
            "value": round(abs(float(notional_usd)), 2),
            "value-effect": "Debit",
            "legs": [
                {
                    "instrument-type": "Equity",
                    "symbol": symbol.upper(),
                    "action": "Buy to Open",
                }
            ],
        }
        return self._post_order(body, client_order_id=client_order_id)

    def cancel_order(self, broker_order_id: str) -> dict[str, Any]:
        """DELETE /orders/{id}. Already-terminal legs are treated as success."""
        account = self.account_number
        url = f"{self.base_url}/accounts/{account}/orders/{broker_order_id}"
        resp = self._http().request("DELETE", url, headers=self._auth_headers())
        data = _response_json(resp) if resp.content else {}
        if resp.status_code >= 400:
            msg = _error_message(data, resp)
            if _already_terminal_cancel(msg):
                logger.info(
                    "tastytrade cancel %s already terminal HTTP %s: %s",
                    broker_order_id,
                    resp.status_code,
                    msg[:200],
                )
                return data if isinstance(data, dict) else {}
            raise RuntimeError(msg)
        return data if isinstance(data, dict) else {}

    # ---- sells / brackets (Phase 2) ---------------------------------------

    def submit_equity_market_sell(
        self,
        *,
        symbol: str,
        quantity: float,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """Sell to Close at market (whole or fractional quantity)."""
        body = {
            "order-type": "Market",
            "time-in-force": "Day",
            "legs": [
                {
                    "instrument-type": "Equity",
                    "symbol": symbol.upper(),
                    "action": "Sell to Close",
                    "quantity": round(float(quantity), 6),
                }
            ],
        }
        return self._post_order(body, client_order_id=client_order_id)

    def submit_equity_limit_sell(
        self,
        *,
        symbol: str,
        quantity: float,
        limit_price: float,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """Sell to Close at a limit price."""
        body = {
            "order-type": "Limit",
            "time-in-force": "Day",
            "price": round(float(limit_price), 2),
            "price-effect": "Credit",
            "legs": [
                {
                    "instrument-type": "Equity",
                    "symbol": symbol.upper(),
                    "action": "Sell to Close",
                    "quantity": round(float(quantity), 6),
                }
            ],
        }
        return self._post_order(body, client_order_id=client_order_id)

    def submit_oco_bracket(
        self,
        *,
        symbol: str,
        quantity: float,
        target_price: float,
        stop_trigger: float,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """Place an OCO bracket closing an existing position.

        Take-profit limit (target) and stop-loss (market stop) legs; filling one
        cancels the other. Requires an existing position to close.
        """
        body = {
            "type": "OCO",
            "orders": [
                {
                    "order-type": "Limit",
                    "time-in-force": "GTC",
                    "price": round(float(target_price), 2),
                    "price-effect": "Credit",
                    "legs": [
                        {
                            "instrument-type": "Equity",
                            "symbol": symbol.upper(),
                            "action": "Sell to Close",
                            "quantity": round(float(quantity), 6),
                        }
                    ],
                },
                {
                    "order-type": "Stop",
                    "time-in-force": "GTC",
                    "stop-trigger": round(float(stop_trigger), 2),
                    "legs": [
                        {
                            "instrument-type": "Equity",
                            "symbol": symbol.upper(),
                            "action": "Sell to Close",
                            "quantity": round(float(quantity), 6),
                        }
                    ],
                },
            ],
        }
        return self._post_complex_order(body, client_order_id=client_order_id)

    def fetch_cash_balance(self) -> float | None:
        """Current cash-balance for the selected account (None on any failure)."""
        if not self.configured():
            return None
        account = self.account_number
        url = f"{self.base_url}/accounts/{account}/balances"
        try:
            data = self._get(url)
        except Exception:
            logger.exception("tastytrade balances fetch failed")
            return None
        inner = data.get("data") or data
        raw = inner.get("cash-balance") if isinstance(inner, dict) else None
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    # ---- options (Phase B / premium wheel, skeleton) -----------------------

    def _submit_single_leg_option_order(
        self,
        *,
        option_symbol: str,
        action: str,
        quantity: int,
        limit_price: float | None = None,
        time_in_force: str = "Day",
    ) -> dict[str, Any]:
        """Submit a single-leg equity-option order (Sell to Open for the wheel)."""
        body: dict[str, Any] = {
            "order-type": "Limit" if limit_price is not None else "Market",
            "time-in-force": time_in_force,
            "legs": [
                {
                    "instrument-type": "Equity Option",
                    "symbol": option_symbol,
                    "action": action,
                    "quantity": int(quantity),
                }
            ],
        }
        if limit_price is not None:
            body["price"] = round(float(limit_price), 2)
            body["price-effect"] = "Credit" if action.lower().startswith("sell") else "Debit"
        return self._post_order(body)

    def submit_cash_secured_put(
        self,
        *,
        option_symbol: str,
        quantity: int = 1,
        limit_price: float | None = None,
        time_in_force: str = "Day",
    ) -> dict[str, Any]:
        """Sell a cash-secured put (Sell to Open). Collects premium; if assigned,
        the wheel buys the underlying at the strike."""
        return self._submit_single_leg_option_order(
            option_symbol=option_symbol,
            action="Sell to Open",
            quantity=quantity,
            limit_price=limit_price,
            time_in_force=time_in_force,
        )

    def submit_covered_call(
        self,
        *,
        option_symbol: str,
        quantity: int = 1,
        limit_price: float | None = None,
        time_in_force: str = "Day",
    ) -> dict[str, Any]:
        """Sell a covered call (Sell to Open) against held shares."""
        return self._submit_single_leg_option_order(
            option_symbol=option_symbol,
            action="Sell to Open",
            quantity=quantity,
            limit_price=limit_price,
            time_in_force=time_in_force,
        )

    def fetch_options_level(self) -> str | None:
        """Options trading level from /accounts/{account}/trading-status.

        Returns the raw `options-level` string (e.g. "No Restrictions", "The
        Works", "None") or None on failure/absence. The OAuth scope currently
        configured (`read trade openid`) may not expose this (403) and the
        sandbox may return 502 — the caller must treat None as "not approved".
        """
        if not self.configured():
            return None
        account = self.account_number
        url = f"{self.base_url}/accounts/{account}/trading-status"
        try:
            data = self._get(url)
        except Exception:
            logger.exception("tastytrade trading-status fetch failed")
            return None
        inner = data.get("data") or data
        if not isinstance(inner, dict):
            return None
        level = inner.get("options-level")
        return str(level) if level is not None else None
