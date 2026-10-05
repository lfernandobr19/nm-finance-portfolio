"""Watch open hv_dip positions: auto-close + notify (Quick Target exit).

The broker-side OCO bracket owns stop/target when placed (live); this poll is
the fallback for paper/sandbox and owns the time-stop leg (market sell at the
hold horizon). Alerts are now only: stop, target, time_stop.

Every open position is explained: auto-close, exit_hold, or exit_skip no_mark.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.models import InvestmentAccount, PositionExitReason, StrategyKind
from app.services.notify import notify_position_alert
from app.services.positions import close_position, mark_open_positions

logger = logging.getLogger("fiidesk.hv_dip.exit_watch")

_sent_cache_path = Path(get_settings().hv_dip_cache_dir) / "exit_alerts.json"


def _load_sent() -> set[str]:
    if not _sent_cache_path.exists():
        return set()
    try:
        data = json.loads(_sent_cache_path.read_text(encoding="utf-8"))
        return set(data.get("keys") or [])
    except (OSError, json.JSONDecodeError):
        return set()


def _save_sent(keys: set[str]) -> None:
    _sent_cache_path.parent.mkdir(parents=True, exist_ok=True)
    trimmed = list(keys)[-500:]
    _sent_cache_path.write_text(json.dumps({"keys": trimmed}), encoding="utf-8")


_AUTO_CLOSE_ALERTS = ("stop", "target", "time_stop", "judgment_cut")


def run_hv_dip_exit_watch(db: Session) -> int:
    """Process exit alerts; auto-close when configured. Returns actions taken."""
    settings = get_settings()
    accounts = (
        db.query(InvestmentAccount)
        .filter(InvestmentAccount.broker_code == "tastytrade")
        .all()
    )
    sent_keys = _load_sent()
    actions = 0
    for account in accounts:
        currency = str(getattr(account, "currency", "BRL") or "BRL")
        if not currency.endswith("USD"):
            continue
        enriched, _ = mark_open_positions(
            db, account.id, strategy_kind=StrategyKind.hv_dip
        )
        for e in enriched:
            pos = e["position"]
            mark = e.get("mark_price")
            source = e.get("quote_source") or "none"
            if mark is None or e.get("no_mark"):
                logger.info("exit_skip no_mark %s", pos.ticker)
                continue
            mark_f = float(mark)
            alert = e.get("price_alert")
            if not alert:
                logger.info(
                    "exit_hold %s mark=%.2f stop=%s deadline=%s",
                    pos.ticker,
                    mark_f,
                    pos.stop_price,
                    e.get("must_review_by"),
                )
                continue
            key = f"{pos.id}:{alert}"

            if alert in _AUTO_CLOSE_ALERTS and e.get("auto_close"):
                if not settings.hv_dip_auto_close_enabled or account.automation_paused:
                    if key not in sent_keys:
                        notify_position_alert(
                            db,
                            account=account,
                            position=pos,
                            alert=str(alert),
                            mark_price=mark_f,
                        )
                        sent_keys.add(key)
                        actions += 1
                    continue

                try:
                    if alert == "time_stop":
                        close_position(
                            db, pos, reason=PositionExitReason.manual, manual_price=mark_f
                        )
                    elif alert == "judgment_cut":
                        close_position(
                            db, pos, reason=PositionExitReason.protect, manual_price=mark_f
                        )
                    else:
                        reason = (
                            PositionExitReason.stop
                            if alert == "stop"
                            else PositionExitReason.target
                        )
                        close_position(db, pos, reason=reason)
                    logger.info(
                        "auto-close %s %s mark=%.2f source=%s",
                        pos.ticker,
                        alert,
                        mark_f,
                        source,
                    )
                    actions += 1
                except ValueError as exc:
                    logger.warning("auto-close failed %s: %s", pos.ticker, exc)
                continue

            if key in sent_keys:
                continue

            notify_position_alert(
                db,
                account=account,
                position=pos,
                alert=str(alert),
                mark_price=mark_f,
            )
            sent_keys.add(key)
            actions += 1
            logger.info(
                "hv_dip exit alert %s %s mark=%.2f",
                pos.ticker,
                alert,
                mark_f,
            )

    if actions:
        _save_sent(sent_keys)
    return actions
