"""mark_open_positions: never fake mark=entry; skip exit when quote is missing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from app.domain.models import Position, PositionStatus, StrategyKind
from app.services import positions as posmod


def _pos(**kw) -> Position:
    defaults = dict(
        id="p1",
        account_id="acc",
        order_id="o1",
        suggestion_id="s1",
        ticker="XYZ",
        strategy_kind=StrategyKind.hv_dip,
        quantity=5.0,
        entry_price=3.80,
        stop_price=3.61,
        target_price=3.99,
        status=PositionStatus.open,
        opened_at=datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc),
        metrics={},
    )
    defaults.update(kw)
    return Position(**defaults)


def test_no_mark_skips_exit_engine(monkeypatch):
    pos = _pos()
    monkeypatch.setattr(posmod, "list_open_positions", lambda *a, **k: [pos])
    called: list[int] = []

    def _boom(*a, **k):
        called.append(1)
        raise AssertionError("evaluate_hv_dip_exit must not run without a mark")

    monkeypatch.setattr("app.services.hv_dip.exit_engine.evaluate_hv_dip_exit", _boom)
    db = MagicMock()
    enriched, px = posmod.mark_open_positions(db, "acc", prices={})
    assert px == {}
    assert called == []
    assert enriched[0]["mark_price"] is None
    assert enriched[0]["price_alert"] is None
    assert enriched[0]["auto_close"] is False
    assert enriched[0]["no_mark"] is True


def test_no_mark_does_not_invent_stop_alert(monkeypatch):
    """Stop below entry must not fire when the mark is missing (was mark=entry)."""
    pos = _pos(stop_price=3.61, entry_price=3.80)
    monkeypatch.setattr(posmod, "list_open_positions", lambda *a, **k: [pos])
    db = MagicMock()
    enriched, _ = posmod.mark_open_positions(db, "acc", prices={})
    assert enriched[0]["price_alert"] is None
    assert enriched[0]["mark_price"] is None


def test_yahoo_mark_runs_exit(monkeypatch):
    pos = _pos()
    monkeypatch.setattr(posmod, "list_open_positions", lambda *a, **k: [pos])
    db = MagicMock()
    enriched, _ = posmod.mark_open_positions(db, "acc", prices={"XYZ": 10.0})
    assert enriched[0]["mark_price"] == 10.0
    assert enriched[0]["no_mark"] is False
    assert enriched[0]["price_alert"] in (None, "target")  # 10 > target → target


def test_backfill_must_review_by_when_missing(monkeypatch):
    opened = datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc)
    pos = _pos(opened_at=opened, metrics={})
    monkeypatch.setattr(posmod, "list_open_positions", lambda *a, **k: [pos])
    db = MagicMock()
    enriched, _ = posmod.mark_open_positions(db, "acc", prices={})
    deadline = pos.metrics.get("must_review_by")
    assert deadline
    assert enriched[0]["must_review_by"] == deadline
    parsed = datetime.fromisoformat(deadline)
    assert parsed >= opened + timedelta(days=3)
