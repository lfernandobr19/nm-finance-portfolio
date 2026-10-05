from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.models import (
    AccountRule,
    InvestmentAccount,
    MarketSnapshot,
    NewsItem,
    StrategyKind,
    Suggestion,
    SuggestionStatus,
)
from app.services.llm_summary import generate_llm_summary
from app.services.notify import notify_suggestion
from app.services.orders import create_order_from_suggestion
from app.services.scoring import build_price_explanation, score_snapshot

settings = get_settings()


def _active_rule(db: Session, account_id: str) -> AccountRule | None:
    return (
        db.query(AccountRule)
        .filter(AccountRule.account_id == account_id, AccountRule.is_active.is_(True))
        .order_by(AccountRule.version.desc())
        .first()
    )


def _pending_exists(db: Session, account_id: str, ticker: str) -> bool:
    return (
        db.query(Suggestion)
        .filter(
            Suggestion.account_id == account_id,
            Suggestion.ticker == ticker,
            Suggestion.strategy_kind == StrategyKind.income,
            Suggestion.status == SuggestionStatus.pending,
        )
        .count()
        > 0
    )


def _auto_approved_today(db: Session, account_id: str) -> int:
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        db.query(Suggestion)
        .filter(
            Suggestion.account_id == account_id,
            Suggestion.status == SuggestionStatus.auto_approved,
            Suggestion.acted_at >= start,
        )
        .count()
    )


def _news_titles(db: Session, ticker: str) -> list[str]:
    rows = (
        db.query(NewsItem.title)
        .filter(NewsItem.ticker == ticker.upper())
        .order_by(NewsItem.published_at.desc().nullslast())
        .limit(5)
        .all()
    )
    return [r[0] for r in rows]


def _is_income_account(account: InvestmentAccount) -> bool:
    """Income desk (FIIs/BDR) runs on BRL accounts only — not NM USD."""
    currency = getattr(account, "currency", None)
    currency_val = currency.value if hasattr(currency, "value") else str(currency or "BRL")
    broker = (getattr(account, "broker_code", None) or "inter").lower()
    if currency_val.upper().endswith("USD"):
        return False
    return True


def create_suggestions_from_snapshots(
    db: Session, snapshots: list[MarketSnapshot]
) -> list[Suggestion]:
    accounts = db.query(InvestmentAccount).all()
    created: list[Suggestion] = []
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.suggestion_ttl_hours)

    for account in accounts:
        if not _is_income_account(account):
            continue
        rule = _active_rule(db, account.id)
        if not rule:
            continue
        for snap in snapshots:
            result = score_snapshot(snap, rule)
            if not result.passed:
                continue
            if _pending_exists(db, account.id, snap.ticker):
                continue

            status = SuggestionStatus.pending
            acted_at = None
            if (
                account.auto_approve_enabled
                and not account.automation_paused
                and result.score >= account.auto_approve_min_score
                and _auto_approved_today(db, account.id) < account.daily_auto_approve_limit
            ):
                status = SuggestionStatus.auto_approved
                acted_at = datetime.now(timezone.utc)

            amount = min(account.max_ticket_brl, account.target_capital or account.max_ticket_brl)
            explanation = build_price_explanation(snap, result.reasons)
            metrics = {
                "price": snap.price,
                "gross_yield": snap.dividend_yield,
                "effective_yield": result.effective_yield,
                "withholding_rate": snap.withholding_rate,
                "p_vp": snap.p_vp,
                "avg_volume": snap.avg_volume,
                "change_day_pct": snap.change_day_pct,
                "change_month_pct": snap.change_month_pct,
                "sector": snap.sector,
                "name": snap.name,
                "asset_class": snap.asset_class.value,
                "dividend_frequency": snap.dividend_frequency.value,
                "currency_exposure": snap.currency_exposure.value,
                "underlying_ticker": snap.underlying_ticker,
                "venue": snap.venue,
            }
            llm_summary = generate_llm_summary(
                ticker=snap.ticker,
                metrics=metrics,
                reasons=result.reasons,
                price_explanation=explanation,
                news_titles=_news_titles(db, snap.ticker),
            )
            suggestion = Suggestion(
                account_id=account.id,
                ticker=snap.ticker,
                strategy_kind=StrategyKind.income,
                asset_class=snap.asset_class,
                dividend_frequency=snap.dividend_frequency,
                score=result.score,
                status=status,
                reasons=result.reasons,
                metrics=metrics,
                price_explanation=explanation,
                llm_summary=llm_summary,
                rule_version=rule.version,
                proposed_amount_brl=amount,
                expires_at=expires_at,
                acted_at=acted_at,
            )
            db.add(suggestion)
            db.flush()
            created.append(suggestion)
            if status == SuggestionStatus.auto_approved:
                create_order_from_suggestion(db, suggestion, acted_by_user_id=None)
            # Notify pending and auto_approved so owners see activity
            notify_suggestion(db, suggestion)

    db.commit()
    for s in created:
        db.refresh(s)
    return created


def expire_stale_suggestions(db: Session) -> int:
    now = datetime.now(timezone.utc)
    q = db.query(Suggestion).filter(
        Suggestion.status == SuggestionStatus.pending,
        Suggestion.expires_at < now,
    )
    count = q.update({Suggestion.status: SuggestionStatus.expired}, synchronize_session=False)
    db.commit()
    return count
