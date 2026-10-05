"""Last-good quote cache and tasty/yahoo fallback (no arq.Retry on 502)."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.services.brapi_client import Bar
from app.services.market_data import MarketDataClient, clear_live_price_cache


@pytest.fixture(autouse=True)
def _isolate_live_price_cache():
    clear_live_price_cache()
    yield
    clear_live_price_cache()


def _client(tmp_path) -> MarketDataClient:
    md = MarketDataClient()
    md.cache_dir = tmp_path
    md.last_quote_sources = {}
    return md


def _bar(close: float) -> Bar:
    return Bar(
        date=datetime(2026, 9, 10, tzinfo=timezone.utc),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1e6,
    )


def test_tasty_502_falls_back_to_yahoo(tmp_path, caplog):
    md = _client(tmp_path)
    md._fetch_tastytrade_quotes = MagicMock(return_value={})
    md.fetch_daily_bars = MagicMock(return_value=[_bar(10.0)])

    with caplog.at_level(logging.INFO, logger="fiidesk.market_data"):
        out = md.fetch_last_prices(["XYZ"])

    assert out == {"XYZ": 10.0}
    assert md.last_quote_sources["XYZ"] == "yahoo"
    assert "quote fallback source=yahoo" in caplog.text


def test_both_empty_uses_last_good_cache(tmp_path, caplog):
    md = _client(tmp_path)
    md._remember_quote("XYZ", 9.5, "yahoo")
    md._fetch_tastytrade_quotes = MagicMock(return_value={})
    md.fetch_daily_bars = MagicMock(return_value=[])

    with caplog.at_level(logging.INFO, logger="fiidesk.market_data"):
        out = md.fetch_last_prices(["XYZ"])

    assert out == {"XYZ": 9.5}
    assert md.last_quote_sources["XYZ"] == "cache"
    assert "quote fallback source=cache" in caplog.text


def test_both_empty_no_cache_omits_ticker(tmp_path):
    md = _client(tmp_path)
    md._fetch_tastytrade_quotes = MagicMock(return_value={})
    md.fetch_daily_bars = MagicMock(return_value=[])
    assert md.fetch_last_prices(["XYZ"]) == {}
    assert md.last_quote_sources == {}


def test_expired_cache_omits_ticker(tmp_path, monkeypatch):
    md = _client(tmp_path)
    md._remember_quote("XYZ", 9.5, "yahoo")
    quotes = md._load_last_quotes()
    quotes["XYZ"]["ts"] = time.time() - 25 * 3600
    md._save_last_quotes(quotes)
    md._fetch_tastytrade_quotes = MagicMock(return_value={})
    md.fetch_daily_bars = MagicMock(return_value=[])
    assert md.fetch_last_prices(["XYZ"]) == {}
