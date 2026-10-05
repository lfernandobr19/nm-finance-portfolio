"""tastytrade DXLink intraday candles (5m) for day trade study."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import httpx
import websockets

from app.config import get_settings
from app.services.day_trade.bars import IntradayBar
from app.services.tastytrade_client import TastytradeClient

logger = logging.getLogger("fiidesk.tastytrade.market_data")

DXLINK_VERSION = "0.1-DXF-JS/0.3.0"
_CANDLE_CHANNEL = 1
_CANDLE_FIELDS = [
    "eventSymbol",
    "eventTime",
    "eventFlags",
    "index",
    "time",
    "sequence",
    "count",
    "volume",
    "vwap",
    "bidVolume",
    "askVolume",
    "impVolatility",
    "openInterest",
    "open",
    "high",
    "low",
    "close",
]
_CANDLE_FIELD_COUNT = len(_CANDLE_FIELDS)


@dataclass(frozen=True)
class QuoteToken:
    token: str
    dxlink_url: str
    level: str


def parse_watchlist(raw: str | None = None) -> list[str]:
    settings = get_settings()
    text = (raw or settings.day_trade_watchlist or "").strip()
    return [t.strip().upper() for t in text.split(",") if t.strip()]


def fetch_quote_token(client: TastytradeClient | None = None, *, max_attempts: int = 4) -> QuoteToken:
    tt = client or TastytradeClient()
    if not tt.configured():
        raise RuntimeError("tastytrade credentials not configured")
    url = f"{tt.base_url}/api-quote-tokens"
    last_err: Exception | None = None
    for attempt in range(max_attempts):
        try:
            with httpx.Client(timeout=30.0) as http:
                resp = http.get(url, headers=tt._auth_headers())
                if resp.status_code >= 400:
                    raise RuntimeError(
                        f"api-quote-tokens HTTP {resp.status_code}: {resp.text[:300]}"
                    )
                payload = resp.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, dict):
                raise RuntimeError("api-quote-tokens missing data")
            token = str(data.get("token") or "")
            dxlink_url = str(data.get("dxlink-url") or data.get("dxlink_url") or "")
            level = str(data.get("level") or "")
            if not token or not dxlink_url:
                raise RuntimeError("api-quote-tokens missing token or dxlink-url")
            return QuoteToken(token=token, dxlink_url=dxlink_url, level=level)
        except Exception as exc:
            last_err = exc
            err = str(exc).lower()
            if attempt + 1 >= max_attempts:
                break
            wait = min(2.0 * (2**attempt), 30.0)
            if "not a tastytrade customer" in err or "401" in err or "403" in err:
                logger.warning(
                    "quote token attempt %d/%d failed (%s); retry in %.0fs",
                    attempt + 1,
                    max_attempts,
                    exc,
                    wait,
                )
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"api-quote-tokens failed after {max_attempts} attempts: {last_err}")


def _parse_candle_compact(chunk: list[Any]) -> dict[str, Any] | None:
    if len(chunk) < _CANDLE_FIELD_COUNT:
        return None
    return dict(zip(_CANDLE_FIELDS, chunk[:_CANDLE_FIELD_COUNT], strict=False))


def _valid_ohlc(o: float, h: float, l: float, c: float) -> bool:
    for v in (o, h, l, c):
        if v <= 0 or math.isnan(v) or math.isinf(v):
            return False
    return True


def candle_to_bar(candle: dict[str, Any]) -> IntradayBar | None:
    try:
        ts_ms = int(candle.get("time") or candle.get("eventTime") or 0)
        if ts_ms <= 0:
            return None
        o = float(candle.get("open") or 0)
        h = float(candle.get("high") or 0)
        l = float(candle.get("low") or 0)
        c = float(candle.get("close") or 0)
        if not _valid_ohlc(o, h, l, c):
            return None
        ts = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
        return IntradayBar(
            ts=ts,
            open=o,
            high=h,
            low=l,
            close=c,
            volume=float(candle.get("volume") or 0),
        )
    except (TypeError, ValueError):
        return None


def _candle_symbol(ticker: str, interval: str) -> str:
    return f"{ticker.upper()}{{={interval},tho=true}}"


class DXLinkCandleStreamer:
    """Minimal DXLink client for 5m equity candles."""

    def __init__(
        self,
        *,
        symbols: list[str],
        interval: str = "5m",
        on_bar: Callable[[str, IntradayBar], Awaitable[None] | None] | None = None,
        start_time: datetime | None = None,
    ) -> None:
        self.symbols = [s.upper() for s in symbols]
        self.interval = interval
        self.on_bar = on_bar
        self.start_time = start_time
        self._tt = TastytradeClient()
        self._quote: QuoteToken | None = None
        self._channel_open = asyncio.Event()
        self._stop = asyncio.Event()

    async def run(self) -> None:
        backoff = 2.0
        while not self._stop.is_set():
            try:
                self._quote = fetch_quote_token(self._tt)
                backoff = 2.0
            except Exception:
                logger.exception("DXLink quote token failed; retry in %.0fs", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
                continue
            try:
                await self._connect_once()
                backoff = 2.0
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("DXLink stream error; reconnecting in %.0fs", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def stop(self) -> None:
        self._stop.set()

    async def _connect_once(self) -> None:
        assert self._quote is not None
        async with websockets.connect(
            self._quote.dxlink_url,
            ping_interval=None,
            close_timeout=5,
            max_size=8 * 1024 * 1024,
        ) as ws:
            self._channel_open = asyncio.Event()
            await ws.send(
                json.dumps(
                    {
                        "type": "SETUP",
                        "channel": 0,
                        "keepaliveTimeout": 60,
                        "acceptKeepaliveTimeout": 60,
                        "version": DXLINK_VERSION,
                    }
                )
            )
            keepalive = asyncio.create_task(self._keepalive(ws))
            try:
                async for raw in ws:
                    if self._stop.is_set():
                        break
                    try:
                        message = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    await self._handle_message(ws, message)
            finally:
                keepalive.cancel()

    async def _keepalive(self, ws: Any) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(30)
            try:
                await ws.send(json.dumps({"type": "KEEPALIVE", "channel": 0}))
            except Exception:
                return

    async def _handle_message(self, ws: Any, message: dict[str, Any]) -> None:
        msg_type = message.get("type")
        if msg_type == "AUTH_STATE":
            if message.get("state") == "UNAUTHORIZED" and self._quote:
                await ws.send(
                    json.dumps({"type": "AUTH", "channel": 0, "token": self._quote.token})
                )
            elif message.get("state") == "AUTHORIZED":
                await self._open_candle_channel(ws)
        elif msg_type == "CHANNEL_OPENED" and message.get("channel") == _CANDLE_CHANNEL:
            self._channel_open.set()
            await self._setup_feed(ws)
            await self._subscribe_candles(ws)
        elif msg_type == "FEED_DATA" and message.get("channel") == _CANDLE_CHANNEL:
            await self._handle_feed_data(message.get("data") or [])
        elif msg_type == "ERROR":
            raise RuntimeError(str(message.get("message") or message))

    async def _open_candle_channel(self, ws: Any) -> None:
        await ws.send(
            json.dumps(
                {
                    "type": "CHANNEL_REQUEST",
                    "channel": _CANDLE_CHANNEL,
                    "service": "FEED",
                    "parameters": {"contract": "AUTO"},
                }
            )
        )

    async def _setup_feed(self, ws: Any) -> None:
        await self._channel_open.wait()
        await ws.send(
            json.dumps(
                {
                    "type": "FEED_SETUP",
                    "channel": _CANDLE_CHANNEL,
                    "acceptAggregationPeriod": 0.1,
                    "acceptDataFormat": "COMPACT",
                    "acceptEventFields": {"Candle": _CANDLE_FIELDS},
                }
            )
        )

    async def _subscribe_candles(self, ws: Any) -> None:
        start = self.start_time or (datetime.now(timezone.utc) - timedelta(hours=8))
        from_time = int(start.timestamp() * 1000)
        await ws.send(
            json.dumps(
                {
                    "type": "FEED_SUBSCRIPTION",
                    "channel": _CANDLE_CHANNEL,
                    "add": [
                        {
                            "symbol": _candle_symbol(sym, self.interval),
                            "type": "Candle",
                            "fromTime": from_time,
                        }
                        for sym in self.symbols
                    ],
                }
            )
        )
        logger.info("DXLink subscribed to %d symbols (%s)", len(self.symbols), self.interval)

    async def _handle_feed_data(self, data: list[Any]) -> None:
        if not data:
            return
        if isinstance(data[0], dict):
            for item in data:
                if not isinstance(item, dict):
                    continue
                bar = candle_to_bar(item)
                ticker = _ticker_from_event_symbol(str(item.get("eventSymbol") or ""))
                if bar and ticker:
                    await self._emit(ticker, bar)
            return
        if data[0] != "Candle" or len(data) < 2:
            return
        rows = data[1]
        if not isinstance(rows, list):
            return
        multiples = len(rows) // _CANDLE_FIELD_COUNT
        for i in range(multiples):
            chunk = rows[i * _CANDLE_FIELD_COUNT : (i + 1) * _CANDLE_FIELD_COUNT]
            candle = _parse_candle_compact(chunk)
            if not candle:
                continue
            bar = candle_to_bar(candle)
            ticker = _ticker_from_event_symbol(str(candle.get("eventSymbol") or ""))
            if bar and ticker:
                await self._emit(ticker, bar)

    async def _emit(self, ticker: str, bar: IntradayBar) -> None:
        if not self.on_bar:
            return
        result = self.on_bar(ticker, bar)
        if asyncio.iscoroutine(result):
            await result


def _ticker_from_event_symbol(event_symbol: str) -> str:
    if not event_symbol:
        return ""
    return event_symbol.split("{", 1)[0].upper()


async def collect_candles(
    symbols: list[str],
    *,
    interval: str = "5m",
    timeout_seconds: float = 15.0,
) -> dict[str, list[IntradayBar]]:
    collected: dict[str, list[IntradayBar]] = {s.upper(): [] for s in symbols}

    async def on_bar(ticker: str, bar: IntradayBar) -> None:
        rows = collected.setdefault(ticker, [])
        if rows and rows[-1].ts == bar.ts:
            rows[-1] = bar
        else:
            rows.append(bar)

    streamer = DXLinkCandleStreamer(symbols=symbols, interval=interval, on_bar=on_bar)
    task = asyncio.create_task(streamer.run())
    try:
        await asyncio.sleep(timeout_seconds)
    finally:
        await streamer.stop()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    return collected
