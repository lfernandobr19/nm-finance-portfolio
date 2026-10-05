"""Delete the stale duplicate "NM USD Paper" (alpaca) account.

The active paper account is the `tastytrade` one (with the real open
positions). This script removes the leftover `alpaca` duplicate and all its
children, mirroring the DELETE /accounts/{id} cascade in accounts.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal
from app.domain.models import (
    AccountMembership,
    AccountRule,
    DayTradeSignal,
    HvDipObservation,
    Invite,
    InvestmentAccount,
    Order,
    Position,
    Suggestion,
    WatchlistItem,
)

STALE_ID = "4374deba-913d-4f74-b6ba-98cce0017e43"  # NM USD Paper (alpaca)

CHILDREN = (
    Position,
    Order,
    DayTradeSignal,
    Suggestion,
    WatchlistItem,
    HvDipObservation,
    Invite,
    AccountRule,
    AccountMembership,
)


def main() -> int:
    db = SessionLocal()
    try:
        acc = db.get(InvestmentAccount, STALE_ID)
        if acc is None:
            print("STALE account not found; nothing to do")
            return 0
        if acc.broker_code != "alpaca" or acc.name != "NM USD Paper":
            print(
                "REFUSING: account does not look like the stale alpaca paper: "
                f"name={acc.name} broker={acc.broker_code}"
            )
            return 1

        print(f"Deleting account {acc.id} ({acc.name} / {acc.broker_code})")
        for model in CHILDREN:
            n = db.query(model).filter(model.account_id == STALE_ID).delete(
                synchronize_session=False
            )
            print(f"  {model.__name__}: {n}")
        db.delete(acc)
        db.commit()
        print("DONE")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
