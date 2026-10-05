"""Nightly intelligence pulse: calibrate LLM, review closes, snapshot learn status."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.models import Position, PositionStatus, StrategyKind
from app.services.llm_client import local_configured

logger = logging.getLogger("fiidesk.intelligence")

STATUS_PATH = Path(".cache/fiidesk/intelligence.json")


def _learn_status(kind: str, result: dict[str, Any] | None) -> dict[str, Any]:
    res = result or {}
    status = str(res.get("status") or "unknown")
    n = res.get("n_trades")
    if n is None and isinstance(res.get("wf"), dict):
        n = res["wf"].get("n_trades") or res["wf"].get("oos_n")
    logger.info("learn_status kind=%s n=%s status=%s", kind, n, status)
    return {"status": status, "n": n}


def write_intelligence_status(payload: dict[str, Any]) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def empty_pulse() -> dict[str, Any]:
    return {
        "available": False,
        "ts": None,
        "llm_default": None,
        "last_source": None,
        "news_json_ok": None,
        "n_closed_usd": 0,
        "learn": {},
        "reviews_n": 0,
        "calibration": None,
        "hv_dip_auto_buy_enabled": False,
        "recent_reviews": [],
        "swing_h1": None,
        "studies": None,
        "ollama": None,
        "groq_cooldown": None,
        "assertiveness": None,
        "research": None,
        "memory": None,
        "platt": None,
        "dt_gates": None,
        "whitelist": None,
        "trials": None,
        "desk_slices": None,
        "live_promotion": None,
        "hv_dip_live_auto_buy": False,
    }


def read_intelligence_status() -> dict[str, Any]:
    """Read the last pulse snapshot. Does not run the job."""
    if not STATUS_PATH.exists():
        return empty_pulse()
    try:
        data = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_pulse()
    if not isinstance(data, dict):
        return empty_pulse()
    data.setdefault("available", True)
    data.setdefault("recent_reviews", [])
    data.setdefault("learn", {})
    data.setdefault("n_closed_usd", 0)
    data.setdefault("reviews_n", 0)
    data.setdefault("hv_dip_auto_buy_enabled", False)
    data.setdefault("swing_h1", None)
    data.setdefault("studies", None)
    return data


def patch_intelligence_status(patch: dict[str, Any]) -> None:
    """Merge keys into the snapshot without marking the nightly pulse available."""
    data = read_intelligence_status()
    data.update(patch)
    write_intelligence_status(data)


def _recent_reviews(db: Session, *, limit: int = 5) -> list[dict[str, Any]]:
    rows = (
        db.query(Position)
        .filter(Position.status == PositionStatus.closed)
        .order_by(Position.closed_at.desc().nullslast())
        .limit(40)
        .all()
    )
    out: list[dict[str, Any]] = []
    for pos in rows:
        review = (pos.metrics or {}).get("llm_review")
        if not isinstance(review, dict):
            continue
        conf = review.get("confidence")
        try:
            conf_f = float(conf) if conf is not None else None
        except (TypeError, ValueError):
            conf_f = None
        out.append(
            {
                "ticker": pos.ticker,
                "lesson": str(review.get("lesson") or "")[:400],
                "would_change": str(review.get("would_change") or ""),
                "confidence": conf_f,
                "source": review.get("source"),
            }
        )
        if len(out) >= limit:
            break
    return out


def _assertiveness(db: Session) -> dict[str, Any]:
    try:
        from app.services.learn.calibration import load_calibrators, reliability_curve
        from app.services.learn.ledger import SOURCES, ledger_summary, resolved_pairs

        summary = ledger_summary(db)
        # Always expose mega_rotation / judgment even with n < 30 (gate deny floor).
        sources = list(dict.fromkeys([*SOURCES, *summary.keys()]))
        curves = {}
        for source in sources:
            curve = reliability_curve(resolved_pairs(db, source=source))
            if curve:
                curves[source] = curve
        return {
            "by_source": summary,
            "calibrators": load_calibrators(),
            "curves": curves,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("assertiveness pulse skipped: %s", exc)
        return {}


def _research_status() -> dict[str, Any]:
    try:
        from app.services.learn.research import status

        return status()
    except Exception:
        return {}


def _memory_status() -> dict[str, Any]:
    try:
        from app.services.learn.memory import status

        return status()
    except Exception:
        return {}


def _run_studies_snapshot(db: Session) -> dict[str, Any] | None:
    """Run active learn studies (bars → analogies). Never blocks the pulse on failure."""
    try:
        from app.services.studies.runner import run_studies

        return run_studies(db)
    except Exception as exc:  # noqa: BLE001 — studies are best-effort
        logger.warning("studies pulse skipped: %s", exc)
        return None


def run_intelligence_pulse(db: Session) -> dict[str, Any]:
    """Calibrate → review (cap 10) → learn snapshots. LLM never places orders."""
    settings = get_settings()
    from app.services.llm_calibrate import calibrate_news_outcomes
    from app.services.trade_review import review_closed_positions
    from app.services.hv_dip.learning import run_learning as run_hv
    from app.services.desk_learn import run_budget_learning
    from app.services.day_trade.learning import run_learning as run_dt

    cal = calibrate_news_outcomes(db)
    reviews_n = review_closed_positions(db, limit=10)
    hv = run_hv(db)
    desk = run_budget_learning(db)
    dt = run_dt(db)

    prev = read_intelligence_status()
    n_closed = (
        db.query(Position)
        .filter(
            Position.status == PositionStatus.closed,
            Position.strategy_kind.in_(
                (StrategyKind.hv_dip, StrategyKind.index_core, StrategyKind.mega_rotation)
            ),
        )
        .count()
    )
    payload = {
        "available": True,
        "ts": datetime.now(timezone.utc).isoformat(),
        "llm_default": settings.llm_local_model if local_configured() else settings.llm_model,
        "last_source": (cal or {}).get("prompt_version"),
        "news_json_ok": (cal or {}).get("n_labeled"),
        "n_closed_usd": int(n_closed or 0),
        "learn": {
            "hv_dip": _learn_status("hv_dip", hv if isinstance(hv, dict) else {"status": str(hv)}),
            "desk": _learn_status("desk", desk if isinstance(desk, dict) else {"status": str(desk)}),
            "day_trade": _learn_status("day_trade", dt if isinstance(dt, dict) else {"status": str(dt)}),
        },
        "reviews_n": reviews_n,
        "calibration": cal,
        "hv_dip_auto_buy_enabled": bool(settings.hv_dip_auto_buy_enabled),
        "recent_reviews": _recent_reviews(db),
        "swing_h1": prev.get("swing_h1"),
        "studies": _run_studies_snapshot(db),
        "assertiveness": _assertiveness(db),
        "research": _research_status(),
        "memory": _memory_status(),
    }
    write_intelligence_status(payload)
    logger.info(
        "intelligence pulse reviews=%s closed_usd=%s hv=%s",
        reviews_n,
        payload["n_closed_usd"],
        payload["learn"]["hv_dip"]["status"],
    )
    return payload
