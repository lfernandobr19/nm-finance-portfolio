"""Closed-trade LLM review never touches the desk gate."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.domain.models import Position, PositionStatus, StrategyKind
from app.services import trade_review as tr
from app.services.llm_client import LlmResult


def test_review_writes_metrics_without_gate(monkeypatch):
    pos = Position(
        id="p1",
        account_id="acc",
        order_id="o1",
        suggestion_id="s1",
        ticker="XYZ",
        strategy_kind=StrategyKind.hv_dip,
        quantity=5,
        entry_price=3.8,
        stop_price=3.34,
        target_price=4.72,
        status=PositionStatus.closed,
        exit_price=3.5,
        r_multiple_realized=-0.65,
        closed_at=datetime.now(timezone.utc),
        metrics={},
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
        pos
    ]
    gate = MagicMock()
    monkeypatch.setattr("app.services.desk_gate.evaluate_gate", gate)
    monkeypatch.setattr(tr, "local_configured", lambda: True)
    monkeypatch.setattr(tr, "cloud_configured", lambda: False)
    monkeypatch.setattr(tr, "_headlines", lambda db, ticker: [])
    monkeypatch.setattr(
        "app.services.learn.harvest.harvest_trade_review", lambda *a, **k: None
    )
    monkeypatch.setattr(
        tr,
        "chat",
        lambda *a, **k: LlmResult(
            content=json.dumps(
                {"lesson": "stop hit", "would_change": "none", "confidence": 0.7}
            ),
            source="ollama",
            status=200,
            model="qwen2.5:7b",
        ),
    )
    n = tr.review_closed_positions(db)
    assert n == 1
    assert pos.metrics["llm_review"]["lesson"] == "stop hit"
    assert pos.metrics["llm_review"]["source"] == "ollama"
    gate.assert_not_called()


def test_review_skip_none_closed(monkeypatch, caplog):
    import logging

    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
    monkeypatch.setattr(tr, "local_configured", lambda: True)
    monkeypatch.setattr(tr, "cloud_configured", lambda: True)
    with caplog.at_level(logging.INFO, logger="fiidesk.trade_review"):
        n = tr.review_closed_positions(db)
    assert n == 0
    assert "review_skip none_closed" in caplog.text
