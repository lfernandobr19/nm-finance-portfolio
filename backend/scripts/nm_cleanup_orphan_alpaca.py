"""Delete any orphaned alpaca "NM USD Paper" accounts (leftover duplicates).

After the paper account migrated to tastytrade, `ensure-nm-usd` used to
recreate an `alpaca`-brokered "NM USD Paper" duplicate. This removes any such
account that has no activity, keeping only the tastytrade paper account.
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
        dupes = (
            db.query(InvestmentAccount)
            .filter(
                InvestmentAccount.broker_code == "alpaca",
                InvestmentAccount.name == "NM USD Paper",
            )
            .all()
        )
        if not dupes:
            print("No alpaca 'NM USD Paper' accounts found.")
            return 0

        for acc in dupes:
            # Safety: only remove if it has no open positions/orders (orphaned).
            npos = db.query(Position).filter(Position.account_id == acc.id).count()
            nord = db.query(Order).filter(Order.account_id == acc.id).count()
            if npos or nord:
                print(
                    f"SKIP {acc.id}: has positions={npos} orders={nord}; not deleting."
                )
                continue
            print(f"Deleting orphaned alpaca paper account {acc.id} ...")
            for model in CHILDREN:
                db.query(model).filter(model.account_id == acc.id).delete(
                    synchronize_session=False
                )
            db.delete(acc)
        db.commit()
        print("DONE")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
