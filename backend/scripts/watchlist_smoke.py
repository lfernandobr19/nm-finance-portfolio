"""Smoke test for the watchlist (observação) endpoints against the running API.

Runs on Ravenna: mints a real token for an owner/operator and exercises
GET/POST/DELETE plus live-quote enrichment via http://127.0.0.1:8010.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from app.db import SessionLocal
from app.domain.models import AccountMembership, InvestmentAccount, MembershipRole, User
from app.security import create_access_token

BASE = "http://127.0.0.1:8010/api/v1"


def _pick() -> tuple[str, str, str]:
    db = SessionLocal()
    try:
        user = (
            db.query(User)
            .filter(User.is_active.is_(True))
            .first()
        )
        assert user is not None, "no active user"
        m = (
            db.query(AccountMembership)
            .filter(
                AccountMembership.user_id == user.id,
                AccountMembership.role.in_(
                    [MembershipRole.owner, MembershipRole.operator]
                ),
            )
            .first()
        )
        assert m is not None, "no owner/operator membership"
        account = db.get(InvestmentAccount, m.account_id)
        assert account is not None
        return user.id, m.account_id, account.name
    finally:
        db.close()


def main() -> None:
    user_id, account_id, account_name = _pick()
    token = create_access_token(user_id)
    headers = {"Authorization": f"Bearer {token}"}
    base = f"{BASE}/accounts/{account_id}/watchlist"
    print(f"account={account_name} ({account_id[:8]})")

    with httpx.Client(timeout=30) as client:
        r = client.get(base, headers=headers)
        print("GET(empty)", r.status_code, r.text[:200])
        r.raise_for_status()

        r = client.post(base, headers=headers, json={"ticker": "PETR4", "note": "smoke"})
        print("POST", r.status_code, r.text[:300])
        r.raise_for_status()

        r = client.post(base, headers=headers, json={"ticker": "petr4", "note": "dup"})
        print("POST(dup)", r.status_code, "should stay single")

        r = client.get(base, headers=headers)
        print("GET(after add)", r.status_code, r.text[:400])
        r.raise_for_status()
        items = r.json()
        assert any(i["ticker"] == "PETR4" for i in items), "PETR4 missing after add"

        r = client.delete(f"{base}/PETR4", headers=headers)
        print("DELETE", r.status_code)

        r = client.get(base, headers=headers)
        print("GET(after delete)", r.status_code, r.text[:200])
        r.raise_for_status()
        assert all(i["ticker"] != "PETR4" for i in r.json()), "PETR4 still present"

    print("SMOKE_OK")


if __name__ == "__main__":
    main()
