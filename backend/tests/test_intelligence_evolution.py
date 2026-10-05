"""Read-only evolution endpoints + cheap pulse patch."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.main import app


def _auth_user():
    return SimpleNamespace(id="u1", email="t@example.com", is_active=True)


def _client():
    app.dependency_overrides[get_current_user] = _auth_user
    return TestClient(app)


def test_evolution_routes_registered():
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/v1/intelligence/evolution" in paths
    assert "/api/v1/intelligence/memory" in paths
    assert "/api/v1/intelligence/ledger" in paths
    assert "/api/v1/intelligence/decisions" in paths
    assert "/api/v1/intelligence/calibration" in paths


def test_evolution_endpoints_200(db_session, tmp_path, monkeypatch):
    from app.services.learn import memory as mem

    monkeypatch.setattr(mem, "_path", lambda: tmp_path / "memory.db")
    mem.write(
        kind="pattern",
        scope="hv_dip:deep_dip",
        text="dip fraco",
        provenance="test",
        refuted=True,
        n_support=30,
        path=tmp_path / "memory.db",
    )
    client = _client()
    try:
        evo = client.get("/api/v1/intelligence/evolution?limit=10")
        mem_r = client.get("/api/v1/intelligence/memory?limit=10")
        led = client.get("/api/v1/intelligence/ledger?limit=10")
        dec = client.get("/api/v1/intelligence/decisions?limit=10")
        cal = client.get("/api/v1/intelligence/calibration")
    finally:
        app.dependency_overrides.clear()
    assert evo.status_code == 200
    assert "items" in evo.json()
    assert mem_r.status_code == 200
    assert any(i["refuted"] for i in mem_r.json()["items"])
    assert led.status_code == 200
    assert dec.status_code == 200
    assert cal.status_code == 200
    assert "calibrators" in cal.json()


def _seed_denies(db, *, reason: str, n: int = 12):
    from datetime import datetime, timezone
    from uuid import uuid4

    from app.domain.models import DeskDecision, StrategyKind

    now = datetime.now(timezone.utc)
    for i in range(n):
        db.add(
            DeskDecision(
                id=str(uuid4()),
                account_id="acc-test",
                strategy_kind=StrategyKind.mega_rotation,
                ticker=f"T{i}",
                verdict="deny",
                reason=reason,
                notional=25.0,
                price=10.0,
                cash_before=100.0,
                enforce=True,
                created_at=now,
                payload={},
            )
        )
    db.commit()


def test_unaffordable_denies_are_not_a_deny_storm(db_session, monkeypatch):
    from app.config import Settings
    from app.services.learn.evolution import live_promotion_checklist

    monkeypatch.setattr(
        "app.services.learn.evolution.get_settings",
        lambda: Settings(desk_gate_enforce=True),
    )
    _seed_denies(db_session, reason="unaffordable", n=12)
    items = {i["id"]: i for i in live_promotion_checklist(db_session)["items"]}
    assert items["gate_enforce"]["ok"] is True
    assert "deny_tese 7d=0" in items["gate_enforce"]["detail"]


def test_miscalibrated_denies_are_a_deny_storm(db_session, monkeypatch):
    from app.config import Settings
    from app.services.learn.evolution import live_promotion_checklist

    monkeypatch.setattr(
        "app.services.learn.evolution.get_settings",
        lambda: Settings(desk_gate_enforce=True),
    )
    _seed_denies(db_session, reason="miscalibrated", n=12)
    items = {i["id"]: i for i in live_promotion_checklist(db_session)["items"]}
    assert items["gate_enforce"]["ok"] is False
    assert "deny_tese 7d=12" in items["gate_enforce"]["detail"]


def test_cheap_status_patch_has_live_checklist(db_session):
    from app.services.learn.evolution import cheap_status_patch

    patch = cheap_status_patch(db_session)
    assert "live_promotion" in patch
    assert "items" in patch["live_promotion"]
    ids = {i["id"] for i in patch["live_promotion"]["items"]}
    assert {"paper_n", "brier", "buckets", "fdr_guards", "gate_enforce", "kill_switch", "daily_cap"} <= ids
    assert "memory" in patch
    assert "desk_slices" in patch or patch["desk_slices"] is None
    assert patch["dt_gates"]["reason"] == "soma R"
    assert "rules" in patch["dt_gates"]
