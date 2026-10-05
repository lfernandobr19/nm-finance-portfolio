"""Intelligence pulse + ARQ registration. Code default keeps auto-buy off."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.config import Settings, get_settings
from app.services.intelligence import run_intelligence_pulse, write_intelligence_status
from app.workers.arq_settings import WorkerSettings
from app.workers.jobs import job_intelligence


def test_hv_dip_auto_buy_code_default_is_off():
    assert Settings.model_fields["hv_dip_auto_buy_enabled"].default is False


def test_job_intelligence_registered():
    assert job_intelligence in WorkerSettings.functions


class _QueryStub:
    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def count(self):
        return 0

    def all(self):
        return []


def test_pulse_writes_status(tmp_path, monkeypatch):
    from app.services import intelligence as intel

    monkeypatch.setattr(intel, "STATUS_PATH", tmp_path / "intelligence.json")
    db = MagicMock()
    db.query.return_value = _QueryStub()
    monkeypatch.setattr(
        "app.services.llm_calibrate.calibrate_news_outcomes",
        lambda db: {"n_labeled": 0, "hits": 0, "prompt_version": "classify_v1"},
    )
    monkeypatch.setattr("app.services.trade_review.review_closed_positions", lambda db, limit=10: 0)
    monkeypatch.setattr(
        "app.services.hv_dip.learning.run_learning",
        lambda db: {"status": "no_data", "n_trades": 0},
    )
    monkeypatch.setattr(
        "app.services.desk_learn.run_budget_learning",
        lambda db: {"status": "no_data", "n_trades": 0},
    )
    monkeypatch.setattr(
        "app.services.day_trade.learning.run_learning",
        lambda db: {"status": "no_data", "rules": {}},
    )
    monkeypatch.setattr(intel, "_run_studies_snapshot", lambda db: None)
    payload = run_intelligence_pulse(db)
    assert payload["learn"]["hv_dip"]["status"] == "no_data"
    assert payload["hv_dip_auto_buy_enabled"] is get_settings().hv_dip_auto_buy_enabled
    assert (tmp_path / "intelligence.json").exists()
    write_intelligence_status(payload)
    assert payload["reviews_n"] == 0
    assert payload["available"] is True
    assert payload["recent_reviews"] == []
    assert payload.get("swing_h1") is None


def test_assertiveness_includes_mega_rotation_and_judgment(db_session):
    from datetime import datetime, timezone

    from app.services.intelligence import _assertiveness
    from app.services.learn.ledger import record_forecast, resolve_forecast

    now = datetime.now(timezone.utc)
    mega = record_forecast(
        db_session, source="mega_rotation", kind="entry", ticker="NVDA", p_pred=0.7, now=now
    )
    judged = record_forecast(
        db_session, source="judgment", kind="courage", ticker="NVDA", p_pred=0.6, now=now
    )
    resolve_forecast(db_session, mega, outcome=True, now=now)
    resolve_forecast(db_session, judged, outcome=False, now=now)
    db_session.flush()
    data = _assertiveness(db_session)
    assert "mega_rotation" in data["by_source"]
    assert "judgment" in data["by_source"]
    assert data["by_source"]["mega_rotation"]["resolved"] >= 1
    assert "mega_rotation" in data["curves"]
    assert "judgment" in data["curves"]


def test_patch_swing_h1_does_not_mark_available(tmp_path, monkeypatch):
    from app.services import intelligence as intel

    monkeypatch.setattr(intel, "STATUS_PATH", tmp_path / "intelligence.json")
    intel.patch_intelligence_status(
        {"swing_h1": {"h1_ok": 3, "h1_skip": 1, "h1_fail": 2, "ts": "t"}}
    )
    data = intel.read_intelligence_status()
    assert data["available"] is False
    assert data["swing_h1"]["h1_ok"] == 3
    assert data["swing_h1"]["h1_fail"] == 2


def test_pulse_preserves_swing_h1(tmp_path, monkeypatch):
    from app.services import intelligence as intel

    monkeypatch.setattr(intel, "STATUS_PATH", tmp_path / "intelligence.json")
    intel.patch_intelligence_status(
        {"swing_h1": {"h1_ok": 1, "h1_skip": 0, "h1_fail": 4}}
    )
    db = MagicMock()
    db.query.return_value = _QueryStub()
    monkeypatch.setattr(
        "app.services.llm_calibrate.calibrate_news_outcomes",
        lambda db: {"n_labeled": 0, "hits": 0, "prompt_version": "classify_v1"},
    )
    monkeypatch.setattr("app.services.trade_review.review_closed_positions", lambda db, limit=10: 0)
    monkeypatch.setattr(
        "app.services.hv_dip.learning.run_learning",
        lambda db: {"status": "no_data", "n_trades": 0},
    )
    monkeypatch.setattr(
        "app.services.desk_learn.run_budget_learning",
        lambda db: {"status": "no_data", "n_trades": 0},
    )
    monkeypatch.setattr(
        "app.services.day_trade.learning.run_learning",
        lambda db: {"status": "no_data", "rules": {}},
    )
    monkeypatch.setattr(intel, "_run_studies_snapshot", lambda db: None)
    payload = run_intelligence_pulse(db)
    assert payload["available"] is True
    assert payload["swing_h1"]["h1_fail"] == 4
