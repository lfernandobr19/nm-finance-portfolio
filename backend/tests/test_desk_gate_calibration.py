"""Calibration deny: a mis-scored source loses the right to auto-execute."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.config import Settings
from app.domain.models import AccountCurrency, ExecutionMode, InvestmentAccount, StrategyKind
from app.services.desk_gate import DeskIntent, evaluate_gate


def _account() -> InvestmentAccount:
    return InvestmentAccount(
        id="acc1",
        name="NM Paper",
        owner_user_id="u1",
        broker_code="tastytrade",
        currency=AccountCurrency.USD,
        execution_mode=ExecutionMode.paper,
        cash_usd=100.0,
        hv_dip_equity_usd=100.0,
        hv_dip_cash_floor_pct=20.0,
        max_ticket_brl=100.0,
        automation_paused=False,
    )


def _intent(account, **kw) -> DeskIntent:
    defaults = dict(
        account=account,
        kind=StrategyKind.hv_dip,
        ticker="SOFI",
        notional=20.0,
        price=10.0,
        score=80.0,
    )
    defaults.update(kw)
    return DeskIntent(**defaults)


def _settings(**kw) -> Settings:
    base = dict(
        desk_gate_enabled=True,
        desk_gate_enforce=True,
        desk_gate_queue_enabled=False,
        desk_gate_usd_budgets="hv_dip=0.4,index_core=0.4,mega_rotation=0",
        desk_gate_window_seconds=300,
        desk_gate_protect_enabled=False,
        desk_gate_regime_lock=False,
        desk_gate_calibration_enabled=True,
        desk_gate_calibration_max_brier=0.30,
        desk_gate_calibration_min_resolved=30,
        desk_gate_calibration_max_bucket_gap=0.25,
        desk_gate_calibration_min_bucket_n=8,
        # The judgment layer lifts numeric priors with courage; disable it here
        # to test the calibration lock in isolation (legacy hard mode).
        desk_judgment_enabled=False,
    )
    base.update(kw)
    return Settings(**base)


class _Row:
    def __init__(self, brier, p_pred=None, outcome=None):
        self.brier = brier
        self.p_pred = p_pred
        self.outcome = outcome


def test_miscalibrated_source_is_denied(monkeypatch):
    account = _account()
    db = MagicMock()
    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query
    query.all.return_value = [_Row(0.45) for _ in range(40)]
    monkeypatch.setattr("app.services.desk_gate.get_settings", lambda: _settings())
    monkeypatch.setattr("app.services.desk_gate.account_equity_usd", lambda *a, **k: 100.0)
    monkeypatch.setattr("app.services.desk_gate.deployed_kind_usd", lambda *a, **k: 0.0)
    verdict = evaluate_gate(db, _intent(account))
    assert verdict.allow is False
    assert verdict.reason == "miscalibrated"


def test_well_calibrated_source_passes(monkeypatch):
    account = _account()
    db = MagicMock()
    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query
    query.all.return_value = [_Row(0.12) for _ in range(40)]
    monkeypatch.setattr("app.services.desk_gate.get_settings", lambda: _settings())
    monkeypatch.setattr("app.services.desk_gate.account_equity_usd", lambda *a, **k: 100.0)
    monkeypatch.setattr("app.services.desk_gate.deployed_kind_usd", lambda *a, **k: 0.0)
    verdict = evaluate_gate(db, _intent(account))
    assert verdict.allow is True
    assert verdict.reason == "ok"


def test_too_few_resolved_does_not_block(monkeypatch):
    account = _account()
    db = MagicMock()
    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query
    query.all.return_value = [_Row(0.45) for _ in range(5)]
    monkeypatch.setattr("app.services.desk_gate.get_settings", lambda: _settings())
    monkeypatch.setattr("app.services.desk_gate.account_equity_usd", lambda *a, **k: 100.0)
    monkeypatch.setattr("app.services.desk_gate.deployed_kind_usd", lambda *a, **k: 0.0)
    verdict = evaluate_gate(db, _intent(account))
    assert verdict.allow is True


def test_wide_reliability_bucket_denies_even_when_mean_brier_is_fine(monkeypatch):
    """Average Brier can hide one badly mis-scaled confidence bucket.

    15 forecasts at p=0.10 that all miss (Brier 0.01) plus 25 at p=0.80 with
    only 8 hits (freq=0.32, gap=0.48). Mean Brier stays under 0.30; the high
    bucket does not.
    """
    rows = [_Row(0.01, p_pred=0.10, outcome=False) for _ in range(15)]
    rows += [_Row(0.04, p_pred=0.80, outcome=True) for _ in range(8)]
    rows += [_Row((0.80) ** 2, p_pred=0.80, outcome=False) for _ in range(17)]
    account = _account()
    db = MagicMock()
    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query
    query.all.return_value = rows
    monkeypatch.setattr("app.services.desk_gate.get_settings", lambda: _settings())
    monkeypatch.setattr("app.services.desk_gate.account_equity_usd", lambda *a, **k: 100.0)
    monkeypatch.setattr("app.services.desk_gate.deployed_kind_usd", lambda *a, **k: 0.0)
    verdict = evaluate_gate(db, _intent(account))
    assert verdict.allow is False
    assert verdict.reason == "miscalibrated"


def test_sparse_bucket_does_not_deny(monkeypatch):
    """A two-point 0.95 bucket is noise, not a reliability curve."""
    rows = [_Row(0.25, p_pred=0.50, outcome=True) for _ in range(15)]
    rows += [_Row(0.25, p_pred=0.50, outcome=False) for _ in range(15)]
    rows += [_Row(0.0025, p_pred=0.95, outcome=True) for _ in range(2)]
    account = _account()
    db = MagicMock()
    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query
    query.all.return_value = rows
    monkeypatch.setattr("app.services.desk_gate.get_settings", lambda: _settings())
    monkeypatch.setattr("app.services.desk_gate.account_equity_usd", lambda *a, **k: 100.0)
    monkeypatch.setattr("app.services.desk_gate.deployed_kind_usd", lambda *a, **k: 0.0)
    verdict = evaluate_gate(db, _intent(account))
    assert verdict.allow is True


def test_mega_rotation_below_floor_does_not_deny(monkeypatch):
    account = _account()
    db = MagicMock()
    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query
    query.all.return_value = [_Row(0.45) for _ in range(5)]
    monkeypatch.setattr(
        "app.services.desk_gate.get_settings",
        lambda: _settings(desk_gate_usd_budgets="mega_rotation=1"),
    )
    monkeypatch.setattr("app.services.desk_gate.account_equity_usd", lambda *a, **k: 100.0)
    monkeypatch.setattr("app.services.desk_gate.deployed_kind_usd", lambda *a, **k: 0.0)
    verdict = evaluate_gate(
        db, _intent(account, kind=StrategyKind.mega_rotation, ticker="NVDA")
    )
    assert verdict.allow is True
    assert verdict.reason != "miscalibrated"
