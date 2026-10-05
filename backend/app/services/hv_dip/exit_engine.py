"""Quick-Target exit state machine: hard stop + small target + time-stop.

Replaces the old hv_dip exits (2R/50% target, LATCHED +5%, trailing PROTECT
with 20–50% giveback, 14-day time review). The new thesis is a short, high-
probability swing:

- **stop**   = `entry × (1 − stop_pct/100)` — hard, protects capital.
- **target** = `entry + target_R × (entry − stop)` — small, positive, quick.
- **time-stop** = `max_hold_days` business days — market sell on expiry.

The target/stop prices are set at entry (`quick_target_prices`) and the exit
evaluation only compares the mark against them, plus the time-stop deadline.
Trailing giveback is gone: the broker-side OCO bracket owns stop/target, and
the poll here is a fallback + the time-stop leg.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import get_settings


@dataclass
class ExitEvaluation:
    """Result of evaluating one open position against exit rules."""

    metrics: dict[str, Any] = field(default_factory=dict)
    price_alert: str | None = None
    exit_state: str = "normal"
    auto_close: bool = False
    notify: bool = False
    peak_unrealized_pct: float = 0.0


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def quick_target_prices(
    entry: float,
    *,
    target_r: float | None = None,
    stop_pct: float | None = None,
) -> tuple[float, float]:
    """Compute (stop, target) for the quick-target thesis from an entry price.

    stop   = entry × (1 − stop_pct/100)
    target = entry + target_R × (entry − stop)
    """
    settings = get_settings()
    tr = float(target_r if target_r is not None else settings.hv_dip_qt_target_r)
    sp = float(stop_pct if stop_pct is not None else settings.hv_dip_qt_stop_pct)
    stop = round(entry * (1.0 - sp / 100.0), 2)
    risk = max(entry - stop, 1e-6)
    target = round(entry + tr * risk, 2)
    return stop, target


def add_business_days(dt: datetime, days: int) -> datetime:
    """Add ``days`` US business days to a datetime (weekends skipped)."""
    d = dt
    added = 0
    while added < days:
        d += timedelta(days=1)
        if d.weekday() < 5:  # Monday..Friday
            added += 1
    return d


def exit_state_from_metrics(metrics: dict[str, Any]) -> str:
    if metrics.get("time_stop_triggered"):
        return "time_stop"
    return "normal"


def days_until_review(metrics: dict[str, Any], *, now: datetime | None = None) -> int | None:
    """Days until the time-stop deadline (``must_review_by``)."""
    now = now or datetime.now(timezone.utc)
    deadline = _parse_iso(metrics.get("time_review_extended_until")) or _parse_iso(
        metrics.get("must_review_by")
    )
    if deadline is None:
        return None
    return (deadline.date() - now.date()).days


def evaluate_hv_dip_exit(
    metrics: dict[str, Any],
    *,
    upnl_pct: float,
    mark: float,
    entry: float,
    stop: float | None,
    target: float | None,
    opened_at: datetime,
    now: datetime | None = None,
    recovery_high: float | None = None,
    days_since_recent_high: int | None = None,
    time_stop: bool | None = None,
) -> ExitEvaluation:
    """Evaluate a position against the quick-target exit rules.

    Order of checks: hard stop → hard target → time-stop. The first trigger wins.
    Trailing giveback/latch/protect are intentionally removed — the broker OCO
    bracket owns stop/target, this poll is the fallback + the time-stop leg.

    ``time_stop`` (the frozen calendar deadline) is off by default
    (``hv_dip_qt_time_stop_enabled``): the desk holds on price action and
    thesis, and decides itself how long to wait. Replay/backtests pass
    ``time_stop=True`` to keep exploring that leg historically.
    """
    settings = get_settings()
    if time_stop is None:
        time_stop = bool(getattr(settings, "hv_dip_qt_time_stop_enabled", False))
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    m = dict(metrics or {})

    # Peak tracked for observability only (no trailing giveback anymore).
    stored_peak = m.get("peak_unrealized_pct")
    peak = float(stored_peak) if stored_peak is not None else upnl_pct
    if upnl_pct > peak:
        peak = upnl_pct
        m["peak_unrealized_pct"] = peak

    result = ExitEvaluation(metrics=m, peak_unrealized_pct=peak)

    # Hard stop — protect capital.
    if stop is not None and mark <= float(stop):
        result.price_alert = "stop"
        result.auto_close = True
        result.exit_state = "stop"
        return result

    # Hard target — take the small, quick win.
    if target is not None and mark >= float(target):
        result.price_alert = "target"
        result.auto_close = True
        result.exit_state = "target"
        return result

    # Time-stop — market sell at the hold horizon (never same-day; 1–3 pregões).
    if time_stop:
        deadline = _parse_iso(m.get("time_review_extended_until")) or _parse_iso(
            m.get("must_review_by")
        )
        if deadline is not None and now >= deadline and not m.get("time_stop_triggered"):
            result.price_alert = "time_stop"
            result.auto_close = True
            result.exit_state = "time_stop"
            result.notify = True
            m["time_stop_triggered"] = True

    result.metrics = m
    return result


def init_hv_dip_position_metrics(
    existing_metrics: dict[str, Any] | None,
    *,
    must_review_by: datetime,
) -> dict[str, Any]:
    m = dict(existing_metrics or {})
    if not m.get("must_review_by"):
        m["must_review_by"] = _iso(must_review_by)
    return m


def compute_must_review_by(first_opened_at: datetime) -> datetime:
    """Time-stop deadline: `hv_dip_qt_max_hold_days` business days after open."""
    settings = get_settings()
    days = int(settings.hv_dip_qt_max_hold_days or 3)
    if first_opened_at.tzinfo is None:
        first_opened_at = first_opened_at.replace(tzinfo=timezone.utc)
    return add_business_days(first_opened_at, days)


def extend_time_review(metrics: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """One-time +N business-day extension of the time-stop deadline."""
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    m = dict(metrics or {})
    if m.get("time_review_extended_until"):
        raise ValueError("Extensão de review já utilizada")
    base = _parse_iso(m.get("must_review_by")) or now
    extra = int(settings.hv_dip_review_extension_days or 3)
    m["time_review_extended_until"] = _iso(add_business_days(base, extra))
    m["time_stop_triggered"] = False
    return m
