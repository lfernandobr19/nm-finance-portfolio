"""Reset the USD paper account to US$ 100 and wipe its trading history.

Prep for the "Quick Target" swing strategy: zero everything active and delete
the history (positions, orders, suggestions, hv_dip observations) for the
tastytrade PAPER USD account, then restore `cash_usd = 100.0`.

Leaves the user-curated `watchlist_items` untouched (separate feature), and
does NOT touch the live accounts.

Run on Ravenna:
    .venv/bin/python scripts/nm_reset_paper_quick.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal
from app.domain.models import (
    AccountCurrency,
    ExecutionMode,
    HvDipObservation,
    InvestmentAccount,
    Order,
    Position,
    Suggestion,
)

TARGET_CASH = 100.0
TARGET_EQUITY = 100.0

# Deletion order matters: Position -> Order -> Suggestion (FK dependencies).
CHILDREN = (Position, Order, Suggestion, HvDipObservation)


def _find_target(db):
    acc = (
        db.query(InvestmentAccount)
        .filter(
            InvestmentAccount.broker_code == "tastytrade",
            InvestmentAccount.execution_mode == ExecutionMode.paper,
            InvestmentAccount.currency == AccountCurrency.USD,
        )
        .one_or_none()
    )
    if acc is None:
        raise SystemExit("USD paper (tastytrade) account not found; aborting.")
    return acc


def reset_paper(*, dry_run: bool = False) -> dict:
    db = SessionLocal()
    stats = {"account": "", "deleted": {}, "cash_before": 0.0}
    try:
        acc = _find_target(db)
        stats["account"] = acc.id
        stats["cash_before"] = float(acc.cash_usd or 0.0)

        print(
            f"Target: {acc.name} id={acc.id} broker={acc.broker_code} "
            f"mode={acc.execution_mode} cash={stats['cash_before']}"
        )

        for model in CHILDREN:
            n = (
                db.query(model)
                .filter(model.account_id == acc.id)
                .delete(synchronize_session=False)
            )
            stats["deleted"][model.__name__] = n
            print(f"  delete {model.__name__}: {n}")

        acc.cash_usd = TARGET_CASH
        acc.hv_dip_equity_usd = TARGET_EQUITY
        print(f"  set cash_usd={TARGET_CASH} hv_dip_equity_usd={TARGET_EQUITY}")

        if dry_run:
            db.rollback()
            print("DRY RUN — no changes committed")
        else:
            db.commit()
            print("Committed.")
    except SystemExit:
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset USD paper account to $100")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    args = parser.parse_args()
    stats = reset_paper(dry_run=args.dry_run)
    print(
        f"Done: account={stats['account'][:8]} cash_before={stats['cash_before']} "
        f"deleted={stats['deleted']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
