"""Read-only views of what the desk learned, blocked, or calibrated.

Cheap: no LLM, no walk-forward. Used by job_react pulse patches and the
intelligence GET endpoints.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.models import (
    DayTradeConfigHistory,
    DeskBudgetConfig,
    DeskDecision,
    ForecastLedger,
    HvDipConfigHistory,
    Position,
    PositionStatus,
    StrategyKind,
)

logger = logging.getLogger("fiidesk.learn.evolution")

# Cash/infra denies are not a thesis storm. scan_skip is audit, not a gate deny.
_ALWAYS_BLOCK = {"unaffordable", "invalid_notional", "paused"}
_THESIS_DENY_REASONS = {
    "miscalibrated",
    "budget",
    "learn_skip",
    "regime",
    "regime_lock",
    "cash_floor",
    "window_busy",
    "cooldown",
    "stoploss_guard",
    "max_drawdown",
    "low_profit_pair",
}


def _is_thesis_deny(row: Any) -> bool:
    verdict = str(getattr(row, "verdict", "") or "")
    reason = str(getattr(row, "reason", "") or "")
    if verdict != "deny":
        return False
    if verdict.startswith("scan") or reason in _ALWAYS_BLOCK:
        return False
    return reason in _THESIS_DENY_REASONS


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.isoformat()
    return str(v)


def cheap_status_patch(db: Session) -> dict[str, Any]:
    """Fields job_react can refresh without calling an LLM."""
    from app.services.intelligence import _assertiveness, _memory_status, _research_status
    from app.services.learn.news_whitelist import read_whitelist
    from app.services.learn.trials import load_all as load_trials

    settings = get_settings()
    return {
        "assertiveness": _assertiveness(db),
        "memory": _memory_status(),
        "research": _research_status(),
        "platt": _platt_snapshot(),
        "dt_gates": _dt_gates(db),
        "whitelist": read_whitelist(),
        "trials": load_trials(),
        "desk_slices": _desk_slices(db),
        "live_promotion": live_promotion_checklist(db),
        "hv_dip_auto_buy_enabled": bool(settings.hv_dip_auto_buy_enabled),
        "hv_dip_live_auto_buy": bool(getattr(settings, "hv_dip_live_auto_buy", False)),
    }


def _platt_snapshot() -> dict[str, Any]:
    from app.services.learn.calibration import load_calibrators

    return load_calibrators()


def _dt_gates(db: Session) -> dict[str, Any]:
    """Lab-wide day-trade expectancy cuts (n≥10 and sum R ≤ 0)."""
    try:
        from app.services.day_trade.gating import compute_gates

        gates = compute_gates(db)
        return {
            "rules": sorted(gates.get("rules") or []),
            "tickers": sorted(gates.get("tickers") or []),
            "reason": "soma R",
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("dt_gates pulse skipped: %s", exc)
        return {"rules": [], "tickers": [], "reason": "soma R"}


def _desk_slices(db: Session) -> dict[str, Any] | None:
    try:
        row = (
            db.query(DeskBudgetConfig)
            .filter(DeskBudgetConfig.is_active.is_(True))
            .order_by(DeskBudgetConfig.version.desc())
            .first()
        )
    except Exception:
        return None
    if row is None:
        return None
    return {
        "version": row.version,
        "slices": row.slices,
        "origin": row.origin,
        "validation": row.validation,
        "activated_at": _iso(row.activated_at),
    }


def live_promotion_checklist(db: Session) -> dict[str, Any]:
    """Visible gates before USD live may auto-buy. Never flips the flag."""
    from app.services.learn.calibration import reliability_curve
    from app.services.learn.ledger import ledger_summary, resolved_pairs

    settings = get_settings()
    min_n = int(settings.desk_gate_calibration_min_resolved or 30)
    max_brier = float(settings.desk_gate_calibration_max_brier or 0.30)
    max_gap = float(settings.desk_gate_calibration_max_bucket_gap or 0.25)
    min_bucket = int(settings.desk_gate_calibration_min_bucket_n or 8)

    n_closed = (
        db.query(Position)
        .filter(
            Position.status == PositionStatus.closed,
            Position.strategy_kind == StrategyKind.hv_dip,
        )
        .count()
    )
    summary = ledger_summary(db).get("hv_dip") or {}
    resolved = int(summary.get("resolved") or 0)
    brier = summary.get("brier")
    pairs = resolved_pairs(db, source="hv_dip")
    bad_bucket = False
    for bucket in reliability_curve(pairs):
        if int(bucket["n"]) >= min_bucket and abs(float(bucket["gap"])) > max_gap:
            bad_bucket = True
            break

    suppress_n = 0
    try:
        from app.services.studies.apply import read_guards

        for g in read_guards().values():
            if isinstance(g, dict) and (g.get("suppress") or g.get("force_review")):
                suppress_n += 1
    except Exception:
        logger.debug("live checklist guards skipped", exc_info=True)

    from datetime import timedelta

    since = datetime.now(timezone.utc) - timedelta(days=7)

    def _within(ts: Any) -> bool:
        if ts is None:
            return True
        if isinstance(ts, datetime) and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        try:
            return ts >= since
        except TypeError:
            return True

    try:
        recent = [
            SimpleNamespace(verdict=verdict, reason=reason, created_at=created_at)
            for verdict, reason, created_at in db.query(
                DeskDecision.verdict, DeskDecision.reason, DeskDecision.created_at
            ).filter(DeskDecision.enforce.is_(True))
            if _within(created_at)
        ]
    except Exception:
        recent = []
    thesis_denies = sum(1 for r in recent if _is_thesis_deny(r))
    deny_storm = thesis_denies >= 10

    items = [
        {
            "id": "paper_n",
            "ok": int(n_closed or 0) >= min_n,
            "detail": f"hv_dip fechados={n_closed} piso={min_n}",
        },
        {
            "id": "brier",
            "ok": brier is not None and float(brier) <= max_brier and resolved >= min_n,
            "detail": f"Brier hv_dip={brier} resolved={resolved} teto={max_brier}",
        },
        {
            "id": "buckets",
            "ok": not bad_bucket,
            "detail": "nenhum bucket n≥8 com |gap|>0.25" if not bad_bucket else "curva com gap",
        },
        {
            "id": "fdr_guards",
            "ok": True,
            "detail": f"guards FDR ativos={suppress_n} (study_suppressed no audit)",
        },
        {
            "id": "gate_enforce",
            "ok": bool(settings.desk_gate_enforce) and not deny_storm,
            "detail": (
                f"desk_gate_enforce={settings.desk_gate_enforce} "
                f"deny_tese 7d={thesis_denies}/{len(recent)}"
            ),
        },
        {
            "id": "kill_switch",
            "ok": True,
            "detail": "automation_paused no modelo da conta",
        },
        {
            "id": "daily_cap",
            "ok": True,
            "detail": (
                f"hv_dip_auto_buy_daily_cash_pct="
                f"{getattr(settings, 'hv_dip_auto_buy_daily_cash_pct', None)}"
            ),
        },
        {
            "id": "live_flag_off_until_ready",
            "ok": True,
            "detail": f"hv_dip_live_auto_buy={bool(getattr(settings, 'hv_dip_live_auto_buy', False))}",
        },
    ]
    return {
        "ready": all(i["ok"] for i in items if i["id"] != "live_flag_off_until_ready"),
        "items": items,
    }


def list_memories(*, limit: int = 50) -> list[dict[str, Any]]:
    from app.services.learn.memory import list_recent

    return list_recent(limit=limit)


def list_ledger(
    db: Session,
    *,
    source: str | None = None,
    resolved: bool | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    q = db.query(ForecastLedger)
    if source:
        q = q.filter(ForecastLedger.source == source)
    if resolved is True:
        q = q.filter(ForecastLedger.resolved_at.is_not(None))
    elif resolved is False:
        q = q.filter(ForecastLedger.resolved_at.is_(None))
    rows = q.order_by(ForecastLedger.created_at.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "source": r.source,
            "kind": r.kind,
            "ticker": r.ticker,
            "p_pred": r.p_pred,
            "horizon_days": r.horizon_days,
            "outcome": r.outcome,
            "brier": r.brier,
            "created_at": _iso(r.created_at),
            "resolved_at": _iso(r.resolved_at),
        }
        for r in rows
    ]


def list_decisions(
    db: Session,
    *,
    limit: int = 50,
    verdict: str | None = None,
) -> list[dict[str, Any]]:
    q = db.query(DeskDecision)
    if verdict:
        q = q.filter(DeskDecision.verdict == verdict)
    rows = q.order_by(DeskDecision.created_at.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "ticker": r.ticker,
            "strategy_kind": r.strategy_kind.value if hasattr(r.strategy_kind, "value") else str(r.strategy_kind),
            "verdict": r.verdict,
            "reason": r.reason,
            "notional": r.notional,
            "enforce": r.enforce,
            "created_at": _iso(r.created_at),
        }
        for r in rows
    ]


def calibration_view(db: Session) -> dict[str, Any]:
    from app.services.intelligence import _assertiveness
    from app.services.learn.calibration import load_calibrators

    return {
        "calibrators": load_calibrators(),
        "assertiveness": _assertiveness(db),
    }


def list_evolution(db: Session, *, limit: int = 50) -> list[dict[str, Any]]:
    """Merge recent learn/block/calibrate events, newest first."""
    events: list[dict[str, Any]] = []
    try:
        from app.services.learn.memory import list_recent

        for m in list_recent(limit=min(limit, 40)):
            events.append(
                {
                    "ts": m.get("created_at"),
                    "kind": "memory",
                    "title": f"{'REFUTADA' if m.get('refuted') else 'lição'} {m.get('scope')}",
                    "detail": str(m.get("text") or "")[:240],
                }
            )
    except Exception:
        logger.debug("evolution memory skipped", exc_info=True)

    try:
        for r in db.query(DeskDecision).order_by(DeskDecision.created_at.desc()).limit(30):
            events.append(
                {
                    "ts": _iso(r.created_at),
                    "kind": "decision",
                    "title": f"{r.verdict} {r.ticker}",
                    "detail": r.reason,
                }
            )
    except Exception:
        logger.debug("evolution decisions skipped", exc_info=True)

    try:
        for r in (
            db.query(HvDipConfigHistory)
            .order_by(HvDipConfigHistory.created_at.desc())
            .limit(10)
        ):
            events.append(
                {
                    "ts": _iso(r.created_at),
                    "kind": "hv_dip_config",
                    "title": f"hv_dip v{r.version} {r.origin}",
                    "detail": (r.reason or "")[:240],
                }
            )
    except Exception:
        logger.debug("evolution hv_dip history skipped", exc_info=True)

    try:
        for r in (
            db.query(DayTradeConfigHistory)
            .order_by(DayTradeConfigHistory.created_at.desc())
            .limit(10)
        ):
            events.append(
                {
                    "ts": _iso(r.created_at),
                    "kind": "day_trade_config",
                    "title": f"day_trade v{r.version} {r.origin}",
                    "detail": (r.reason or "")[:240],
                }
            )
    except Exception:
        logger.debug("evolution dt history skipped", exc_info=True)

    try:
        from app.services.learn.news_whitelist import read_whitelist

        w = read_whitelist()
        if w.get("ts"):
            events.append(
                {
                    "ts": w.get("ts"),
                    "kind": "whitelist",
                    "title": f"whitelist {w.get('status')}",
                    "detail": ",".join(str(t) for t in (w.get("allowed") or [])),
                }
            )
    except Exception:
        logger.debug("evolution whitelist skipped", exc_info=True)

    try:
        platt = _platt_snapshot()
        for src, entry in platt.items():
            if not isinstance(entry, dict):
                continue
            ts = entry.get("fitted_at")
            if not ts:
                continue
            events.append(
                {
                    "ts": ts,
                    "kind": "platt",
                    "title": f"Platt {src}",
                    "detail": f"n={entry.get('n')} brier={entry.get('brier_calibrated')}",
                }
            )
    except Exception:
        logger.debug("evolution platt skipped", exc_info=True)

    try:
        qpath = Path(".cache/fiidesk/research_queue.db")
        if qpath.exists():
            import sqlite3

            conn = sqlite3.connect(str(qpath))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT task, status, finished_at, created_at FROM queue "
                "ORDER BY COALESCE(finished_at, created_at) DESC LIMIT 15"
            ).fetchall()
            conn.close()
            for r in rows:
                events.append(
                    {
                        "ts": r["finished_at"] or r["created_at"],
                        "kind": "research",
                        "title": f"{r['task']} {r['status']}",
                        "detail": "",
                    }
                )
    except Exception:
        logger.debug("evolution research skipped", exc_info=True)

    def _key(e: dict[str, Any]) -> str:
        return str(e.get("ts") or "")

    events.sort(key=_key, reverse=True)
    return events[:limit]


__all__ = [
    "cheap_status_patch",
    "live_promotion_checklist",
    "list_memories",
    "list_ledger",
    "list_decisions",
    "list_evolution",
    "calibration_view",
]
