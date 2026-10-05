"""Phase 3 debug: apply studies → skipped n<30, suppress when P(target) weak."""

from __future__ import annotations

import json

from app.services.studies.apply import (
    DEFAULT_FLOOR,
    evaluate,
    hv_dip_force_review,
    write_guards,
)
from app.services.studies.models import StudyResult


def _universe_result(
    n: int,
    p_recover: float,
    *,
    p_higher: float = 0.3,
    p_stop_first: float = 0.7,
) -> StudyResult:
    return StudyResult(
        query_id="deep_dip",
        label="dip",
        channel="hv_dip",
        fingerprint="deep_dip",
        ticker="UNIVERSE",
        n=n,
        p_higher=p_higher,
        p_stop_first=p_stop_first,
        p_recover=p_recover,
    )


def test_skipped_below_floor():
    out = evaluate([_universe_result(n=10, p_recover=0.3)])
    assert out["guards"] == {}
    assert out["decisions"][0]["action"] == "skipped"


def test_force_review_when_weak():
    out = evaluate([_universe_result(n=DEFAULT_FLOOR + 5, p_recover=0.3)])
    assert out["guards"]["hv_dip:deep_dip"]["force_review"] is True
    assert out["guards"]["hv_dip:deep_dip"]["suppress"] is True
    assert out["decisions"][0]["action"] == "suppress"
    assert "desk decide" in out["decisions"][0]["reason"]


def test_hold_when_strong():
    out = evaluate([_universe_result(n=DEFAULT_FLOOR + 5, p_recover=0.7)])
    assert out["guards"] == {}
    assert out["decisions"][0]["action"] == "hold"


def test_hv_dip_force_review_reads_guard(monkeypatch, tmp_path):
    guard_file = tmp_path / "guard.json"
    monkeypatch.setattr("app.services.studies.apply.GUARD_PATH", guard_file)
    write_guards(
        {"hv_dip:deep_dip": {"force_review": True, "p_recover": 0.3, "n": 35, "reason": "fraca"}}
    )
    # Advisory (default): the guard is read and its reason surfaces, but it does
    # not hard-block — the desk decides from evidence.
    force, reason = hv_dip_force_review()
    assert force is False
    assert "fraca" in (reason or "")

    # Hard mode restores the suppress behaviour.
    monkeypatch.setattr("app.services.studies.apply._studies_advisory", lambda: False)
    force, reason = hv_dip_force_review()
    assert force is True
    assert "fraca" in (reason or "")

    write_guards({})
    force, reason = hv_dip_force_review()
    assert force is False


def test_write_guards_roundtrip(tmp_path, monkeypatch):
    path = tmp_path / "g.json"
    monkeypatch.setattr("app.services.studies.apply.GUARD_PATH", path)
    write_guards({"k": {"force_review": True}})
    assert json.loads(path.read_text(encoding="utf-8")) == {"k": {"force_review": True}}
