"""Re-link the NM USD Paper account to the Tastytrade sandbox (real paper fills).

The paper account was stuck on broker_code="alpaca" (local simulator). This flips
it to broker_code="tastytrade" while keeping execution_mode=paper, so
get_broker_adapter() routes it to TastytradeBrokerAdapter(live=False) → sandbox.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.db import SessionLocal
from app.domain.models import ExecutionMode, InvestmentAccount
from app.services.tastytrade_client import TastytradeClient


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Apply (default dry-run)")
    args = parser.parse_args()

    get_settings.cache_clear()
    settings = get_settings()
    db = SessionLocal()
    try:
        paper = (
            db.query(InvestmentAccount)
            .filter(InvestmentAccount.broker_code == "alpaca")
            .first()
        )
        if not paper:
            print("Nenhuma conta paper (alpaca) encontrada.")
            return 1

        sandbox = TastytradeClient(live=False)
        print(f"Conta paper encontrada: {paper.name} (broker={paper.broker_code}, mode={paper.execution_mode})")
        print(f"Sandbox Tastytrade configurado: {sandbox.configured()} | account={sandbox.account_number}")

        if paper.broker_code == "tastytrade":
            print("Já está religada a tastytrade.")
            return 0

        print(f"Mudando broker_code: {paper.broker_code} -> tastytrade (mode permanece {paper.execution_mode})")
        if not args.execute:
            print("Dry-run. Re-execute com --execute para aplicar.")
            return 0

        paper.broker_code = "tastytrade"
        # keep paper execution_mode (sandbox)
        paper.execution_mode = ExecutionMode.paper
        db.commit()
        db.refresh(paper)
        print(f"OK — {paper.name} religada a broker={paper.broker_code}, mode={paper.execution_mode}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
