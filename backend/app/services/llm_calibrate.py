"""Grade news LLM labels against what the price actually did (no gate change).

Two bugs made the old measurement meaningless, and both are fixed here:

- **Wrong horizon.** Outcomes were scored on the next session's close while
  ``hv_dip`` holds for up to ``hv_dip_max_hold_days`` (14). That is a swing
  exam marked with a day trade answer key. Returns are now recorded at 1, 5 and
  14 sessions, and the 14-session figure is the one that decides anything.
- **Neutral band too tight.** ``neutral`` only counted as correct when the move
  was under a flat 1%, on tickers selected *because* they are volatile. A third
  of all classifications failed by construction. The band is now a multiple of
  the ticker's own ATR, scaled by the square root of the horizon.

Raising the hit rate is not the point and would be trivial to fake by widening
the band. The summary therefore breaks results out by sentiment, so a gain that
comes only from easier ``neutral`` grading stays visible instead of hiding
inside the average.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.models import NewsEvent
from app.services.brapi_client import Bar

logger = logging.getLogger("fiidesk.llm_calibrate")

PROMPT_VERSION = "classify_v1"
# Bumped independently of the prompt: the same labels scored by a different
# ruler are not comparable, and old summaries must not look like regressions.
RULER_VERSION = "ruler_v2_multi_horizon_atr"

HORIZONS: tuple[int, ...] = (1, 5, 14)
# Matches hv_dip_max_hold_days: the horizon the strategy actually trades.
PRIMARY_HORIZON = 14
_ATR_WINDOW = 14
_MIN_BAND = 0.005

_CAL_PATH = Path(".cache/fiidesk/llm_calibration.json")


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _sorted_bars(bars: list[Bar]) -> list[tuple[Bar, datetime]]:
    dated = [
        (b, b.date if b.date.tzinfo else b.date.replace(tzinfo=timezone.utc))
        for b in bars
        if getattr(b, "date", None) is not None
    ]
    dated.sort(key=lambda x: x[1])
    return dated


def _split_at(bars: list[Bar], published_at: datetime) -> tuple[list[Bar], list[Bar]]:
    """Bars up to and including the publish day, and the bars strictly after it."""
    pub_day = published_at.date()
    before: list[Bar] = []
    after: list[Bar] = []
    for bar, dt in _sorted_bars(bars):
        (before if dt.date() <= pub_day else after).append(bar)
    return before, after


def forward_returns(
    bars: list[Bar],
    published_at: datetime | None,
    horizons: tuple[int, ...] = HORIZONS,
) -> dict[int, float | None]:
    """Close-to-close return at each horizon, anchored on the publish-day close.

    A horizon the history does not reach yields ``None`` rather than a partial
    return, so a two-day-old event is never scored as if 14 days had passed.
    """
    published_at = _as_utc(published_at)
    out: dict[int, float | None] = {h: None for h in horizons}
    if not bars or published_at is None:
        return out

    before, after = _split_at(bars, published_at)
    if not before:
        return out
    base = float(before[-1].close)
    if base <= 0:
        return out

    for h in horizons:
        if len(after) >= h:
            out[h] = (float(after[h - 1].close) - base) / base
    return out


def session_return_after(bars: list[Bar], published_at: datetime) -> float | None:
    """Next-session return. Kept for the 1-day slice of the ledger."""
    return forward_returns(bars, published_at, horizons=(1,))[1]


def atr_pct_at(
    bars: list[Bar],
    published_at: datetime | None,
    window: int = _ATR_WINDOW,
) -> float | None:
    """ATR as a fraction of price, using only bars available at publish time.

    Strictly backward-looking: a band computed from the move it is meant to
    judge would grade every event as unremarkable.
    """
    published_at = _as_utc(published_at)
    if published_at is None:
        return None
    before, _ = _split_at(bars, published_at)
    if len(before) < window + 1:
        return None

    trs: list[float] = []
    for prev, cur in zip(before[-(window + 1):-1], before[-window:]):
        prev_close = float(prev.close)
        high, low = float(cur.high), float(cur.low)
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    last_close = float(before[-1].close)
    if not trs or last_close <= 0:
        return None
    return (sum(trs) / len(trs)) / last_close


def neutral_band(atr_pct: float | None, horizon: int, mult: float | None = None) -> float:
    """How far price may drift before ``neutral`` counts as wrong.

    Scaled by ``sqrt(horizon)`` because dispersion grows with the square root of
    time, not linearly: reusing a one-day band over fourteen days would call
    every ordinary drift a missed call.
    """
    if mult is None:
        mult = float(get_settings().news_neutral_atr_mult or 0.5)
    if atr_pct is None or atr_pct <= 0:
        return max(_MIN_BAND, 0.01 * math.sqrt(max(1, horizon)))
    return max(_MIN_BAND, atr_pct * math.sqrt(max(1, horizon)) * mult)


def outcome_ok(
    sentiment: str | None,
    ret: float | None,
    *,
    band: float = 0.01,
) -> bool | None:
    """Did the label match the move? ``None`` when it cannot be judged yet."""
    if ret is None or not sentiment:
        return None
    if sentiment == "bullish":
        return ret > 0
    if sentiment == "bearish":
        return ret < 0
    return abs(ret) < band


def _empty_bucket() -> dict[str, Any]:
    return {"n": 0, "hits": 0, "brier_sum": 0.0, "brier_n": 0}


def _finish(bucket: dict[str, Any]) -> dict[str, Any]:
    n, bn = bucket["n"], bucket["brier_n"]
    return {
        "n": n,
        "hits": bucket["hits"],
        "hit_rate": round(bucket["hits"] / n, 4) if n else None,
        "brier": round(bucket["brier_sum"] / bn, 4) if bn else None,
    }


def _write_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-horizon and per-sentiment scores, so the ruler change stays auditable."""
    by_horizon: dict[int, dict[str, Any]] = {h: _empty_bucket() for h in HORIZONS}
    by_type: dict[str, dict[str, Any]] = {}
    by_sentiment: dict[str, dict[str, Any]] = {}

    for r in rows:
        conf = r.get("confidence")
        for h in HORIZONS:
            ok = r.get(f"outcome_ok_{h}d")
            if ok is None:
                continue
            bucket = by_horizon[h]
            bucket["n"] += 1
            bucket["hits"] += 1 if ok else 0
            if conf is not None:
                bucket["brier_sum"] += (float(conf) - (1.0 if ok else 0.0)) ** 2
                bucket["brier_n"] += 1

        primary = r.get(f"outcome_ok_{PRIMARY_HORIZON}d")
        if primary is None:
            continue
        for key, target in (
            (str(r.get("event_type") or "other"), by_type),
            (str(r.get("sentiment") or "unknown"), by_sentiment),
        ):
            bucket = target.setdefault(key, _empty_bucket())
            bucket["n"] += 1
            bucket["hits"] += 1 if primary else 0
            if conf is not None:
                bucket["brier_sum"] += (float(conf) - (1.0 if primary else 0.0)) ** 2
                bucket["brier_n"] += 1

    primary_stats = _finish(by_horizon[PRIMARY_HORIZON])
    summary = {
        "prompt_version": PROMPT_VERSION,
        "ruler_version": RULER_VERSION,
        "primary_horizon": PRIMARY_HORIZON,
        "n_labeled": primary_stats["n"],
        "hits": primary_stats["hits"],
        "hit_rate": primary_stats["hit_rate"],
        "brier": primary_stats["brier"],
        "by_horizon": {f"{h}d": _finish(by_horizon[h]) for h in HORIZONS},
        "by_event_type": {k: _finish(v) for k, v in by_type.items()},
        "by_sentiment": {k: _finish(v) for k, v in by_sentiment.items()},
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    _CAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CAL_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _row_view(ev: NewsEvent, raw: dict[str, Any]) -> dict[str, Any]:
    view = {
        "event_type": ev.event_type,
        "sentiment": ev.sentiment,
        "confidence": ev.confidence,
    }
    for h in HORIZONS:
        view[f"outcome_ok_{h}d"] = raw.get(f"outcome_ok_{h}d")
    return view


def _needs_label(raw: dict[str, Any]) -> bool:
    """Unfinished until the primary horizon lands.

    Shorter horizons are written as soon as they exist, so a row can be
    partially labelled and still come back on a later pass to gain its 5d and
    14d outcomes.
    """
    return raw.get(f"outcome_ret_{PRIMARY_HORIZON}d") is None


def calibrate_news_outcomes(
    db: Session,
    *,
    limit: int | None = None,
    scan_window: int = 4000,
) -> dict[str, Any]:
    """Backfill multi-horizon outcomes for classified events. Never touches the gate.

    Ordered newest-first on purpose. The previous version took the *oldest* 200
    events, which were the only ones ever labelled, so every subsequent run
    re-read the same finished rows and the backlog never moved: 6.5k classified
    against 202 labelled.
    """
    from app.services.market_data import MarketDataClient

    settings = get_settings()
    if limit is None:
        limit = int(settings.news_calibrate_batch or 400)

    # Eligible as soon as one session has passed. Waiting for the full 14-day
    # horizon before writing anything would leave the whole corpus unlabelled,
    # since every event currently on file is younger than three weeks.
    cutoff = datetime.now(timezone.utc) - timedelta(days=1.6)
    rows = (
        db.query(NewsEvent)
        .filter(NewsEvent.processed_at.is_not(None))
        .filter(NewsEvent.ticker.is_not(None))
        .order_by(NewsEvent.processed_at.desc())
        .limit(scan_window)
        .all()
    )

    client = MarketDataClient()
    bars_cache: dict[str, list[Bar]] = {}

    def bars_for(ticker: str) -> list[Bar]:
        if ticker not in bars_cache:
            try:
                bars_cache[ticker] = client.fetch_daily_bars(ticker)
            except Exception:
                logger.exception("llm_calibrate bars failed for %s", ticker)
                bars_cache[ticker] = []
        return bars_cache[ticker]

    seen: list[dict[str, Any]] = []
    written = 0
    for ev in rows:
        raw = dict(ev.raw or {})
        if not _needs_label(raw):
            seen.append(_row_view(ev, raw))
            continue
        if written >= limit:
            continue

        published = _as_utc(ev.published_at) or _as_utc(ev.processed_at)
        if published is None or published > cutoff:
            continue

        bars = bars_for(str(ev.ticker or "").upper())
        rets = forward_returns(bars, published)
        if all(v is None for v in rets.values()):
            continue

        atr = atr_pct_at(bars, published)
        gained = False
        for h in HORIZONS:
            ret = rets[h]
            if ret is None or raw.get(f"outcome_ret_{h}d") is not None:
                continue
            band = neutral_band(atr, h)
            raw[f"outcome_ret_{h}d"] = round(ret, 6)
            raw[f"outcome_neutral_band_{h}d"] = round(band, 6)
            raw[f"outcome_ok_{h}d"] = outcome_ok(ev.sentiment, ret, band=band)
            gained = True

        if not gained:
            # Re-scanned but nothing new matured; do not spend write budget on it.
            seen.append(_row_view(ev, raw))
            continue

        raw["outcome_atr_pct"] = None if atr is None else round(atr, 6)
        raw["ruler_version"] = RULER_VERSION
        # Legacy key still read by older dashboards; points at the longest
        # horizon that has actually landed rather than the next session.
        for h in reversed(HORIZONS):
            if raw.get(f"outcome_ok_{h}d") is not None:
                raw["outcome_ok"] = raw[f"outcome_ok_{h}d"]
                raw["outcome_horizon"] = h
                break
        ev.raw = raw
        written += 1
        seen.append(_row_view(ev, raw))

    summary = _write_summary(seen)
    summary["written"] = written
    summary["scanned"] = len(rows)
    db.flush()
    logger.info(
        "llm_calibrate written=%d labeled=%s hit_rate@%dd=%s brier=%s ruler=%s",
        written,
        summary.get("n_labeled"),
        PRIMARY_HORIZON,
        summary.get("hit_rate"),
        summary.get("brier"),
        RULER_VERSION,
    )
    return summary


__all__ = [
    "HORIZONS",
    "PRIMARY_HORIZON",
    "RULER_VERSION",
    "calibrate_news_outcomes",
    "forward_returns",
    "atr_pct_at",
    "neutral_band",
    "outcome_ok",
    "session_return_after",
]
