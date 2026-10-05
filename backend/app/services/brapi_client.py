"""brapi.dev quote + daily OHLC client with local file cache (quota-friendly)."""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger("fiidesk.brapi")
# httpx INFO logs full request URLs (would leak ?token=...)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# brapi.dev free tier rate-limits hard: a burst of a few requests returns 401/429.
# Space per-ticker fetches out so the swing cycle (dozens of tickers) doesn't trip it.
_MIN_INTERVAL_SECONDS = 0.6
_last_request_at = 0.0
_throttle_lock = threading.Lock()
_LAST_PRICE_TTL_SEC = 15.0
_last_price_cache: dict[tuple[str, ...], tuple[float, dict[str, float]]] = {}
_last_price_lock = threading.Lock()


def clear_last_price_cache() -> None:
    with _last_price_lock:
        _last_price_cache.clear()


def _throttle() -> None:
    global _last_request_at
    with _throttle_lock:
        now = time.monotonic()
        wait = _last_request_at + _MIN_INTERVAL_SECONDS - now
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


@dataclass
class Bar:
    date: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class BrapiClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.cache_dir = Path(self.settings.swing_cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def token(self) -> str:
        return (self.settings.brapi_token or "").strip()

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
        if time.time() - fetched_at > self.settings.swing_ohlc_ttl_seconds:
            return None
        return data

    def _write_cache(self, ticker: str, payload: dict[str, Any]) -> None:
        payload = {**payload, "fetched_at": time.time()}
        path = self._cache_path(ticker)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _h1_cache_path(self, ticker: str) -> Path:
        return self.cache_dir / f"{ticker.upper()}.1h.json"

    def _read_h1_cache(self, ticker: str) -> dict[str, Any] | None:
        path = self._h1_cache_path(ticker)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        fetched_at = float(data.get("fetched_at", 0))
        ttl = int(self.settings.swing_h1_ttl_seconds or 90 * 60)
        if time.time() - fetched_at > ttl:
            return None
        return data

    def _write_h1_cache(self, ticker: str, payload: dict[str, Any]) -> None:
        payload = {**payload, "fetched_at": time.time()}
        path = self._h1_cache_path(ticker)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def fetch_hourly_bars(self, ticker: str, *, force: bool = False) -> list[Bar]:
        """1h OHLC for swing confirmation. Separate cache/TTL from daily bars."""
        ticker = ticker.upper()
        if not force:
            cached = self._read_h1_cache(ticker)
            if cached and cached.get("bars"):
                return [_bar_from_dict(b) for b in cached["bars"]]

        bars = self._brapi_hourly_bars(ticker)
        if not bars:
            bars = self._yahoo_hourly_bars(ticker)
        if bars:
            self._write_h1_cache(
                ticker,
                {"ticker": ticker, "bars": [_bar_to_dict(b) for b in bars]},
            )
        return bars

    def _brapi_hourly_bars(self, ticker: str) -> list[Bar]:
        if not self.token:
            return []
        url = f"{self.settings.brapi_base_url.rstrip('/')}/quote/{ticker}"
        headers = {"Authorization": f"Bearer {self.token}"}
        params = {"range": "5d", "interval": "1h"}
        _throttle()
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(url, params=params, headers=headers)
        except Exception:
            logger.exception("brapi hourly fetch failed for %s", ticker)
            return []
        if resp.status_code >= 400:
            logger.warning("brapi hourly fetch failed for %s: HTTP %s", ticker, resp.status_code)
            return []
        body = resp.json()
        results = body.get("results") or []
        if not results:
            return []
        hist = results[0].get("historicalDataPrice") or []
        bars = [_parse_hist_row(row) for row in hist]
        bars = [b for b in bars if b is not None]
        bars.sort(key=lambda b: b.date)
        return bars

    def _yahoo_hourly_bars(self, ticker: str) -> list[Bar]:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; FIIDesk/1.0)"}
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}.SA"
        params = {"range": "5d", "interval": "1h"}
        try:
            with httpx.Client(timeout=20.0, headers=headers) as client:
                resp = client.get(url, params=params)
                if resp.status_code >= 400:
                    logger.warning("yahoo hourly bars %s HTTP %s", ticker, resp.status_code)
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
                bars: list[Bar] = []
                for i, ts in enumerate(timestamps):
                    if i >= len(closes) or closes[i] is None:
                        continue
                    close = float(closes[i])
                    o = float(opens[i]) if opens[i] is not None else close
                    h = float(highs[i]) if highs[i] is not None else close
                    l = float(lows[i]) if lows[i] is not None else close
                    v = float(volumes[i]) if volumes[i] is not None else 0.0
                    bars.append(
                        Bar(
                            date=datetime.fromtimestamp(ts, tz=timezone.utc),
                            open=o,
                            high=h,
                            low=l,
                            close=close,
                            volume=v,
                        )
                    )
                bars.sort(key=lambda b: b.date)
                return bars
        except Exception:
            logger.exception("yahoo hourly bars failed for %s", ticker)
            return []

    def fetch_daily_bars(self, ticker: str, *, force: bool = False) -> list[Bar]:
        ticker = ticker.upper()
        if not force:
            cached = self._read_cache(ticker)
            if cached and cached.get("bars"):
                return [_bar_from_dict(b) for b in cached["bars"]]

        bars = self._brapi_daily_bars(ticker)
        if not bars:
            # Free BRAPI tier rate-limits hard (~3 req/window); Yahoo has no quota.
            bars = self._yahoo_daily_bars(ticker)
        if bars:
            self._write_cache(
                ticker,
                {"ticker": ticker, "bars": [_bar_to_dict(b) for b in bars]},
            )
        return bars

    def _brapi_daily_bars(self, ticker: str) -> list[Bar]:
        if not self.token:
            logger.warning("BRAPI_TOKEN empty — cannot fetch %s", ticker)
            return []

        url = f"{self.settings.brapi_base_url.rstrip('/')}/quote/{ticker}"
        # Header-only auth — never put token in query (httpx/proxy logs)
        headers = {"Authorization": f"Bearer {self.token}"}
        params = {"range": "3mo", "interval": "1d"}
        _throttle()
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(url, params=params, headers=headers)
        except Exception:
            logger.exception("brapi fetch failed for %s", ticker)
            return []
        if resp.status_code >= 400:
            # Free tier rate-limits hard (~3 req/window). Fail fast — Yahoo fallback
            # in fetch_daily_bars covers the ticker without hammering BRAPI.
            logger.warning("brapi fetch failed for %s: HTTP %s", ticker, resp.status_code)
            return []
        body = resp.json()

        results = body.get("results") or []
        if not results:
            return []
        hist = results[0].get("historicalDataPrice") or []
        bars = [_parse_hist_row(row) for row in hist]
        bars = [b for b in bars if b is not None]
        bars.sort(key=lambda b: b.date)
        return bars

    def _yahoo_daily_bars(self, ticker: str) -> list[Bar]:
        """B3 daily OHLC via Yahoo chart API (ticker.SA). No API key/quota."""
        headers = {"User-Agent": "Mozilla/5.0 (compatible; FIIDesk/1.0)"}
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}.SA"
        params = {"range": "3mo", "interval": "1d"}
        try:
            with httpx.Client(timeout=20.0, headers=headers) as client:
                resp = client.get(url, params=params)
                if resp.status_code >= 400:
                    logger.warning("yahoo daily bars %s HTTP %s", ticker, resp.status_code)
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
                bars: list[Bar] = []
                for i, ts in enumerate(timestamps):
                    if i >= len(closes) or closes[i] is None:
                        continue
                    close = float(closes[i])
                    o = float(opens[i]) if opens[i] is not None else close
                    h = float(highs[i]) if highs[i] is not None else close
                    l = float(lows[i]) if lows[i] is not None else close
                    v = float(volumes[i]) if volumes[i] is not None else 0.0
                    bars.append(Bar(
                        date=datetime.fromtimestamp(ts, tz=timezone.utc),
                        open=o,
                        high=h,
                        low=l,
                        close=close,
                        volume=v,
                    ))
                bars.sort(key=lambda b: b.date)
                return bars
        except Exception:
            logger.exception("yahoo daily bars failed for %s", ticker)
            return []

    def fetch_last_prices(self, tickers: list[str]) -> dict[str, float]:
        """Current (or last) prices for tickers.

        Order: brapi batch → Yahoo Finance (.SA) → cached/fresh daily close.
        """
        wanted = sorted({t.upper().strip() for t in tickers if t and str(t).strip()})
        out: dict[str, float] = {}
        if not wanted:
            return out

        key = tuple(wanted)
        now = time.time()
        with _last_price_lock:
            hit = _last_price_cache.get(key)
            if hit and now - hit[0] < _LAST_PRICE_TTL_SEC:
                return dict(hit[1])

        if self.token:
            # brapi accepts comma-separated tickers in one request
            url = f"{self.settings.brapi_base_url.rstrip('/')}/quote/{','.join(wanted)}"
            headers = {"Authorization": f"Bearer {self.token}"}
            try:
                with httpx.Client(timeout=30.0) as client:
                    resp = client.get(url, headers=headers)
                    if resp.status_code < 400:
                        body = resp.json()
                        for row in body.get("results") or []:
                            sym = str(row.get("symbol") or "").upper()
                            px = row.get("regularMarketPrice")
                            if px is None:
                                px = row.get("close") or row.get("regularMarketPreviousClose")
                            if sym and px is not None:
                                try:
                                    out[sym] = float(px)
                                except (TypeError, ValueError):
                                    pass
                    else:
                        logger.warning("brapi quote batch HTTP %s", resp.status_code)
            except Exception:
                logger.exception("brapi quote batch failed")

        missing = [t for t in wanted if t not in out]
        if missing:
            out.update(self._yahoo_last_prices(missing))

        for t in wanted:
            if t in out:
                continue
            bars = self.fetch_daily_bars(t)
            if bars:
                out[t] = float(bars[-1].close)
                continue
            # Soft fallback: last cached close even if TTL expired
            stale = self._stale_cache_last_close(t)
            if stale is not None:
                out[t] = stale
        with _last_price_lock:
            _last_price_cache[key] = (time.time(), dict(out))
        return out

    def _yahoo_last_prices(self, tickers: list[str]) -> dict[str, float]:
        """B3 quotes via Yahoo chart API (ticker.SA). No API key."""
        out: dict[str, float] = {}
        headers = {"User-Agent": "Mozilla/5.0 (compatible; FIIDesk/1.0)"}
        try:
            with httpx.Client(timeout=20.0, headers=headers) as client:
                for t in tickers:
                    try:
                        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{t}.SA"
                        resp = client.get(url)
                        if resp.status_code >= 400:
                            logger.warning("yahoo quote %s HTTP %s", t, resp.status_code)
                            continue
                        result = ((resp.json().get("chart") or {}).get("result") or [None])[0]
                        if not result:
                            continue
                        meta = result.get("meta") or {}
                        px = meta.get("regularMarketPrice")
                        if px is None:
                            px = meta.get("previousClose") or meta.get("chartPreviousClose")
                        if px is not None:
                            out[t] = float(px)
                    except Exception:
                        logger.exception("yahoo quote failed for %s", t)
        except Exception:
            logger.exception("yahoo quote batch failed")
        return out

    def _stale_cache_last_close(self, ticker: str) -> float | None:
        path = self._cache_path(ticker)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            bars = data.get("bars") or []
            if not bars:
                return None
            return float(bars[-1]["close"])
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None


def _parse_hist_row(row: dict[str, Any]) -> Bar | None:
    try:
        raw_date = row.get("date")
        if isinstance(raw_date, (int, float)):
            dt = datetime.fromtimestamp(raw_date, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
        return Bar(
            date=dt,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row.get("volume") or 0),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _bar_to_dict(b: Bar) -> dict[str, Any]:
    return {
        "date": b.date.isoformat(),
        "open": b.open,
        "high": b.high,
        "low": b.low,
        "close": b.close,
        "volume": b.volume,
    }


def _bar_from_dict(d: dict[str, Any]) -> Bar:
    return Bar(
        date=datetime.fromisoformat(d["date"]),
        open=float(d["open"]),
        high=float(d["high"]),
        low=float(d["low"]),
        close=float(d["close"]),
        volume=float(d["volume"]),
    )
