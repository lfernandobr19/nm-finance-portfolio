"""Market data facade (tastytrade quotes + Yahoo historical bars).

Real-time quotes come from the tastytrade Open API (`/market-data/by-type`)
and deep daily history (used by the regime guard, dip scoring and backtests)
comes from Yahoo's chart API, which needs no key.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings
from app.services.brapi_client import Bar

logger = logging.getLogger("fiidesk.market_data")
logging.getLogger("httpx").setLevel(logging.WARNING)

_YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FIIDesk/1.0)"}
_LAST_QUOTES_TTL_SECONDS = 24 * 3600
_LAST_QUOTES_FILENAME = "last_quotes.json"
_LIVE_PRICE_TTL_SEC = 15.0
_live_price_cache: dict[tuple[str, ...], tuple[float, dict[str, float], dict[str, str]]] = {}


def clear_live_price_cache() -> None:
    _live_price_cache.clear()


class MarketDataClient:
    """Unified market data: tastytrade for live quotes, Yahoo for daily history."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.cache_dir = Path(self.settings.hv_dip_cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.last_quote_sources: dict[str, str] = {}

    def configured(self) -> bool:
        """Whether tastytrade credentials are present (used for live quotes)."""
        from app.services.tastytrade_client import TastytradeClient

        return TastytradeClient().configured()

    # ---- caching (daily bars) ----
    def _cache_path(self, ticker: str) -> Path:
        return self.cache_dir / f"{ticker.upper()}.json"

    def _read_cache(self, ticker: str) -> dict[str, Any] | None:
        path = self._cache_path(ticker)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        fetched_at = float(data.get("fetched_at", 0))
        if time.time() - fetched_at > self.settings.hv_dip_ohlc_ttl_seconds:
            return None
        return data

    def _write_cache(self, ticker: str, payload: dict[str, Any]) -> None:
        payload = {**payload, "fetched_at": time.time()}
        self._cache_path(ticker).write_text(json.dumps(payload), encoding="utf-8")

    # ---- daily bars (history) ----
    def fetch_daily_bars(self, ticker: str, *, force: bool = False, days: int = 400) -> list[Bar]:
        ticker = ticker.upper()
        if not force:
            cached = self._read_cache(ticker)
            if cached and cached.get("bars"):
                return [_bar_from_dict(b) for b in cached["bars"]]

        bars = self._fetch_yahoo_daily_bars(ticker, days=days)
        if bars:
            self._write_cache(
                ticker,
                {
                    "source": "yahoo",
                    "bars": [
                        {
                            "date": b.date.isoformat(),
                            "open": b.open,
                            "high": b.high,
                            "low": b.low,
                            "close": b.close,
                            "volume": b.volume,
                        }
                        for b in bars
                    ],
                },
            )
        return bars

    def fetch_daily_bars_many(self, tickers: list[str], *, days: int = 400) -> dict[str, list[Bar]]:
        """Fetch daily bars for many tickers (cache + Yahoo). Returns {TICKER: [Bar]}."""
        tickers = sorted({t.upper() for t in tickers if t})
        return {t: self.fetch_daily_bars(t, days=days) for t in tickers}

    # ---- tastytrade quotes (live) ----
    def _fetch_tastytrade_quotes(self, tickers: list[str]) -> dict[str, dict[str, float]]:
        """GET /market-data/by-type for equity quotes.

        Returns {TICKER: {"last": float, "close": float, "mark": float, "volume": float}}.
        Empty dict on any failure (callers fall back to Yahoo).
        """
        from app.services.tastytrade_client import TastytradeClient

        tt = TastytradeClient()
        if not tt.configured():
            return {}
        symbols = ",".join(sorted({t.upper() for t in tickers if t}))
        if not symbols:
            return {}
        url = f"{tt.base_url}/market-data/by-type"
        try:
            with httpx.Client(timeout=20.0) as client:
                resp = client.get(
                    url,
                    headers=tt._auth_headers(),
                    params={"equity": symbols},
                )
                if resp.status_code >= 400:
                    logger.warning("tastytrade quotes HTTP %s", resp.status_code)
                    return {}
                data = resp.json()
        except Exception:
            logger.exception("tastytrade quotes failed")
            return {}

        out: dict[str, dict[str, float]] = {}
        items = ((data.get("data") or {}).get("items")) or []
        for item in items:
            if not isinstance(item, dict):
                continue
            sym = str(item.get("symbol") or "").upper()
            if not sym:
                continue
            try:
                out[sym] = {
                    "last": _to_float(item.get("last")),
                    "close": _to_float(item.get("close")),
                    "mark": _to_float(item.get("mark")),
                    "volume": _to_float(item.get("volume")),
                }
            except (TypeError, ValueError):
                continue
        return out

    def _last_quotes_path(self) -> Path:
        return self.cache_dir / _LAST_QUOTES_FILENAME

    def _load_last_quotes(self) -> dict[str, Any]:
        path = self._last_quotes_path()
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        quotes = data.get("quotes") if isinstance(data, dict) else None
        if isinstance(quotes, dict):
            return quotes
        return data if isinstance(data, dict) else {}

    def _save_last_quotes(self, quotes: dict[str, Any]) -> None:
        payload = {"updated_at": time.time(), "quotes": quotes}
        self._last_quotes_path().write_text(json.dumps(payload), encoding="utf-8")

    def _remember_quote(self, ticker: str, price: float, source: str) -> None:
        quotes = self._load_last_quotes()
        quotes[ticker] = {"price": float(price), "ts": time.time(), "source": source}
        self._save_last_quotes(quotes)

    def _cached_quote(self, ticker: str) -> float | None:
        row = self._load_last_quotes().get(ticker)
        if not isinstance(row, dict):
            return None
        try:
            ts = float(row.get("ts") or 0)
            price = float(row.get("price") or 0)
        except (TypeError, ValueError):
            return None
        if price <= 0 or time.time() - ts > _LAST_QUOTES_TTL_SECONDS:
            return None
        return price

    def fetch_last_prices(self, tickers: list[str]) -> dict[str, float]:
        """Best-effort live price: tastytrade, Yahoo close, then last-good cache.

        A 502/empty tastytrade response is a skip (next cron retries). Never raise
        ``arq.Retry`` here — that would storm Redis on a broker outage.
        """
        tickers = sorted({t.upper() for t in tickers if t})
        self.last_quote_sources = {}
        if not tickers:
            return {}

        key = tuple(tickers)
        now = time.time()
        hit = _live_price_cache.get(key)
        if hit and now - hit[0] < _LIVE_PRICE_TTL_SEC:
            self.last_quote_sources = dict(hit[2])
            return dict(hit[1])

        quotes = self._fetch_tastytrade_quotes(tickers)
        out: dict[str, float] = {}
        for t in tickers:
            q = quotes.get(t)
            price = None
            if q:
                price = q.get("last") or q.get("close") or q.get("mark")
            if price and float(price) > 0:
                px = float(price)
                out[t] = px
                self.last_quote_sources[t] = "tasty"
                self._remember_quote(t, px, "tasty")
                continue
            bars = self.fetch_daily_bars(t)
            if bars:
                px = float(bars[-1].close)
                if px > 0:
                    logger.info("quote fallback source=yahoo ticker=%s price=%.4f", t, px)
                    out[t] = px
                    self.last_quote_sources[t] = "yahoo"
                    self._remember_quote(t, px, "yahoo")
                    continue
            cached = self._cached_quote(t)
            if cached is not None:
                logger.info("quote fallback source=cache ticker=%s price=%.4f", t, cached)
                out[t] = cached
                self.last_quote_sources[t] = "cache"
        _live_price_cache[key] = (time.time(), dict(out), dict(self.last_quote_sources))
        return out

    def fetch_snapshots_many(self, tickers: list[str]) -> dict[str, dict]:
        """Latest price + volume (liquidity filter): tastytrade quote, else Yahoo close."""
        tickers = sorted({t.upper() for t in tickers if t})
        out: dict[str, dict] = {}
        if not tickers:
            return out

        quotes = self._fetch_tastytrade_quotes(tickers)
        for t in tickers:
            q = quotes.get(t)
            price = None
            volume = 0.0
            if q:
                price = q.get("last") or q.get("close") or q.get("mark")
                volume = q.get("volume") or 0.0
            if not price or price <= 0:
                bars = self.fetch_daily_bars(t)
                if not bars:
                    continue
                price = float(bars[-1].close)
                volume = float(bars[-1].volume or 0.0)
            out[t] = {
                "price": float(price),
                "volume": float(volume),
                "dollar_volume": float(price) * float(volume),
            }
        return out

    def fetch_intraday_bars(
        self,
        ticker: str,
        *,
        timeframe: str = "5Min",
        days: int = 5,
    ) -> list[Any]:
        """Historical intraday bars.

        Day-trade study now uses the tastytrade DXLink streamer
        (`app.services.tastytrade_market_data.collect_candles`) instead of a
        polled REST feed. This method remains for compatibility and returns an
        empty list.
        """
        logger.info("intraday backfill skipped for %s (use DXLink collector)", ticker)
        return []

    # ---- Yahoo daily history ----
    def _fetch_yahoo_daily_bars(self, ticker: str, *, days: int) -> list[Bar]:
        """US equities daily OHLC via Yahoo chart API (no key)."""
        yahoo_range = "2y" if days <= 730 else "5y"
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker.upper()}"
        params = {"interval": "1d", "range": yahoo_range}
        try:
            with httpx.Client(timeout=30.0, headers=_YAHOO_HEADERS) as client:
                resp = client.get(url, params=params)
                if resp.status_code >= 400:
                    logger.warning("yahoo bars %s HTTP %s", ticker, resp.status_code)
                    return []
                result = ((resp.json().get("chart") or {}).get("result") or [None])[0]
                if not result:
                    return []
                timestamps = result.get("timestamp") or []
                quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
                opens = quote.get("open") or []
                highs = quote.get("high") or []
                lows = quote.get("low") or []
                closes = quote.get("close") or []
                volumes = quote.get("volume") or []
        except Exception:
            logger.exception("yahoo bars failed for %s", ticker)
            return []

        bars: list[Bar] = []
        for i, ts in enumerate(timestamps):
            try:
                o, h, l, c = opens[i], highs[i], lows[i], closes[i]
                if None in (o, h, l, c):
                    continue
                vol = volumes[i] if i < len(volumes) and volumes[i] is not None else 0.0
                bars.append(
                    Bar(
                        date=datetime.fromtimestamp(int(ts), tz=timezone.utc),
                        open=float(o),
                        high=float(h),
                        low=float(l),
                        close=float(c),
                        volume=float(vol),
                    )
                )
            except (IndexError, TypeError, ValueError):
                continue
        bars.sort(key=lambda b: b.date)
        return bars


def _to_float(value: Any) -> float:
    """Coerce tastytrade string/number fields to float; 0.0 when empty."""
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _bar_from_dict(b: dict[str, Any]) -> Bar:
    dt = datetime.fromisoformat(str(b["date"]).replace("Z", "+00:00"))
    return Bar(
        date=dt,
        open=float(b["open"]),
        high=float(b["high"]),
        low=float(b["low"]),
        close=float(b["close"]),
        volume=float(b.get("volume") or 0),
    )
