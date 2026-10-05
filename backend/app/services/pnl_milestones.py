"""P&L milestone notifications (loss/gain) for USD accounts.

Replaces a hard "daily loss stops the bot" rule with a set of notification
milestones (e.g. ±2.5 / ±5 / ±7.5 / ±10 USD). When the daily net P&L
(realized + unrealized) crosses a milestone in either direction, the owner is
notified once. State is persisted per-account/day in a cache file, mirroring the
pattern used by `exit_watch` (exit_alerts.json).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.models import InvestmentAccount
from app.services.notify import notify_pnl_milestone
from app.services.positions import mark_open_positions, portfolio_snapshot

logger = logging.getLogger("fiidesk.pnl_milestones")

_state_path = Path(get_settings().hv_dip_cache_dir) / "pnl_milestones.json"


def _load_state() -> dict:
    if not _state_path.exists():
        return {}
    try:
        return json.loads(_state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    _state_path.parent.mkdir(parents=True, exist_ok=True)
    _state_path.write_text(json.dumps(state), encoding="utf-8")


def _parse_milestones(raw: str) -> list[float]:
    out: list[float] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            v = float(part)
        except ValueError:
            continue
        if v > 0:
            out.append(v)
    return sorted(out)


def _daily_net_pnl(db: Session, account: InvestmentAccount) -> float:
    """Realized today + unrealized on open positions (mark-to-market)."""
    snap = portfolio_snapshot(db, account)
    realized = float(snap.get("realized_pnl_day_brl") or 0)
    unrealized = float(snap.get("unrealized_pnl_brl") or 0)
    return round(realized + unrealized, 2)


def run_pnl_milestones(db: Session) -> int:
    """Evaluate USD accounts and notify on any newly-crossed milestone."""
    settings = get_settings()
    if not settings.pnl_milestones_enabled:
        return 0
    milestones = _parse_milestones(settings.pnl_milestones_usd)
    if not milestones:
        return 0

    accounts = (
        db.query(InvestmentAccount)
        .filter(InvestmentAccount.broker_code == "tastytrade")
        .all()
    )

    today = datetime.now(timezone.utc).date().isoformat()
    state = _load_state()
    sent = 0

    for account in accounts:
        currency = str(getattr(account, "currency", "BRL") or "BRL")
        if not currency.endswith("USD"):
            continue

        pnl = _daily_net_pnl(db, account)
        if pnl == 0:
            continue

        acc_state = state.get(account.id)
        if not isinstance(acc_state, dict) or acc_state.get("date") != today:
            acc_state = {"date": today, "pos": 0.0, "neg": 0.0}

        direction = "pos" if pnl > 0 else "neg"
        magnitude = abs(pnl)
        last = float(acc_state.get(direction, 0.0) or 0.0)

        # Notify for each newly-crossed milestone in this direction.
        newly = [m for m in milestones if last < m <= magnitude]
        for m in newly:
            try:
                notify_pnl_milestone(db, account=account, pnl=pnl, milestone=m)
                sent += 1
            except Exception:  # noqa: BLE001
                logger.exception("pnl milestone notify failed %s", account.id)
        if newly:
            acc_state[direction] = max(magnitude, last)
            state[account.id] = acc_state

    if sent:
        _save_state(state)
    return sent


__all__ = ["run_pnl_milestones"]
