"""Bar-replay bootstrap for hv_dip: turn 2y of daily OHLC into synthetic trades.

The live learn loop starves because closed paper positions are rare (the
walk-forward floor is 30). Replay walks history with the same entry and exit
functions the engine uses, so the optimizer can *explore* parameter space
before real trades exist.

Two invariants:

- **No look-ahead.** ``build_hv_dip_setup`` is called on ``bars[:i+1]`` only.
  The entry bar never sees a future close.
- **Synthetic never promotes.** Trades are tagged ``synthetic=True``. Production
  activation still requires a real (paper counts) sample.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.brapi_client import Bar
from app.services.hv_dip.engine import build_hv_dip_setup
from app.services.hv_dip.exit_engine import (
    add_business_days,
    evaluate_hv_dip_exit,
    init_hv_dip_position_metrics,
)
from app.services.hv_dip.universe import hv_dip_tickers

logger = logging.getLogger("fiidesk.hv_dip.replay")

_CACHE = Path(".cache/fiidesk/hv_dip_replay.json")


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _bar_dt(bar: Bar) -> datetime:
    dt = _as_utc(getattr(bar, "date", None))
    if dt is None:
        raise ValueError("bar missing date")
    return dt


def simulate_exit(
    *,
    entry: float,
    stop: float,
    target: float,
    opened_at: datetime,
    future: list[Bar],
    max_hold_days: int | None = None,
) -> dict[str, Any] | None:
    """Resolve a position against subsequent bars. Stop wins on the same bar."""
    settings = get_settings()
    hold = int(max_hold_days if max_hold_days is not None else settings.hv_dip_qt_max_hold_days or 3)
    opened_at = _as_utc(opened_at) or datetime.now(timezone.utc)
    deadline = add_business_days(opened_at, hold)
    metrics = init_hv_dip_position_metrics({}, must_review_by=deadline)
    risk = max(entry - stop, 1e-6)

    for bar in future:
        now = _bar_dt(bar)
        low, high, close = float(bar.low), float(bar.high), float(bar.close)

        # Conservative: if the bar spans both levels, assume the stop filled.
        if low <= stop:
            ev = evaluate_hv_dip_exit(
                metrics,
                upnl_pct=(stop - entry) / entry * 100.0,
                mark=stop,
                entry=entry,
                stop=stop,
                target=target,
                opened_at=opened_at,
                now=now,
                time_stop=True,
            )
            if ev.auto_close:
                return {
                    "exit": stop,
                    "exit_reason": ev.exit_state,
                    "closed_at": now,
                    "r": (stop - entry) / risk,
                    "bars_held": 1 + future.index(bar),
                }

        if high >= target:
            ev = evaluate_hv_dip_exit(
                metrics,
                upnl_pct=(target - entry) / entry * 100.0,
                mark=target,
                entry=entry,
                stop=stop,
                target=target,
                opened_at=opened_at,
                now=now,
                time_stop=True,
            )
            if ev.auto_close:
                return {
                    "exit": target,
                    "exit_reason": ev.exit_state,
                    "closed_at": now,
                    "r": (target - entry) / risk,
                    "bars_held": 1 + future.index(bar),
                }

        ev = evaluate_hv_dip_exit(
            metrics,
            upnl_pct=(close - entry) / entry * 100.0,
            mark=close,
            entry=entry,
            stop=stop,
            target=target,
            opened_at=opened_at,
            now=now,
            time_stop=True,
        )
        metrics = ev.metrics
        if ev.auto_close:
            return {
                "exit": close,
                "exit_reason": ev.exit_state,
                "closed_at": now,
                "r": (close - entry) / risk,
                "bars_held": 1 + future.index(bar),
            }
    return None


def replay_bars(
    ticker: str,
    bars: list[Bar],
    *,
    setup_fn: Callable[..., dict | None] = build_hv_dip_setup,
    min_history: int = 45,
    skip_review: bool = True,
    **setup_kwargs: Any,
) -> list[dict[str, Any]]:
    """Walk ``bars`` left-to-right and emit synthetic trades.

    A position blocks re-entry until it exits. Review-required setups are
    skipped by default — they would not have auto-bought.
    """
    trades: list[dict[str, Any]] = []
    i = max(min_history, 40)
    while i < len(bars) - 1:
        window = bars[: i + 1]
        setup = setup_fn(ticker, window, **setup_kwargs)
        if setup is None or (skip_review and setup.get("review_required")):
            i += 1
            continue

        entry = float(setup["entry"])
        stop = float(setup["stop"])
        target = float(setup["target"])
        opened_at = _bar_dt(bars[i])
        resolved = simulate_exit(
            entry=entry,
            stop=stop,
            target=target,
            opened_at=opened_at,
            future=bars[i + 1 :],
        )
        if resolved is None:
            i += 1
            continue

        trades.append(
            {
                "ticker": ticker.upper(),
                "closed_at": resolved["closed_at"],
                "opened_at": opened_at,
                "entry": entry,
                "stop": stop,
                "target": target,
                "exit": resolved["exit"],
                "exit_reason": resolved["exit_reason"],
                "r": float(resolved["r"]),
                "dip_pct": setup.get("dip_pct"),
                "recovery_rate": setup.get("recovery_rate"),
                "quality_tier": setup.get("quality_tier") or "mid",
                "is_fresh_high": bool(setup.get("is_fresh_high")),
                "synthetic": True,
                "bars_held": resolved["bars_held"],
            }
        )
        # Jump to the exit bar so overlapping positions cannot form.
        held = int(resolved["bars_held"])
        i += max(1, held)
    return trades


def replay_universe(
    db: Session | None = None,
    *,
    tickers: list[str] | None = None,
    days: int = 400,
    persist: bool = True,
) -> list[dict[str, Any]]:
    """Replay the hv_dip universe from cached/Yahoo daily bars."""
    from app.services.market_data import MarketDataClient

    names = [t.upper() for t in (tickers or hv_dip_tickers())]
    client = MarketDataClient()
    trades: list[dict[str, Any]] = []
    for ticker in names:
        try:
            bars = client.fetch_daily_bars(ticker, days=days)
        except Exception:
            logger.exception("hv_dip replay fetch failed for %s", ticker)
            continue
        if len(bars) < 50:
            continue
        trades.extend(replay_bars(ticker, bars))
    trades.sort(key=lambda t: t["closed_at"])
    if persist:
        save_replay(trades)
    logger.info("hv_dip replay n=%d tickers=%d", len(trades), len(names))
    return trades


def save_replay(trades: list[dict[str, Any]]) -> None:
    _CACHE.parent.mkdir(parents=True, exist_ok=True)
    serializable: list[dict[str, Any]] = []
    for t in trades:
        row = dict(t)
        for key in ("closed_at", "opened_at"):
            val = row.get(key)
            if isinstance(val, datetime):
                row[key] = val.isoformat()
        serializable.append(row)
    _CACHE.write_text(json.dumps(serializable, indent=2, default=str), encoding="utf-8")


def load_cached_replay() -> list[dict[str, Any]]:
    try:
        raw = json.loads(_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict) or row.get("r") is None:
            continue
        item = dict(row)
        item["synthetic"] = True
        for key in ("closed_at", "opened_at"):
            val = item.get(key)
            if isinstance(val, str):
                try:
                    item[key] = datetime.fromisoformat(val.replace("Z", "+00:00"))
                except ValueError:
                    pass
        out.append(item)
    out.sort(key=lambda t: t.get("closed_at") or datetime.min.replace(tzinfo=timezone.utc))
    return out


__all__ = [
    "replay_bars",
    "replay_universe",
    "simulate_exit",
    "save_replay",
    "load_cached_replay",
]
