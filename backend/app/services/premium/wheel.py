"""Premium wheel (Fase B) — skeleton.

A "Roda" (wheel) de venda de opções: vende put garantido em dinheiro
(cash-secured put) para coletar prêmio; se exercido, passa a deter o ativo e
passa a vender call coberta (covered call); se a call for exercida, entrega o
ativo e reinicia o ciclo.

Este módulo é APENAS o esqueleto. Nada é executado até que todas as condições
sejam satisfeitas (conta live aprovada + opções habilitadas + capital mínimo) e
os parâmetros de seleção sejam validados por walk-forward, como o Quick Target.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.models import (
    AccountCurrency,
    ExecutionMode,
    InvestmentAccount,
)

logger = logging.getLogger("fiidesk.premium.wheel")

_OPTIONS_NONE = ("", "none", "null")


def _resolve_account(db: Session) -> InvestmentAccount | None:
    """Return the target live USD tastytrade account, or None when none exists."""
    settings = get_settings()
    if (settings.premium_account_id or "").strip():
        return db.get(InvestmentAccount, settings.premium_account_id.strip())
    return (
        db.query(InvestmentAccount)
        .filter(
            InvestmentAccount.currency == AccountCurrency.USD,
            InvestmentAccount.broker_code == "tastytrade",
            InvestmentAccount.execution_mode == ExecutionMode.live,
        )
        .order_by(InvestmentAccount.created_at.asc())
        .first()
    )


def _options_level_ok(level: str | None) -> bool:
    """True when the account has some options approval (not "None"/absent)."""
    return level is not None and str(level).strip().lower() not in _OPTIONS_NONE


def wheel_eligible(
    db: Session,
    account: InvestmentAccount | None,
    *,
    options_level: str | None = None,
) -> tuple[bool, str]:
    """Gate the wheel. Returns (eligible, human-readable reason).

    The exact options-level → strategy mapping (CSP vs. covered call) is TBD;
    for the skeleton, any non-"None" level is treated as potentially eligible.
    """
    settings = get_settings()
    if not settings.premium_enabled:
        return False, "premium_enabled=False"
    if account is None:
        return False, "sem conta USD tastytrade live"
    if bool(getattr(account, "automation_paused", False)):
        return False, "kill switch ativo"
    mode = getattr(account, "execution_mode", None)
    mode_val = mode.value if hasattr(mode, "value") else str(mode)
    if mode_val != "live":
        return False, "conta não é live"
    if not _options_level_ok(options_level):
        return False, "opções não aprovadas na Tastytrade"
    cash = float(getattr(account, "cash_usd", None) or 0)
    if cash < float(settings.premium_min_capital_usd or 0):
        return False, (
            f"capital abaixo do mínimo (US$ {cash:.2f} < "
            f"US$ {settings.premium_min_capital_usd:.2f})"
        )
    return True, "ok"


def _select_cash_secured_put(account: InvestmentAccount, ticker: str) -> dict | None:
    """Placeholder: choose strike/DTE for a cash-secured put.

    Returns a dict {option_symbol, quantity, limit_price} or None when no
    qualifying setup is found. Intentionally returns None until the selection
    parameters (delta/DTE/strike) are validated by walk-forward.
    """
    # TODO(fase B): implement strike/DTE selection once options approval is
    # confirmed and the parameters are backtested (delta <= premium_max_delta,
    # DTE in [dte_min, dte_max], premium >= premium_min_premium_usd).
    return None


def run_premium_wheel_cycle(db: Session) -> int:
    """Execute due premium-wheel trades. Returns the number of contracts sold.

    Skeleton: performs the full eligibility gate and returns 0 (no orders) until
    the account is approved for options and the selection is backtested.
    """
    settings = get_settings()
    if not settings.premium_enabled:
        return 0

    account = _resolve_account(db)
    client = None
    options_level: str | None = None
    if account is not None and not bool(getattr(account, "automation_paused", False)):
        from app.services.tastytrade_client import TastytradeClient

        client = TastytradeClient(live=True)
        if client.configured():
            options_level = client.fetch_options_level()

    eligible, reason = wheel_eligible(db, account, options_level=options_level)
    if not eligible:
        logger.info("premium wheel: skip (%s)", reason)
        return 0

    # Selection + submission are intentionally stubbed. When enabled, this
    # becomes: for each premium_tickers -> _select_cash_secured_put -> client.
    # submit_cash_secured_put -> track assignment/covered-call state.
    sold = 0
    logger.info(
        "premium wheel: eligible (capital=%.2f, options_level=%s), but selection "
        "not implemented — sold=%d",
        float(getattr(account, "cash_usd", None) or 0),
        options_level,
        sold,
    )
    return sold


__all__ = [
    "run_premium_wheel_cycle",
    "wheel_eligible",
]
