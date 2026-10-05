"""Swing 1h confirmation: ok / fail / skip (fail-open)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.brapi_client import Bar
from app.services.swing import engine as swing_engine
from app.services.swing.indicators import hourly_confirmation_status, last_closed_hourly
from app.workers.arq_settings import WorkerSettings


NOW = datetime(2026, 9, 11, 16, 0, tzinfo=timezone.utc)


def _bar(hours_ago: int, *, close: float, low: float) -> Bar:
    dt = NOW - timedelta(hours=hours_ago)
    return Bar(
        date=dt,
        open=close,
        high=close + 1,
        low=low,
        close=close,
        volume=1_000_000,
    )


def test_hourly_ok_hold_above_breakout():
    bars = [_bar(3, close=110, low=106)]
    assert hourly_confirmation_status(bars, breakout_level=105, stop=100, now=NOW) == "h1_ok"


def test_hourly_fail_undercuts_stop():
    bars = [_bar(3, close=110, low=98)]
    assert hourly_confirmation_status(bars, breakout_level=105, stop=100, now=NOW) == "h1_fail"


def test_hourly_skip_no_bars():
    assert hourly_confirmation_status(None, breakout_level=105, stop=100, now=NOW) == "h1_skip"
    assert hourly_confirmation_status([], breakout_level=105, stop=100, now=NOW) == "h1_skip"


def test_last_closed_drops_in_progress_hour():
    open_bar = Bar(
        date=NOW - timedelta(minutes=20),
        open=110,
        high=111,
        low=109,
        close=110,
        volume=1,
    )
    closed = _bar(3, close=108, low=107)
    picked = last_closed_hourly([closed, open_bar], now=NOW)
    assert picked is not None
    assert picked.close == 108


def _daily(n: int = 90) -> list[Bar]:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    out: list[Bar] = []
    price = 100.0
    for i in range(n):
        price = 100.0 + 0.4 * i
        high = price + 1.5
        low = price - 1.0
        vol = 2_000_000.0
        if i == n - 1:
            price = price + 6
            high = price + 1
            vol = 4_000_000.0
        out.append(
            Bar(
                date=start + timedelta(days=i),
                open=price,
                high=high,
                low=low,
                close=price,
                volume=vol,
            )
        )
    return out


class _Client:
    def __init__(self, hourly: list[Bar] | None):
        self.hourly = hourly
        self.hourly_calls = 0

    def fetch_daily_bars(self, ticker: str, *, force: bool = False) -> list[Bar]:
        return _daily()

    def fetch_hourly_bars(self, ticker: str, *, force: bool = False) -> list[Bar] | None:
        self.hourly_calls += 1
        return self.hourly


def _live_bar(hours_ago: int, *, close: float, low: float) -> Bar:
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    dt = dt.replace(minute=0, second=0, microsecond=0)
    return Bar(
        date=dt,
        open=close,
        high=close + 1,
        low=low,
        close=close,
        volume=1_000_000,
    )


def _patch_dw(monkeypatch) -> None:
    monkeypatch.setattr(swing_engine, "weekly_trend_bullish", lambda *a, **k: True)
    monkeypatch.setattr(
        swing_engine, "daily_breakout_long", lambda bars, n=10: (True, 105.0)
    )
    monkeypatch.setattr(
        swing_engine, "trend_context_allows_long", lambda *a, **k: (True, "ok")
    )


def test_analyze_ticker_h1_ok_keeps_candidate(monkeypatch):
    _patch_dw(monkeypatch)
    client = _Client([_live_bar(3, close=110, low=106)])
    stats = {"h1_ok": 0, "h1_skip": 0, "h1_fail": 0}
    row = swing_engine.analyze_ticker("PETR4", client, stats=stats)
    assert row is not None
    assert row["h1_status"] == "h1_ok"
    assert client.hourly_calls == 1
    assert stats == {"h1_ok": 1, "h1_skip": 0, "h1_fail": 0}


def test_analyze_ticker_h1_fail_drops_candidate(monkeypatch):
    _patch_dw(monkeypatch)
    client = _Client([_live_bar(3, close=90, low=80)])
    stats = {"h1_ok": 0, "h1_skip": 0, "h1_fail": 0}
    row = swing_engine.analyze_ticker("PETR4", client, stats=stats)
    assert client.hourly_calls == 1
    assert row is None, (row or {}).get("h1_status")
    assert stats["h1_fail"] == 1
    assert stats["h1_ok"] == 0


def test_analyze_ticker_h1_skip_keeps_candidate(monkeypatch):
    _patch_dw(monkeypatch)
    client = _Client(None)
    stats = {"h1_ok": 0, "h1_skip": 0, "h1_fail": 0}
    row = swing_engine.analyze_ticker("PETR4", client, stats=stats)
    assert row is not None
    assert row["h1_status"] == "h1_skip"
    assert stats["h1_skip"] == 1


def test_swing_cron_unchanged():
    crons = WorkerSettings.cron_jobs
    swing = [c for c in crons if getattr(c, "coroutine", None) is not None]
    names = [getattr(c.coroutine, "__name__", "") for c in crons]
    assert "job_swing_dw" in names
    job = next(c for c in crons if getattr(c.coroutine, "__name__", "") == "job_swing_dw")
    assert job.hour == {0, 6, 12, 18}
    assert job.minute == 10
    assert len([n for n in names if n == "job_swing_dw"]) == 1
    _ = SimpleNamespace(swing=swing)
