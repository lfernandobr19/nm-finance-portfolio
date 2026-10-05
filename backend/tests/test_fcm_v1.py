"""FCM v1 transport helpers (no network / no DB)."""

from __future__ import annotations

from app.config import get_settings
from app.services.notify import _fcm_error_code, _fcm_v1_configured

settings = get_settings()


def test_fcm_error_code_parses_unregistered():
    body = (
        '{"error":{"code":404,"message":"Requested entity was not found.",'
        '"status":"NOT_FOUND","details":['
        '{"@type":"type.googleapis.com/google.firebase.fcm.v1.FcmError",'
        '"errorCode":"UNREGISTERED"}]}}'
    )
    assert _fcm_error_code(body) == "UNREGISTERED"


def test_fcm_error_code_returns_none_for_garbage():
    assert _fcm_error_code("not json") is None
    assert _fcm_error_code('{"error":{"details":[]}}') is None


def test_fcm_v1_not_configured_by_default(monkeypatch):
    monkeypatch.setattr(settings, "fcm_project_id", "")
    monkeypatch.setattr(settings, "fcm_service_account_json", "")
    assert _fcm_v1_configured() is False


def test_fcm_v1_configured_when_both_set(monkeypatch):
    monkeypatch.setattr(settings, "fcm_project_id", "fiidesk-12345")
    monkeypatch.setattr(settings, "fcm_service_account_json", '{"type":"service_account"}')
    assert _fcm_v1_configured() is True
