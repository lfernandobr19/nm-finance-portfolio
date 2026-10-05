"""Order POST/GET retry: 502/503 retried, 400 is not."""

from __future__ import annotations

import httpx
import pytest

from app.services.tastytrade_client import (
    AmbiguousOrderSubmit,
    TastytradeClient,
    TastytradeHttpError,
)


class _FakeSettings:
    tastytrade_sandbox = True
    tastytrade_client_id = "sb-id"
    tastytrade_client_secret = "sb-secret"
    tastytrade_refresh_token = "sb-refresh"
    tastytrade_account_number = "sb-acct"
    tastytrade_base_url = "https://api.tastyworks.com"
    tastytrade_sandbox_base_url = "https://api.cert.tastyworks.com"
    tastytrade_oauth_scopes = "read trade openid"
    tastytrade_live_client_id = ""
    tastytrade_live_client_secret = ""
    tastytrade_live_refresh_token = ""
    tastytrade_live_account_number = ""


class _SeqClient:
    """httpx.Client stand-in that pops scripted responses."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def request(self, method, url, **kwargs):
        self.calls.append((method, str(url)))
        if not self.responses:
            raise AssertionError(f"unexpected {method} {url}")
        return self.responses.pop(0)

    def close(self):
        return None


def _client(monkeypatch) -> TastytradeClient:
    monkeypatch.setattr("app.services.tastytrade_client.get_settings", lambda: _FakeSettings)
    c = TastytradeClient(live=False)
    c._access_token = "tok"  # noqa: SLF001
    c._expires_at = 1e18  # noqa: SLF001
    monkeypatch.setattr("app.services.tastytrade_client.time.sleep", lambda s: None)
    return c


def _json_resp(code: int, payload: dict) -> httpx.Response:
    return httpx.Response(code, json=payload)


def test_post_order_retries_502_then_succeeds(monkeypatch):
    seq = _SeqClient(
        [
            _json_resp(502, {"error": "bad gateway"}),
            _json_resp(502, {"error": "bad gateway"}),
            _json_resp(200, {"data": {"id": "1", "status": "Live"}}),
        ]
    )
    monkeypatch.setattr("app.services.tastytrade_client.httpx.Client", lambda **k: seq)
    client = _client(monkeypatch)
    data = client._post(  # noqa: SLF001
        "https://api.cert.tastyworks.com/accounts/sb-acct/orders",
        {"order-type": "Limit"},
    )
    assert data["data"]["id"] == "1"
    assert len(seq.calls) == 3


def test_post_order_400_does_not_retry(monkeypatch):
    seq = _SeqClient([_json_resp(400, {"error": "User is not a TastyTrade customer"})])
    monkeypatch.setattr("app.services.tastytrade_client.httpx.Client", lambda **k: seq)
    client = _client(monkeypatch)
    with pytest.raises(TastytradeHttpError) as exc:
        client._post(  # noqa: SLF001
            "https://api.cert.tastyworks.com/accounts/sb-acct/orders",
            {"order-type": "Limit"},
        )
    assert exc.value.status_code == 400
    assert len(seq.calls) == 1


def test_post_order_exhausted_502_is_ambiguous(monkeypatch):
    seq = _SeqClient(
        [
            _json_resp(502, {"error": "bad gateway"}),
            _json_resp(503, {"error": "unavailable"}),
            _json_resp(502, {"error": "bad gateway"}),
        ]
    )
    monkeypatch.setattr("app.services.tastytrade_client.httpx.Client", lambda **k: seq)
    client = _client(monkeypatch)
    with pytest.raises(AmbiguousOrderSubmit):
        client._post(  # noqa: SLF001
            "https://api.cert.tastyworks.com/accounts/sb-acct/orders",
            {"order-type": "Limit"},
        )
    assert len(seq.calls) == 3


def test_get_order_retries_502(monkeypatch):
    seq = _SeqClient(
        [
            _json_resp(502, {"error": "bad gateway"}),
            _json_resp(200, {"data": {"id": "1650607", "status": "Live"}}),
        ]
    )
    monkeypatch.setattr("app.services.tastytrade_client.httpx.Client", lambda **k: seq)
    client = _client(monkeypatch)
    data = client.get_order("1650607")
    inner = data.get("data") or data
    assert inner["id"] == "1650607"
    assert len(seq.calls) == 2


def test_cancel_already_filled_does_not_raise(monkeypatch):
    seq = _SeqClient(
        [_json_resp(400, {"error": "Order cannot be canceled because it is filled"})]
    )
    monkeypatch.setattr("app.services.tastytrade_client.httpx.Client", lambda **k: seq)
    client = _client(monkeypatch)
    data = client.cancel_order("1650607")
    assert isinstance(data, dict)


def test_limit_buy_sends_external_identifier(monkeypatch):
    captured: dict = {}

    class _Cap(_SeqClient):
        def request(self, method, url, **kwargs):
            captured["json"] = kwargs.get("json")
            captured["url"] = str(url)
            return super().request(method, url, **kwargs)

    seq = _Cap(
        [
            _json_resp(
                200,
                {
                    "data": {
                        "warnings": [],
                        "buying-power-effect": {
                            "current-buying-power": "10000",
                            "change-in-buying-power": "218.86",
                            "change-in-buying-power-effect": "Debit",
                            "impact": "218.86",
                            "effect": "Debit",
                        },
                    }
                },
            ),
            _json_resp(200, {"data": {"id": "1", "status": "Live"}}),
        ]
    )
    monkeypatch.setattr("app.services.tastytrade_client.httpx.Client", lambda **k: seq)
    client = _client(monkeypatch)
    client.submit_equity_limit_buy(
        symbol="NVDA", quantity=1, limit_price=218.86, client_order_id="cid-1"
    )
    assert captured["json"]["external-identifier"] == "cid-1"
    assert "ext-client-order-id" not in captured["json"]


def test_list_orders_hits_history_not_live(monkeypatch):
    from datetime import datetime, timezone

    seq = _SeqClient([_json_resp(200, {"data": {"items": [{"id": "1", "status": "Expired"}]}})])
    monkeypatch.setattr("app.services.tastytrade_client.httpx.Client", lambda **k: seq)
    client = _client(monkeypatch)
    items = client.list_orders(start_at=datetime(2026, 9, 16, tzinfo=timezone.utc))
    assert items[0]["id"] == "1"
    assert "/orders/live" not in seq.calls[0][1]
    assert seq.calls[0][0] == "GET"


def test_token_retries_502_then_succeeds(monkeypatch):
    seq = _SeqClient(
        [
            _json_resp(502, {"error": "bad gateway"}),
            _json_resp(200, {"access_token": "new-tok", "expires_in": 900}),
        ]
    )
    monkeypatch.setattr("app.services.tastytrade_client.httpx.Client", lambda **k: seq)
    client = _client(monkeypatch)
    client._access_token = None  # noqa: SLF001
    client._expires_at = 0  # noqa: SLF001
    assert client.access_token() == "new-tok"
    assert len(seq.calls) == 2


def test_token_400_customer_does_not_retry(monkeypatch):
    seq = _SeqClient([_json_resp(400, {"error": "User is not a TastyTrade customer"})])
    monkeypatch.setattr("app.services.tastytrade_client.httpx.Client", lambda **k: seq)
    client = _client(monkeypatch)
    client._access_token = None  # noqa: SLF001
    client._expires_at = 0  # noqa: SLF001
    with pytest.raises(RuntimeError, match="not a TastyTrade customer"):
        client.access_token()
    assert len(seq.calls) == 1


def test_persist_refresh_overrides_settings_and_clears_cache(monkeypatch):
    from app.services import tastytrade_client as tc

    monkeypatch.setattr(tc, "_write_env_refresh", lambda *a, **k: None)
    client = _client(monkeypatch)
    cleared: list[int] = []

    def fake_settings():
        return _FakeSettings()

    fake_settings.cache_clear = lambda: cleared.append(1)
    monkeypatch.setattr(tc, "get_settings", fake_settings)
    client._persist_refresh_token("rotated-refresh")  # noqa: SLF001
    assert client._refresh_token == "rotated-refresh"  # noqa: SLF001
    assert cleared == [1]


def test_http_client_is_reused(monkeypatch):
    seq = _SeqClient(
        [
            _json_resp(200, {"data": {"items": []}}),
            _json_resp(200, {"data": {"items": []}}),
        ]
    )
    constructed: list[int] = []

    def _make(**kwargs):
        constructed.append(1)
        return seq

    monkeypatch.setattr("app.services.tastytrade_client.httpx.Client", _make)
    client = _client(monkeypatch)
    client.list_live_orders()
    client.list_positions()
    assert constructed == [1]
    assert seq.calls[0][0] == "GET"
    assert seq.calls[1][1].endswith("/positions")


def test_probe_account_400_customer_returns_false(monkeypatch):
    seq = _SeqClient([_json_resp(400, {"error": "User is not a TastyTrade customer"})])
    monkeypatch.setattr("app.services.tastytrade_client.httpx.Client", lambda **k: seq)
    client = _client(monkeypatch)
    assert client.probe_account() is False
    assert len(seq.calls) == 1
    assert seq.calls[0][1].endswith("/customers/me/accounts")


def test_probe_account_lists_customers_me_accounts(monkeypatch):
    seq = _SeqClient(
        [
            _json_resp(
                200,
                {
                    "data": {
                        "items": [
                            {
                                "account": {"account-number": "sb-acct"},
                                "authority-level": "owner",
                            }
                        ]
                    }
                },
            )
        ]
    )
    monkeypatch.setattr("app.services.tastytrade_client.httpx.Client", lambda **k: seq)
    client = _client(monkeypatch)
    assert client.probe_account() is True
    assert client._authority_level == "owner"  # noqa: SLF001
    assert seq.calls[0][1].endswith("/customers/me/accounts")


def test_dry_run_insufficient_bp_does_not_post(monkeypatch):
    from app.services.tastytrade_client import DryRunRejected

    seq = _SeqClient(
        [
            _json_resp(
                200,
                {
                    "data": {
                        "warnings": [],
                        "buying-power-effect": {
                            "current-buying-power": "10",
                            "change-in-buying-power": "218.86",
                            "change-in-buying-power-effect": "Debit",
                            "impact": "218.86",
                            "effect": "Debit",
                        },
                    }
                },
            )
        ]
    )
    monkeypatch.setattr("app.services.tastytrade_client.httpx.Client", lambda **k: seq)
    client = _client(monkeypatch)
    with pytest.raises(DryRunRejected, match="buying-power"):
        client.submit_equity_limit_buy(symbol="NVDA", quantity=1, limit_price=218.86)
    assert all("/dry-run" in url for _m, url in seq.calls)
    assert not any(m == "POST" and "/dry-run" not in url for m, url in seq.calls)


def test_dry_run_502_proceeds_to_post(monkeypatch):
    seq = _SeqClient(
        [
            _json_resp(502, {"error": "bad gateway"}),
            _json_resp(502, {"error": "bad gateway"}),
            _json_resp(502, {"error": "bad gateway"}),
            _json_resp(200, {"data": {"id": "1", "status": "Live"}}),
        ]
    )
    monkeypatch.setattr("app.services.tastytrade_client.httpx.Client", lambda **k: seq)
    client = _client(monkeypatch)
    data = client.submit_equity_limit_buy(symbol="NVDA", quantity=1, limit_price=218.86)
    inner = data.get("data") or data
    assert inner["id"] == "1"


def test_replace_equity_limit_puts_same_id(monkeypatch):
    seq = _SeqClient([_json_resp(200, {"data": {"id": "1650607", "status": "Live"}})])
    monkeypatch.setattr("app.services.tastytrade_client.httpx.Client", lambda **k: seq)
    client = _client(monkeypatch)
    client.replace_equity_limit(
        "1650607", symbol="NVDA", quantity=1, limit_price=210.0
    )
    assert seq.calls[0][0] == "PUT"
    assert seq.calls[0][1].endswith("/orders/1650607")


def test_oauth_login_script_uses_sandbox_auth():
    from pathlib import Path

    from app.services.tastytrade_client import SANDBOX_AUTH_URL

    src = (Path(__file__).resolve().parents[1] / "scripts" / "tastytrade_oauth_login.py").read_text(
        encoding="utf-8"
    )
    assert "cert-my.staging-tasty.works" in src
    assert SANDBOX_AUTH_URL.endswith("auth.html")


def _dry_run_ok() -> httpx.Response:
    return _json_resp(
        200,
        {
            "data": {
                "warnings": [],
                "buying-power-effect": {
                    "current-buying-power": "10000",
                    "change-in-buying-power": "218.86",
                    "change-in-buying-power-effect": "Debit",
                    "impact": "218.86",
                    "effect": "Debit",
                },
            }
        },
    )


def test_ambiguous_post_finds_order_does_not_repost(monkeypatch):
    seq = _SeqClient(
        [
            _dry_run_ok(),
            _json_resp(502, {"error": "bad gateway"}),
            _json_resp(502, {"error": "bad gateway"}),
            _json_resp(502, {"error": "bad gateway"}),
            _json_resp(
                200,
                {
                    "data": {
                        "items": [
                            {
                                "id": "1650607",
                                "status": "Live",
                                "external-identifier": "cid-1",
                            }
                        ]
                    }
                },
            ),
        ]
    )
    monkeypatch.setattr("app.services.tastytrade_client.httpx.Client", lambda **k: seq)
    client = _client(monkeypatch)
    data = client.submit_equity_limit_buy(
        symbol="NVDA", quantity=1, limit_price=218.86, client_order_id="cid-1"
    )
    inner = data.get("data") or data
    assert inner["id"] == "1650607"
    posts = [c for c in seq.calls if c[0] == "POST" and "/dry-run" not in c[1]]
    assert len(posts) == 3


def test_ambiguous_post_empty_lookup_posts_once_more(monkeypatch):
    seq = _SeqClient(
        [
            _dry_run_ok(),
            _json_resp(502, {"error": "bad gateway"}),
            _json_resp(502, {"error": "bad gateway"}),
            _json_resp(502, {"error": "bad gateway"}),
            _json_resp(200, {"data": {"items": []}}),
            _json_resp(200, {"data": {"items": []}}),
            _json_resp(200, {"data": {"id": "99", "status": "Live"}}),
        ]
    )
    monkeypatch.setattr("app.services.tastytrade_client.httpx.Client", lambda **k: seq)
    client = _client(monkeypatch)
    data = client.submit_equity_limit_buy(
        symbol="NVDA", quantity=1, limit_price=218.86, client_order_id="cid-1"
    )
    inner = data.get("data") or data
    assert inner["id"] == "99"
    posts = [c for c in seq.calls if c[0] == "POST" and "/dry-run" not in c[1]]
    assert len(posts) == 4


def test_get_401_refreshes_token_once(monkeypatch):
    seq = _SeqClient(
        [
            _json_resp(401, {"error": "Unauthorized"}),
            _json_resp(200, {"access_token": "new-tok", "expires_in": 900}),
            _json_resp(200, {"data": {"id": "1650607", "status": "Live"}}),
        ]
    )
    monkeypatch.setattr("app.services.tastytrade_client.httpx.Client", lambda **k: seq)
    client = _client(monkeypatch)
    data = client.get_order("1650607")
    inner = data.get("data") or data
    assert inner["id"] == "1650607"
    assert seq.calls[0][0] == "GET"
    assert seq.calls[1][0] == "POST"
    assert "/oauth/token" in seq.calls[1][1]
    assert seq.calls[2][0] == "GET"


def test_read_only_authority_rejects_post(monkeypatch):
    from app.services.tastytrade_client import TastytradeHttpError

    seq = _SeqClient([])
    monkeypatch.setattr("app.services.tastytrade_client.httpx.Client", lambda **k: seq)
    client = _client(monkeypatch)
    client._authority_level = "read-only"  # noqa: SLF001
    with pytest.raises(TastytradeHttpError) as exc:
        client.submit_equity_limit_buy(symbol="NVDA", quantity=1, limit_price=218.86)
    assert exc.value.status_code == 403
    assert seq.calls == []


def test_http_transport_retries_passed(monkeypatch):
    captured: dict = {}

    def _make(**kwargs):
        captured["transport"] = kwargs.get("transport")
        return _SeqClient([_json_resp(200, {"data": {"items": []}})])

    monkeypatch.setattr("app.services.tastytrade_client.httpx.Client", _make)
    client = _client(monkeypatch)
    client.list_live_orders()
    assert isinstance(captured["transport"], httpx.HTTPTransport)
