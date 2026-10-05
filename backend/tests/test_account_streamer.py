"""Account Streamer Order events + unique ARQ enqueue."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.tastytrade_account_streamer import (
    TASTY_RECONCILE_EXPIRES_SECONDS,
    TASTY_RECONCILE_JOB_ID,
    TASTY_RECONCILE_JOB_NAME,
    classify_order_event,
    connect_ack_ok,
    enqueue_tasty_reconcile,
    stream_event_should_enqueue,
    unwrap_order_event,
)
from app.workers.arq_settings import WorkerSettings, job_tasty_reconcile_fn
from app.workers.jobs import job_tasty_reconcile


LIVE_ORDER = {
    "type": "Order",
    "data": {
        "id": 1650607,
        "status": "Live",
        "cancellable": True,
        "ext-client-order-id": "cid-nvda-1",
        "legs": [
            {
                "instrument-type": "Equity",
                "symbol": "NVDA",
                "quantity": 1,
                "remaining-quantity": 1,
                "action": "Buy to Open",
                "fills": [],
            }
        ],
    },
}

FILLED_ORDER = {
    "type": "Order",
    "data": {
        "id": 1650607,
        "status": "Filled",
        "cancellable": False,
        "ext-client-order-id": "cid-nvda-1",
        "legs": [
            {
                "instrument-type": "Equity",
                "symbol": "NVDA",
                "quantity": 1,
                "remaining-quantity": 0,
                "action": "Buy to Open",
                "fills": [{"fill-price": 218.5}],
            }
        ],
    },
}


def test_live_remaining_is_working_does_not_enqueue():
    kind, should = classify_order_event(LIVE_ORDER)
    assert kind == "working"
    assert should is False
    assert unwrap_order_event(LIVE_ORDER)["id"] == 1650607


def test_filled_remaining_zero_enqueues():
    kind, should = classify_order_event(FILLED_ORDER)
    assert kind == "filled"
    assert should is True


def test_non_order_message_ignored():
    kind, should = classify_order_event({"type": "Heartbeat", "status": "ok"})
    assert kind is None
    assert should is False


def test_enqueue_duplicate_job_id_returns_false():
    import asyncio

    class _Redis:
        def __init__(self) -> None:
            self.seen: set[str] = set()
            self.calls: list[tuple[str, str | None]] = []

        async def enqueue_job(self, name, *, _job_id=None, _expires=None):
            self.calls.append((name, _job_id, _expires))
            if _job_id in self.seen:
                return None
            self.seen.add(_job_id)
            return SimpleNamespace(job_id=_job_id)

    async def _run():
        redis = _Redis()
        first = await enqueue_tasty_reconcile(redis=redis)
        second = await enqueue_tasty_reconcile(redis=redis)
        assert first is True
        assert second is False
        assert redis.calls == [
            (TASTY_RECONCILE_JOB_NAME, TASTY_RECONCILE_JOB_ID, 300),
            (TASTY_RECONCILE_JOB_NAME, TASTY_RECONCILE_JOB_ID, 300),
        ]

    asyncio.run(_run())


def test_reconcile_job_wrapped_with_func_timeout_and_keep_result():
    assert job_tasty_reconcile_fn.name == "job_tasty_reconcile"
    assert job_tasty_reconcile_fn.timeout_s == 120
    assert job_tasty_reconcile_fn.keep_result_s == 30
    assert job_tasty_reconcile_fn in WorkerSettings.functions
    cron_names = [c.name for c in WorkerSettings.cron_jobs]
    assert any(name.endswith("job_tasty_reconcile") for name in cron_names)
    cron = next(c for c in WorkerSettings.cron_jobs if c.name.endswith("job_tasty_reconcile"))
    assert cron.unique is True
    assert cron.max_tries == 1
    assert cron.coroutine is job_tasty_reconcile
    assert TASTY_RECONCILE_EXPIRES_SECONDS == 300


def test_current_position_and_balance_enqueue():
    assert stream_event_should_enqueue({"type": "CurrentPosition", "data": {"symbol": "NVDA"}})
    assert stream_event_should_enqueue({"type": "Balance", "data": {}})
    assert not stream_event_should_enqueue({"type": "Heartbeat", "status": "ok"})


def test_connect_ack_ok_only_after_connect():
    assert connect_ack_ok({"status": "ok", "action": "connect", "web-socket-session-id": "abc"})
    assert not connect_ack_ok({"status": "ok", "action": "heartbeat"})
    assert not connect_ack_ok({"type": "Order", "data": {"status": "Live"}})


def test_replace_requested_is_working_does_not_enqueue():
    kind, should = classify_order_event(
        {
            "type": "Order",
            "data": {
                "id": 1,
                "status": "Replace Requested",
                "legs": [{"remaining-quantity": 1, "fills": []}],
            },
        }
    )
    assert kind == "working"
    assert should is False


def test_removed_is_cancelled_enqueues():
    kind, should = classify_order_event(
        {"type": "Order", "data": {"id": 1, "status": "Removed", "legs": []}}
    )
    assert kind == "cancelled"
    assert should is True
