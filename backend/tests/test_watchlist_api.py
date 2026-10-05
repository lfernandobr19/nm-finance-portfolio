"""Tests for the watchlist (observação) schemas and serialization."""

from __future__ import annotations

from datetime import datetime, timezone

from app.schemas import WatchlistAddIn, WatchlistItemOut

NOW = datetime.now(timezone.utc)


def test_watchlist_item_out_from_attributes():
    out = WatchlistItemOut(
        id="w1",
        account_id="a1",
        ticker="PETR4",
        note="alta de petróleo",
        created_at=NOW,
        price=34.56789,
        prev_close=33.0,
        change_pct=4.7509,
        currency="BRL",
    )
    dump = out.model_dump()
    assert out.ticker == "PETR4"
    assert dump["price"] == 34.5679
    assert dump["prev_close"] == 33.0
    assert dump["change_pct"] == 4.7509
    assert dump["currency"] == "BRL"


def test_watchlist_item_out_defaults_and_null_quote():
    out = WatchlistItemOut(id="w2", account_id="a1", ticker="AAPL")
    dump = out.model_dump()
    assert dump["price"] is None
    assert dump["prev_close"] is None
    assert dump["change_pct"] is None
    assert dump["currency"] == "BRL"
    assert dump["note"] is None


def test_watchlist_add_in_validates_ticker():
    body = WatchlistAddIn(ticker="  nvda ", note="obs")
    assert body.ticker == "  nvda "
    assert body.note == "obs"


def test_watchlist_add_in_min_length():
    try:
        WatchlistAddIn(ticker="")
        assert False, "expected validation error"
    except Exception:
        pass
