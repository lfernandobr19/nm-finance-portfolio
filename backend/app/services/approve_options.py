"""Compute approve amount options for hv_dip suggestions."""

from __future__ import annotations

import math

from sqlalchemy.orm import Session

from app.domain.models import InvestmentAccount, StrategyKind, Suggestion
from app.services.fractional_cache import is_fractional_blocked
from app.services.hv_dip.sizing import account_sizing_basis, deployed_on_ticker_usd
from app.services.orders import (
    _hv_dip_live_price,
    _quantity,
    _strategy_kind,
    assert_hv_dip_guards,
)


def _max_amount_usd(db: Session, account: InvestmentAccount, suggestion: Suggestion) -> float:
    """Upper bound for order amount after guardrails (binary search helper)."""
    basis = account_sizing_basis(db, account)
    letter = (getattr(suggestion, "swing_score_letter", None) or "").upper()
    spendable = basis.spendable(letter)
    deployed = deployed_on_ticker_usd(db, account.id, suggestion.ticker)
    ticker_room = max(0.0, basis.ticker_cap - deployed)
    # max_ticket_brl is a max ORDER VALUE ceiling. proposed_amount_brl is only the
    # default suggested amount, never a ceiling (avoids "1 share > máximo" false block).
    order_ceiling = float(account.max_ticket_brl or 0)
    ceiling = order_ceiling if order_ceiling > 0 else spendable
    return round(min(spendable, ticker_room, ceiling), 2)


def _amount_allowed(db: Session, account: InvestmentAccount, suggestion: Suggestion, amount: float) -> bool:
    if amount < 0.01:
        return False
    try:
        assert_hv_dip_guards(
            db, account, suggestion, amount_usd=amount, human_approved=True
        )
        return True
    except ValueError:
        return False


def build_approve_options(
    db: Session,
    account: InvestmentAccount,
    suggestion: Suggestion,
) -> dict:
    kind = _strategy_kind(suggestion)
    if kind != StrategyKind.hv_dip:
        amt = float(suggestion.proposed_amount_brl or account.max_ticket_brl or 0)
        return {
            "live_price": float(suggestion.entry_price or 0),
            "fractional_allowed": True,
            "max_amount_usd": amt,
            "default_amount_usd": amt,
            "approvable": amt >= 0.01,
            "block_reason": None if amt >= 0.01 else "Valor proposto inválido",
            "options": [
                {
                    "amount_usd": amt,
                    "quantity": None,
                    "label": f"US$ {amt:.2f}",
                    "mode": "default",
                }
            ]
            if amt >= 0.01
            else [],
        }

    live_price, _ = _hv_dip_live_price(suggestion)
    max_amt = _max_amount_usd(db, account, suggestion)
    default_amt = float(suggestion.proposed_amount_brl or account.max_ticket_brl or max_amt)
    default_amt = round(min(default_amt, max_amt), 2) if max_amt > 0 else 0.0

    fractional_allowed = not is_fractional_blocked(suggestion.ticker)
    if live_price > max_amt + 0.01 and fractional_allowed:
        fractional_allowed = False

    options: list[dict] = []
    block_reason: str | None = None

    if fractional_allowed:
        if max_amt >= 0.01 and _amount_allowed(db, account, suggestion, max_amt):
            qty = _quantity(max_amt, live_price, fractional=True)
            options.append(
                {
                    "amount_usd": max_amt,
                    "quantity": qty,
                    "label": f"US$ {max_amt:.2f} (notional ~{qty:.4g} ações)",
                    "mode": "notional_market",
                }
            )
        if default_amt >= 0.01 and default_amt != max_amt and _amount_allowed(
            db, account, suggestion, default_amt
        ):
            qty = _quantity(default_amt, live_price, fractional=True)
            options.append(
                {
                    "amount_usd": default_amt,
                    "quantity": qty,
                    "label": f"US$ {default_amt:.2f} (ticket · ~{qty:.4g} ações)",
                    "mode": "notional_market",
                }
            )
        if not options:
            block_reason = (
                f"Caixa/guardrails insuficientes para {suggestion.ticker} "
                f"(máx US$ {max_amt:.2f})."
            )
    else:
        whole_max = int(math.floor(max_amt / live_price)) if live_price > 0 else 0
        for n in range(1, whole_max + 1):
            amt = round(n * live_price, 2)
            if not _amount_allowed(db, account, suggestion, amt):
                break
            options.append(
                {
                    "amount_usd": amt,
                    "quantity": float(n),
                    "label": f"{n} ação{'s' if n > 1 else ''} · US$ {amt:.2f}",
                    "mode": "limit_live",
                }
            )
        if not options:
            block_reason = (
                f"{suggestion.ticker}: fractional indisponível; "
                f"1 ação = US$ {live_price:.2f} > máximo US$ {max_amt:.2f}."
            )

    approvable = bool(options)
    return {
        "live_price": round(live_price, 2),
        "fractional_allowed": fractional_allowed,
        "max_amount_usd": max_amt,
        "default_amount_usd": default_amt if approvable else None,
        "approvable": approvable,
        "block_reason": block_reason,
        "options": options,
    }


def validate_approve_amount(
    db: Session,
    account: InvestmentAccount,
    suggestion: Suggestion,
    amount_usd: float,
) -> None:
    """Raise ValueError if amount is not in computed options."""
    opts = build_approve_options(db, account, suggestion)
    if not opts["approvable"]:
        raise ValueError(opts["block_reason"] or "Sugestão não pode ser aprovada")
    allowed = {round(float(o["amount_usd"]), 2) for o in opts["options"]}
    amt = round(float(amount_usd), 2)
    if opts["fractional_allowed"]:
        if amt < 0.01 or amt > float(opts["max_amount_usd"]) + 0.01:
            raise ValueError(
                f"Valor US$ {amt:.2f} fora do permitido (máx US$ {opts['max_amount_usd']:.2f})."
            )
        assert_hv_dip_guards(
            db, account, suggestion, amount_usd=amt, human_approved=True
        )
        return
    if amt not in allowed:
        raise ValueError(
            f"Valor US$ {amt:.2f} não permitido para {suggestion.ticker} "
            f"(fractional indisponível — escolha uma opção da lista)."
        )
