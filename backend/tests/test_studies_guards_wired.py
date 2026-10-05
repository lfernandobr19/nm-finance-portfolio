"""Guards written for every channel are now read by the engine that owns it.

Before this, ``evaluate`` happily wrote ``swing:breakout_h1`` and
``day_trade:orb`` guards and nothing ever looked at them.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.services.day_trade.bars import IntradayBar
from app.services.studies.apply import (
    day_trade_rule_notes,
    guard_for,
    hv_dip_force_review,
    swing_force_review,
)


@pytest.fixture
def guards(monkeypatch, tmp_path):
    path = tmp_path / "study_guard.json"
    monkeypatch.setattr("app.services.studies.apply.GUARD_PATH", path)

    def _write(payload: dict) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")

    _write({})
    return _write


def test_guard_for_reads_any_channel(guards):
    guards({"swing:breakout_h1": {"force_review": True, "reason": "rompimento fraco"}})
    force, reason = guard_for("swing", "breakout_h1")
    assert force is True
    assert reason == "rompimento fraco"


def test_guard_for_is_quiet_when_absent(guards):
    assert guard_for("swing", "breakout_h1") == (False, None)


def test_a_guard_on_one_channel_does_not_leak_to_another(guards):
    guards({"day_trade:orb": {"force_review": True, "reason": "orb fraco"}})
    assert hv_dip_force_review() == (False, None)
    assert swing_force_review() == (False, None)
    assert day_trade_rule_notes() == {"opening_range_break": "orb fraco"}


def test_the_orb_fingerprint_maps_to_its_rule_id(guards):
    """The study calls it 'orb'; the rule that fires calls itself
    'opening_range_break'. A guard keyed on the wrong name blocks nothing."""
    guards({"day_trade:orb": {"force_review": True, "reason": "orb fraco"}})
    assert "orb" not in day_trade_rule_notes()
    assert day_trade_rule_notes()["opening_range_break"] == "orb fraco"


def test_force_review_false_is_not_a_guard(guards):
    guards({"swing:breakout_h1": {"force_review": False, "reason": "ok"}})
    assert swing_force_review() == (False, None)


def test_day_trade_collects_every_blocked_rule(guards):
    guards({
        "day_trade:orb": {"force_review": True, "reason": "orb fraco"},
        "day_trade:vwap_reclaim": {"force_review": True, "reason": "vwap fraco"},
    })
    assert day_trade_rule_notes() == {
        "opening_range_break": "orb fraco",
        "vwap_reclaim": "vwap fraco",
    }


def test_a_guard_falls_back_to_a_generic_reason(guards):
    guards({"swing:breakout_h1": {"force_review": True}})
    force, reason = swing_force_review()
    # Advisory (default): the reason surfaces but the guard does not hard-block.
    assert force is False
    assert reason and "padrão fraco" in reason


def test_malformed_guard_file_blocks_nothing(guards, tmp_path):
    (tmp_path / "study_guard.json").write_text("{not json", encoding="utf-8")
    assert day_trade_rule_notes() == {}
    assert swing_force_review() == (False, None)


# --------------------------------------------------------------------------- #
# The observer loop actually honours the guard
# --------------------------------------------------------------------------- #

_ACCOUNT = "7fa92732-d890-41ba-ac47-13e4e5b3e67f"
_BASE = datetime(2026, 1, 15, 14, 30, tzinfo=timezone.utc)


def _breakout_bars() -> list[IntradayBar]:
    """A clean opening-range break, the setup the orb rule exists to catch."""
    rows = [
        (0, 10.0, 10.5, 9.8, 10.2, 1000),
        (1, 10.2, 10.6, 10.0, 10.4, 1000),
        (2, 10.4, 10.7, 10.2, 10.5, 1000),
        (3, 10.6, 11.0, 10.6, 10.9, 2000),
    ]
    return [
        IntradayBar(ts=_BASE + timedelta(minutes=m * 5), open=o, high=h, low=lo,
                    close=c, volume=v)
        for m, o, h, lo, c, v in rows
    ]


@pytest.fixture
def observer_env(monkeypatch):
    """Neutralise every gate except the study guard under test."""
    import app.services.day_trade.observer as obs

    monkeypatch.setattr(obs, "is_time_window_ok", lambda _ts: True)
    monkeypatch.setattr(obs, "concurrent_exceeded", lambda *a, **k: False)
    monkeypatch.setattr(obs, "daily_loss_exceeded", lambda *a, **k: False)
    monkeypatch.setattr(obs, "update_open_signals", lambda *a, **k: 0)
    monkeypatch.setattr(obs, "compute_gates", lambda *a, **k: {})
    monkeypatch.setattr(obs, "rule_is_gated", lambda *a, **k: False)
    monkeypatch.setattr(obs, "ticker_is_gated", lambda *a, **k: False)
    monkeypatch.setattr(obs, "record_forecast", lambda *a, **k: None)
    return obs


def test_a_signal_carries_no_note_when_the_study_is_fine(observer_env, monkeypatch, db_session):
    monkeypatch.setattr(observer_env, "day_trade_rule_notes", dict)
    created = observer_env.run_observer_for_bar(
        db_session, account_id=_ACCOUNT, ticker="AMD", bars=_breakout_bars()
    )
    assert [s.rule_id for s in created] == ["opening_range_break"]
    assert "study_note" not in created[0].metrics


def test_harvest_still_reads_legacy_force_review_key(guards):
    """Old study_guard.json files only had force_review; still read as evidence."""
    guards({"hv_dip:deep_dip": {"force_review": True, "reason": "legado"}})
    force, reason = hv_dip_force_review()
    # Advisory (default): the legacy key is read (reason surfaces) but the
    # verdict no longer hard-blocks — the desk decides.
    assert force is False
    assert reason == "legado"


def test_a_guarded_rule_still_fires_but_carries_the_verdict(
    observer_env, monkeypatch, db_session
):
    """Day trade is simulated end to end: blocking the rule would only cost
    samples. The weakness travels with the signal instead."""
    monkeypatch.setattr(
        observer_env, "day_trade_rule_notes",
        lambda: {"opening_range_break": "orb fraco"},
    )
    created = observer_env.run_observer_for_bar(
        db_session, account_id=_ACCOUNT, ticker="AMD", bars=_breakout_bars()
    )
    assert [s.rule_id for s in created] == ["opening_range_break"]
    assert created[0].metrics["study_note"] == "orb fraco"


def test_a_note_for_another_rule_does_not_attach(observer_env, monkeypatch, db_session):
    monkeypatch.setattr(
        observer_env, "day_trade_rule_notes", lambda: {"vwap_reclaim": "vwap fraco"}
    )
    created = observer_env.run_observer_for_bar(
        db_session, account_id=_ACCOUNT, ticker="AMD", bars=_breakout_bars()
    )
    assert created[0].rule_id == "opening_range_break"
    assert "study_note" not in created[0].metrics
