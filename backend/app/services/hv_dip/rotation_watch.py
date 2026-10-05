"""Suggest rotation when a better hv_dip setup appears and slots are tight."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.models import (
    InvestmentAccount,
    Position,
    PositionStatus,
    StrategyKind,
    Suggestion,
    SuggestionStatus,
)
from app.services.notify import notify_rotation_opportunity
from app.services.positions import count_open_hv_dip_tickers, mark_open_positions, portfolio_snapshot

logger = logging.getLogger("fiidesk.hv_dip.rotation_watch")

_cache_path = Path(get_settings().hv_dip_cache_dir) / "rotation_alerts.json"


def _load_sent() -> set[str]:
    if not _cache_path.exists():
        return set()
    try:
        data = json.loads(_cache_path.read_text(encoding="utf-8"))
        return set(data.get("keys") or [])
    except (OSError, json.JSONDecodeError):
        return set()


def _save_sent(keys: set[str]) -> None:
    _cache_path.parent.mkdir(parents=True, exist_ok=True)
    trimmed = list(keys)[-500:]
    _cache_path.write_text(json.dumps({"keys": trimmed}), encoding="utf-8")


def _entry_score(db: Session, position: Position) -> float | None:
    """Original suggestion score at entry — the comparable quality anchor.

    A rotation should only fire when a NEW setup is genuinely better than the
    one already held. The open position's entry score is stored on its source
    suggestion, so we compare apples-to-apples on the same 0-99 scale.
    """
    if position.suggestion_id is None:
        return None
    sug = db.get(Suggestion, position.suggestion_id)
    if sug is None or sug.score is None:
        return None
    return float(sug.score)


def run_hv_dip_rotation_watch(db: Session) -> int:
    settings = get_settings()
    if not settings.hv_dip_exit_v2_enabled:
        return 0

    sent_keys = _load_sent()
    sent = 0
    delta = float(settings.hv_dip_rotation_score_delta or 10.0)

    accounts = (
        db.query(InvestmentAccount)
        .filter(InvestmentAccount.broker_code == "tastytrade")
        .all()
    )
    for account in accounts:
        currency = str(getattr(account, "currency", "BRL") or "BRL")
        if not currency.endswith("USD"):
            continue

        snap = portfolio_snapshot(db, account)
        max_slots = int(snap.get("hv_dip_max_positions") or 4)
        open_tickers = int(snap.get("open_hv_dip_tickers") or 0)
        cash_pct = float(snap.get("cash_pct_of_equity") or 100.0)
        floor_pct = float(snap.get("hv_dip_cash_floor_pct") or 30.0)
        slots_full = open_tickers >= max_slots
        cash_tight = cash_pct <= floor_pct + 5.0
        if not slots_full and not cash_tight:
            continue

        pending = (
            db.query(Suggestion)
            .filter(
                Suggestion.account_id == account.id,
                Suggestion.strategy_kind == StrategyKind.hv_dip,
                Suggestion.status == SuggestionStatus.pending,
            )
            .order_by(Suggestion.score.desc())
            .limit(5)
            .all()
        )
        if not pending:
            continue

        enriched, _ = mark_open_positions(
            db, account.id, strategy_kind=StrategyKind.hv_dip
        )
        if not enriched:
            continue

        weakest: tuple[Position, float, float, float] | None = None
        for e in enriched:
            pos = e["position"]
            if e.get("mark_price") is None or e.get("no_mark"):
                continue
            entry_score = _entry_score(db, pos)
            if entry_score is None:
                continue
            upnl = float(e.get("unrealized_pnl_pct") or 0)
            mark = float(e.get("mark_price") or 0)
            if weakest is None or entry_score < weakest[1]:
                weakest = (pos, entry_score, upnl, mark)

        if weakest is None:
            continue
        open_pos, open_entry_score, open_upnl, weak_mark = weakest

        # Never rotate into a ticker we already hold (that's a tranche add-on,
        # not a rotation), and never rotate for a merely-equal-or-worse setup.
        open_tickers = {e["position"].ticker.upper() for e in enriched}
        for sug in pending:
            if sug.ticker.upper() in open_tickers:
                continue
            if float(sug.score) < open_entry_score + delta:
                continue
            dismissed = list((open_pos.metrics or {}).get("rotation_dismissed_ids") or [])
            if sug.id in dismissed:
                continue
            key = f"rotation:{open_pos.id}:{sug.id}"
            if key in sent_keys:
                continue
            notify_rotation_opportunity(
                db,
                account=account,
                open_position=open_pos,
                new_suggestion=sug,
                open_upnl_pct=open_upnl,
                open_mark=weak_mark,
            )
            sent_keys.add(key)
            sent += 1
            logger.info(
                "rotation alert %s -> %s score=%.0f vs open entry %.0f",
                open_pos.ticker,
                sug.ticker,
                sug.score,
                open_entry_score,
            )
            break

    if sent:
        _save_sent(sent_keys)
    return sent
