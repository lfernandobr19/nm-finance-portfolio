"""Create (idempotent) the NM USD Live Tastytrade account.

Creates a separate InvestmentAccount routed to Tastytrade production, mirrors its
cash balance from the broker, seeds the observation watchlist (LCID/RIOT/AFRM/UPST),
and wires up membership + rules. Safe to re-run.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow `python scripts/nm_create_live_tastytrade.py` from backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db import SessionLocal
from app.domain.models import (
    AccountCurrency,
    AccountMembership,
    AccountRule,
    ExecutionMode,
    InvestmentAccount,
    MembershipRole,
    WatchlistItem,
)
from app.services.tastytrade_client import TastytradeClient

WATCH_TICKERS = ["LCID", "RIOT", "AFRM", "UPST"]


def _find_owner_id(db) -> str | None:
    """Reuse the owner of the paper USD account; fall back to the first user."""
    paper = (
        db.query(InvestmentAccount)
        .filter(InvestmentAccount.broker_code == "alpaca")
        .first()
    )
    if paper and paper.owner_user_id:
        return paper.owner_user_id
    from app.domain.models import User

    first_user = db.query(User).order_by(User.created_at.asc()).first()
    return first_user.id if first_user else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Apply changes (default is dry-run)")
    args = parser.parse_args()

    get_settings.cache_clear()
    settings = get_settings()
    db = SessionLocal()

    try:
        existing = (
            db.query(InvestmentAccount)
            .filter(InvestmentAccount.broker_code == "tastytrade")
            .first()
        )
        if existing:
            print(f"Conta live já existe: {existing.name} ({existing.id})")
            account = existing
        else:
            owner_id = _find_owner_id(db)
            if not owner_id:
                print("Nenhum usuário encontrado para ser dono da conta. Abortando.")
                return 1
            account = InvestmentAccount(
                name="NM USD Live",
                owner_user_id=owner_id,
                target_capital=0.0,
                max_ticket_brl=0.0,
                auto_approve_enabled=False,
                broker_code="tastytrade",
                execution_mode=ExecutionMode.live,
                currency=AccountCurrency.USD,
                cash_brl=0.0,
                cash_usd=0.0,
                hv_dip_equity_usd=0.0,
                hv_dip_max_positions=4,
                hv_dip_cash_floor_pct=30.0,
                hv_dip_max_ticker_pct=80.0,
                swing_equity_brl=0.0,
            )
            print(f"Criando conta live: {account.name} (broker=tastytrade, mode=live)")
            if args.execute:
                db.add(account)
                db.flush()
            else:
                print("  (dry-run: conta não persistida)")

        # Cash balance mirror
        client = TastytradeClient(live=True)
        if client.configured():
            cash = client.fetch_cash_balance()
            if cash is None:
                print("  Credenciais live ok, mas não consegui ler cash-balance.")
            else:
                print(f"  cash-balance Tastytrade (live): {cash:.2f} USD")
                print(
                    f"  cash_usd {account.cash_usd} -> {cash:.2f}; "
                    f"hv_dip_equity_usd {account.hv_dip_equity_usd} -> {cash:.2f}"
                )
                if args.execute:
                    account.cash_usd = round(cash, 2)
                    account.hv_dip_equity_usd = round(cash, 2)
        else:
            print("  Credenciais live ausentes — saldo fica em 0 (avise o usuário).")

        # Membership + rule (only for a new account)
        if not existing:
            has_rule = (
                db.query(AccountRule)
                .filter(AccountRule.account_id == account.id)
                .first()
            )
            if not has_rule:
                print("  Criando AccountRule (us_equity) + AccountMembership owner")
                if args.execute:
                    db.add(
                        AccountRule(
                            account_id=account.id,
                            version=1,
                            is_active=True,
                            allowed_sectors=[],
                            excluded_tickers=[],
                            allowed_asset_classes=["us_equity"],
                            prefer_monthly_dividends=False,
                            min_effective_yield=0.0,
                            min_dividend_yield=0.0,
                            score_threshold=50.0,
                        )
                    )
                    db.add(
                        AccountMembership(
                            user_id=account.owner_user_id,
                            account_id=account.id,
                            role=MembershipRole.owner,
                        )
                    )

        # Watchlist seeding (idempotent via unique constraint)
        for ticker in WATCH_TICKERS:
            exists = (
                db.query(WatchlistItem)
                .filter(
                    WatchlistItem.account_id == account.id,
                    WatchlistItem.ticker == ticker,
                )
                .first()
            )
            if exists:
                print(f"  Observação {ticker}: já presente")
                continue
            print(f"  Observação {ticker}: adicionando")
            if args.execute:
                db.add(
                    WatchlistItem(
                        account_id=account.id,
                        ticker=ticker,
                        added_by_user_id=account.owner_user_id,
                        note="posição comprada — acompanhar",
                    )
                )

        if args.execute:
            try:
                db.commit()
                print("OK — conta live pronta.")
            except IntegrityError:
                db.rollback()
                print("Commit falhou (possível corrida). Re-execute.")
                return 1
        else:
            print("Dry-run. Re-execute com --execute para aplicar.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
