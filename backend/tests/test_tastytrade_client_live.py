"""TastytradeClient live/sandbox environment selection."""

from __future__ import annotations

from app.services.tastytrade_client import TastytradeClient


def test_live_client_selects_live_credentials_and_base(monkeypatch):
    monkeypatch.setattr("app.services.tastytrade_client.get_settings", _fake_settings)

    client = TastytradeClient(live=True)
    assert client.live is True
    assert client._client_id == "live-id"  # noqa: SLF001
    assert client._client_secret == "live-secret"  # noqa: SLF001
    assert client._refresh_token == "live-refresh"  # noqa: SLF001
    assert client.account_number == "live-acct"
    assert client.base_url == "https://api.tastyworks.com"
    assert client.configured() is True


def test_sandbox_client_selects_sandbox_credentials_and_base(monkeypatch):
    monkeypatch.setattr("app.services.tastytrade_client.get_settings", _fake_settings)

    client = TastytradeClient(live=False)
    assert client.live is False
    assert client._client_id == "sb-id"  # noqa: SLF001
    assert client._client_secret == "sb-secret"  # noqa: SLF001
    assert client._refresh_token == "sb-refresh"  # noqa: SLF001
    assert client.account_number == "sb-acct"
    assert client.base_url == "https://api.cert.tastyworks.com"
    assert client.configured() is True


class _fake_settings:
    tastytrade_sandbox = True
    tastytrade_client_id = "sb-id"
    tastytrade_client_secret = "sb-secret"
    tastytrade_refresh_token = "sb-refresh"
    tastytrade_account_number = "sb-acct"
    tastytrade_base_url = "https://api.tastyworks.com"
    tastytrade_sandbox_base_url = "https://api.cert.tastyworks.com"
    tastytrade_oauth_scopes = "read trade openid"
    tastytrade_live_client_id = "live-id"
    tastytrade_live_client_secret = "live-secret"
    tastytrade_live_refresh_token = "live-refresh"
    tastytrade_live_account_number = "live-acct"
