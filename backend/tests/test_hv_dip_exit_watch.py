"""exit_watch: always log auto-close, exit_hold, or exit_skip no_mark."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from app.config import Settings
from app.domain.models import (
    AccountCurrency,
    ExecutionMode,
    InvestmentAccount,
    Position,
    PositionStatus,
    StrategyKind,
)
from app.services.hv_dip import exit_watch as ew


def _account() -> InvestmentAccount:
    return InvestmentAccount(
        id="acc1",
        name="NM USD Paper",
        owner_user_id="u1",
        broker_code="tastytrade",
        currency=AccountCurrency.USD,
        execution_mode=ExecutionMode.paper,
        cash_usd=81.0,
        automation_paused=False,
    )


def _pos() -> Position:
    return Position(
        id="p1",
        account_id="acc1",
        order_id="o1",
        suggestion_id="s1",
        ticker="XYZ",
        strategy_kind=StrategyKind.hv_dip,
        quantity=5.0,
        entry_price=3.80,
        stop_price=3.61,
        target_price=3.99,
        status=PositionStatus.open,
        opened_at=datetime(2026, 9, 7, tzinfo=timezone.utc),
        metrics={"must_review_by": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()},
    )


def _db(account: InvestmentAccount) -> MagicMock:
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [account]
    return db


def test_exit_watch_logs_hold(monkeypatch, caplog):
    pos = _pos()
    deadline = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    monkeypatch.setattr(
        ew,
        "mark_open_positions",
        lambda *a, **k: (
            [
                {
                    "position": pos,
                    "mark_price": 3.80,
                    "price_alert": None,
                    "auto_close": False,
                    "must_review_by": deadline,
                    "quote_source": "yahoo",
                    "no_mark": False,
                }
            ],
            {"XYZ": 3.80},
        ),
    )
    closed: list = []
    monkeypatch.setattr(ew, "close_position", lambda *a, **k: closed.append(1))
    with caplog.at_level(logging.INFO, logger="fiidesk.hv_dip.exit_watch"):
        n = ew.run_hv_dip_exit_watch(_db(_account()))
    assert n == 0
    assert closed == []
    assert "exit_hold XYZ" in caplog.text
    assert "mark=3.80" in caplog.text


def test_exit_watch_auto_close_stop(monkeypatch, caplog):
    pos = _pos()
    monkeypatch.setattr(
        ew,
        "get_settings",
        lambda: Settings(hv_dip_auto_close_enabled=True),
    )
    monkeypatch.setattr(
        ew,
        "mark_open_positions",
        lambda *a, **k: (
            [
                {
                    "position": pos,
                    "mark_price": 3.50,
                    "price_alert": "stop",
                    "auto_close": True,
                    "must_review_by": None,
                    "quote_source": "yahoo",
                    "no_mark": False,
                }
            ],
            {"XYZ": 3.50},
        ),
    )
    closed: list = []
    monkeypatch.setattr(ew, "close_position", lambda *a, **k: closed.append(k.get("reason") or a[2:]))
    with caplog.at_level(logging.INFO, logger="fiidesk.hv_dip.exit_watch"):
        n = ew.run_hv_dip_exit_watch(_db(_account()))
    assert n == 1
    assert closed
    assert "auto-close XYZ stop mark=3.50 source=yahoo" in caplog.text


def test_exit_watch_skip_no_mark(monkeypatch, caplog):
    pos = _pos()
    monkeypatch.setattr(
        ew,
        "mark_open_positions",
        lambda *a, **k: (
            [
                {
                    "position": pos,
                    "mark_price": None,
                    "price_alert": None,
                    "auto_close": False,
                    "must_review_by": None,
                    "quote_source": "none",
                    "no_mark": True,
                }
            ],
            {},
        ),
    )
    closed: list = []
    monkeypatch.setattr(ew, "close_position", lambda *a, **k: closed.append(1))
    with caplog.at_level(logging.INFO, logger="fiidesk.hv_dip.exit_watch"):
        n = ew.run_hv_dip_exit_watch(_db(_account()))
    assert n == 0
    assert closed == []
    assert "exit_skip no_mark XYZ" in caplog.text
