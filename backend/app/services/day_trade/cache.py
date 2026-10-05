"""File + optional Redis cache for intraday 5m bars."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services.day_trade.bars import IntradayBar

logger = logging.getLogger("fiidesk.day_trade.cache")

_MAX_BARS = 120


def _valid_bar(bar: IntradayBar) -> bool:
    import math

    vals = (bar.open, bar.high, bar.low, bar.close, bar.volume)
    return all(
        isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in vals
    )


def _filter_valid(bars: list[IntradayBar]) -> list[IntradayBar]:
    return [b for b in bars if _valid_bar(b)]


class DayTradeBarCache:
    def __init__(self) -> None:
        settings = get_settings()
        self.cache_dir = Path(settings.day_trade_cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._redis = None
        try:
            import redis

            self._redis = redis.from_url(settings.redis_url, decode_responses=True)
            self._redis.ping()
        except Exception:
            self._redis = None
            logger.debug("Redis unavailable — using file cache for day trade bars")

    def _file_path(self, ticker: str) -> Path:
        return self.cache_dir / f"{ticker.upper()}.json"

    def _redis_key(self, ticker: str) -> str:
        return f"day_trade:bars:{ticker.upper()}"

    def get_bars(self, ticker: str) -> list[IntradayBar]:
        ticker = ticker.upper()
        if self._redis:
            try:
                raw = self._redis.get(self._redis_key(ticker))
                if raw:
                    data = json.loads(raw)
                    return _filter_valid(
                        [IntradayBar.from_dict(b) for b in data.get("bars", [])]
                    )
            except Exception:
                logger.exception("Redis read failed for %s", ticker)
        path = self._file_path(ticker)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return _filter_valid(
                [IntradayBar.from_dict(b) for b in data.get("bars", [])]
            )
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return []

    def append_bar(self, ticker: str, bar: IntradayBar) -> list[IntradayBar]:
        import math

        if any(
            math.isnan(v) or math.isinf(v) or v <= 0
            for v in (bar.open, bar.high, bar.low, bar.close, bar.volume)
        ):
            logger.debug("Skip invalid bar for %s at %s", ticker, bar.ts)
            return self.get_bars(ticker)
        ticker = ticker.upper()
        bars = self.get_bars(ticker)
        if bars and bars[-1].ts == bar.ts:
            bars[-1] = bar
        elif not bars or bar.ts > bars[-1].ts:
            bars.append(bar)
        bars = bars[-_MAX_BARS:]
        self._save(ticker, bars)
        return bars

    def set_bars(self, ticker: str, bars: list[IntradayBar]) -> None:
        bars = sorted(bars, key=lambda b: b.ts)[-_MAX_BARS:]
        self._save(ticker.upper(), bars)

    def _save(self, ticker: str, bars: list[IntradayBar]) -> None:
        payload: dict[str, Any] = {"ticker": ticker, "bars": [b.to_dict() for b in bars]}
        raw = json.dumps(payload)
        if self._redis:
            try:
                self._redis.set(self._redis_key(ticker), raw, ex=86400)
            except Exception:
                logger.exception("Redis write failed for %s", ticker)
        self._file_path(ticker).write_text(raw, encoding="utf-8")

    def list_tickers(self) -> list[str]:
        tickers = {p.stem for p in self.cache_dir.glob("*.json")}
        return sorted(tickers)
