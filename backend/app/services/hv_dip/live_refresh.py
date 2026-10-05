"""Refresh pending hv_dip suggestions with live quotes during US session."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.models import StrategyKind, Suggestion, SuggestionStatus
from app.services.market_data import MarketDataClient
from app.services.hv_dip.engine import active_thresholds, build_hv_dip_setup
from app.services.hv_dip.indicators import dip_pct_from_high, is_52w_low, recent_low

logger = logging.getLogger("fiidesk.hv_dip.refresh")
settings = get_settings()


def recompute_live_dip(bars: list, last_price: float, lookback: int) -> float | None:
    """Recalculate dip_pct using last trade instead of daily close."""
    if not bars or last_price <= 0:
        return None
    from app.services.brapi_client import Bar

    last = bars[-1]
    patched = [
        *bars[:-1],
        Bar(
            date=last.date,
            open=last.open,
            high=max(last.high, last_price),
            low=min(last.low, last_price),
            close=last_price,
            volume=last.volume,
        ),
    ]
    return dip_pct_from_high(patched, lookback)


def _should_expire(
    *,
    dip_live: float | None,
    last_price: float,
    setup_low: float | None,
    bars: list,
    stale_streak: int,
) -> tuple[bool, str | None, int]:
    min_dip = float(settings.hv_dip_live_min_dip_pct or 6.0)
    if dip_live is None:
        return False, None, stale_streak

    if dip_live < min_dip:
        streak = stale_streak + 1
        if streak >= 2:
            return True, "dip_recovered_live", streak
        return False, None, streak

    if setup_low is not None and last_price < setup_low * 0.995 and not is_52w_low(bars):
        streak = stale_streak + 1
        if streak >= 2:
            return True, "structure_broken_live", streak
        return False, None, streak

    return False, None, 0


def refresh_pending_hv_dip_suggestions(db: Session) -> dict[str, int]:
    """Update or expire pending hv_dip suggestions using live quotes."""
    stats = {"updated": 0, "expired": 0, "skipped": 0, "errors": 0}
    pending = (
        db.query(Suggestion)
        .filter(
            Suggestion.strategy_kind == StrategyKind.hv_dip,
            Suggestion.status == SuggestionStatus.pending,
        )
        .all()
    )
    if not pending:
        return stats

    client = MarketDataClient()
    # Adopt the learn-loop quality thresholds, but keep this pass on its own dip
    # semantics: intraday revalidation deliberately runs a looser dip floor
    # (`hv_dip_live_min_dip_pct`, applied in `_should_expire`).
    quality_thresholds = {
        k: v for k, v in active_thresholds(db).items() if k != "min_dip_pct"
    }
    lookback = int(settings.hv_dip_lookback or 10)
    tickers = sorted({s.ticker.upper() for s in pending})
    live_prices = client.fetch_last_prices(tickers)
    now_iso = datetime.now(timezone.utc).isoformat()

    for sug in pending:
        ticker = sug.ticker.upper()
        last_price = live_prices.get(ticker)
        if last_price is None or last_price <= 0:
            stats["skipped"] += 1
            continue
        try:
            bars = client.fetch_daily_bars(ticker)
            if len(bars) < lookback + 5:
                stats["skipped"] += 1
                continue

            metrics = dict(sug.metrics or {})
            stale_streak = int(metrics.get("stale_streak") or 0)
            setup_low = sug.setup_low or metrics.get("setup_low")
            if setup_low is not None:
                setup_low = float(setup_low)

            dip_live = recompute_live_dip(bars, last_price, lookback)
            expire, reason, new_streak = _should_expire(
                dip_live=dip_live,
                last_price=last_price,
                setup_low=setup_low,
                bars=bars,
                stale_streak=stale_streak,
            )
            if expire and reason:
                metrics["invalidated_reason"] = reason
                metrics["dip_pct_live"] = round(dip_live, 2) if dip_live is not None else None
                metrics["live_price"] = round(last_price, 2)
                metrics["refreshed_at"] = now_iso
                sug.metrics = metrics
                sug.status = SuggestionStatus.expired
                stats["expired"] += 1
                logger.info("Expired %s (%s) dip_live=%s", ticker, reason, dip_live)
                continue

            row = build_hv_dip_setup(
                ticker, bars, last_price=last_price, **quality_thresholds
            )
            if not row:
                metrics["stale_streak"] = new_streak
                metrics["dip_pct_live"] = round(dip_live, 2) if dip_live is not None else None
                metrics["live_price"] = round(last_price, 2)
                metrics["refreshed_at"] = now_iso
                sug.metrics = metrics
                if new_streak >= 2:
                    metrics["invalidated_reason"] = "setup_invalid_live"
                    sug.status = SuggestionStatus.expired
                    stats["expired"] += 1
                else:
                    stats["skipped"] += 1
                continue

            scored = row["scored"]
            sug.entry_price = row["entry"]
            sug.stop_price = row["stop"]
            sug.target_price = row["target"]
            sug.r_multiple = scored.r_multiple
            sug.score = scored.numeric_score
            sug.swing_score_letter = scored.letter
            sug.reasons = scored.reasons
            sug.review_required = bool(row["review_required"])
            sug.review_reason = row.get("review_reason")
            if row.get("setup_low") is not None:
                sug.setup_low = row["setup_low"]
            metrics.update(
                {
                    "price": row["entry"],
                    "entry": row["entry"],
                    "stop": row["stop"],
                    "target": row["target"],
                    "setup_low": row["setup_low"],
                    "dip_pct": row["dip_pct"],
                    "dip_pct_live": round(dip_live, 2) if dip_live is not None else row["dip_pct"],
                    "live_price": round(last_price, 2),
                    "entry_at_refresh": row["entry"],
                    "refreshed_at": now_iso,
                    "stale_streak": 0,
                    "atr_pct": row["atr_pct"],
                    "volume_ratio": row["volume_ratio"],
                    "weekly_range_pct": row.get("weekly_range_pct"),
                    "score_letter": scored.letter,
                    "r_multiple": scored.r_multiple,
                }
            )
            sug.metrics = metrics
            sug.price_explanation = (
                f"NM High-Vol {scored.letter}: dip {row['dip_pct']:.1f}% "
                f"(vivo {metrics['dip_pct_live']:.1f}%) "
                f"entrada {row['entry']:.2f} stop {row['stop']:.2f} "
                f"alvo {row['target']:.2f} tranche {sug.tranche_index or 1}"
                + (" [REVIEW]" if row["review_required"] else "")
            )
            stats["updated"] += 1
        except Exception:
            stats["errors"] += 1
            logger.exception("Refresh failed for %s", ticker)

    if stats["updated"] or stats["expired"]:
        db.flush()
    return stats
