"""Portfolio-level Quick Target backtest: finite capital, equal-risk sizing, T+2.

The per-ticker backtest (`backtest_quick_target.py`) takes every signal with a
fixed notional, so it ranks configs by signal count as much as by edge. The real
desk has finite settled cash, whole-lot equal-risk sizing and ~0.5% slippage, so
total-PnL rankings there are misleading.

This walks the calendar day by day:

- **Equal-risk sizing**: qty = floor(risk_budget / (entry - stop)), risk_budget =
  settled_cash x risk_pct. Whole shares only.
- **T+2 settlement**: sell proceeds are un-spendable for `hv_dip_settlement_days`
  business days (anti-GFV), released back into settled cash on the due date.
- **Slots**: N concurrent ticker positions, filled by the production `rank`.
- **Exit**: intraday stop/target (OCO) then time-stop at the hold horizon.

Env knobs:
    BT_SLOTS          concurrent ticker slots (default 5)
    BT_CAPITAL        starting settled cash USD (default 100)
    BT_FLOOR_PCT      cash floor % of equity (default 20)
    BT_SLIPPAGE_PCT   per-side execution cost % (default 0.5)
    BT_RISK_PCT       per-trade risk budget % of settled cash (default 1.0)
    BT_PERIOD         full | h1 | h2 (walk-forward split, default full)

Run from backend/:
    .venv/bin/python scripts/_bt_portfolio.py
"""

from __future__ import annotations

import json
import os
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.services.market_data import MarketDataClient
from app.services.hv_dip.engine import build_hv_dip_setup
from app.services.hv_dip.exit_engine import add_business_days, compute_must_review_by
from app.services.hv_dip.universe import hv_dip_tickers

SLOTS = int(os.getenv("BT_SLOTS", "5"))
CAPITAL = float(os.getenv("BT_CAPITAL", "100"))
FLOOR_PCT = float(os.getenv("BT_FLOOR_PCT", "20"))
SLIP = float(os.getenv("BT_SLIPPAGE_PCT", "0.5")) / 100.0
RISK_PCT = float(os.getenv("BT_RISK_PCT", "1.0"))
DAYS = int(os.getenv("BT_DAYS", "500"))
PERIOD = os.getenv("BT_PERIOD", "full").lower()
WARMUP = 70


def _day(bar) -> datetime:
    d = getattr(bar, "date", None)
    if isinstance(d, datetime):
        dt = d
    elif d is not None:
        dt = datetime(d.year, d.month, d.day)
    else:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def main() -> int:
    settings = get_settings()
    settle_days = int(settings.hv_dip_settlement_days or 2)
    tickers = hv_dip_tickers()
    client = MarketDataClient()
    bars_map = client.fetch_daily_bars_many(tickers, days=DAYS)
    bars_map = {t: b for t, b in bars_map.items() if b and len(b) > WARMUP + 5}

    # Calendar union + per-ticker date->index for aligned walking.
    idx: dict[str, dict[datetime, int]] = {}
    calendar: set[datetime] = set()
    for t, bars in bars_map.items():
        m = {}
        for i, b in enumerate(bars):
            d = _day(b)
            m[d] = i
            if i >= WARMUP:
                calendar.add(d)
        idx[t] = m
    days = sorted(calendar)
    # Walk-forward split: only the *trading* calendar is sliced; every ticker
    # keeps its full bar history, so indicators in h2 are not truncated.
    if PERIOD == "h1":
        days = days[: len(days) // 2]
    elif PERIOD == "h2":
        days = days[len(days) // 2 :]

    settled = CAPITAL
    unsettled: list[tuple[datetime, float]] = []
    open_pos: dict[str, dict] = {}
    trades: list[dict] = []
    equity_curve: list[tuple[datetime, float]] = []
    skipped_no_cash = 0
    skipped_no_slot = 0

    for d in days:
        # ---- release T+2 proceeds ----
        due = [amt for rdate, amt in unsettled if rdate <= d]
        if due:
            settled += sum(due)
            unsettled = [(r, a) for r, a in unsettled if r > d]

        # ---- mark to market ----
        mv = 0.0
        for t, p in open_pos.items():
            i = idx[t].get(d)
            px = float(bars_map[t][i].close) if i is not None else p["last"]
            p["last"] = px
            mv += px * p["qty"]
        pending = sum(a for _r, a in unsettled)
        equity = settled + pending + mv
        equity_curve.append((d, equity))
        if equity <= 0:
            break

        # ---- exits (intraday stop/target, then time-stop) ----
        for t in list(open_pos):
            i = idx[t].get(d)
            if i is None:
                continue
            b = bars_map[t][i]
            p = open_pos[t]
            exit_px: float | None = None
            reason = "time_stop"
            if float(b.low) <= p["stop"]:
                exit_px, reason = p["stop"], "stop"
            elif float(b.high) >= p["target"]:
                exit_px, reason = p["target"], "target"
            elif d >= p["must_review_by"]:
                exit_px, reason = float(b.close), "time_stop"
            if exit_px is None:
                continue
            fill = exit_px * (1.0 - SLIP)
            proceeds = fill * p["qty"]
            unsettled.append((add_business_days(d, settle_days), proceeds))
            cost = p["entry"] * p["qty"]
            trades.append(
                {
                    "ticker": t,
                    "reason": reason,
                    "pnl_usd": round(proceeds - cost, 2),
                    "pnl_pct": round((fill - p["entry"]) / p["entry"] * 100.0, 2),
                    "dip_pct": p["dip_pct"],
                    "hold_days": (d - p["opened_at"]).days,
                    "notional": round(cost, 2),
                }
            )
            del open_pos[t]

        # ---- entries: all candidates compete for free slots by production rank ----
        free = SLOTS - len(open_pos)
        if free <= 0:
            continue
        cands = []
        for t, bars in bars_map.items():
            if t in open_pos:
                continue
            i = idx[t].get(d)
            if i is None or i < WARMUP:
                continue
            setup = build_hv_dip_setup(t, bars[: i + 1])
            if not setup or setup.get("review_required"):
                continue
            cands.append((setup["rank"], t, setup))
        if not cands:
            continue
        cands.sort(key=lambda c: -c[0])

        floor_cash = equity * FLOOR_PCT / 100.0
        for _rank, t, setup in cands:
            if free <= 0:
                skipped_no_slot += 1
                break
            deployable = max(0.0, settled - floor_cash)
            if deployable < 1.0:
                skipped_no_cash += 1
                continue

            # Equal-risk whole-lot sizing.
            entry = float(setup["entry"]) * (1.0 + SLIP)
            stop = float(setup["stop"])
            risk_per_share = max(entry - stop, 1e-6)
            risk_budget = settled * RISK_PCT / 100.0
            qty = int(risk_budget / risk_per_share)
            if qty < 1:
                continue
            cost = qty * entry
            if cost > deployable:
                qty = int(deployable / entry)
                if qty < 1:
                    skipped_no_cash += 1
                    continue
                cost = qty * entry
            settled -= cost
            open_pos[t] = {
                "entry": entry,
                "qty": qty,
                "stop": stop,
                "target": float(setup["target"]),
                "dip_pct": float(setup["dip_pct"]),
                "opened_at": d,
                "must_review_by": compute_must_review_by(d),
                "last": entry,
            }
            free -= 1

    # ---- report ----
    final = equity_curve[-1][1] if equity_curve else CAPITAL
    peak = 0.0
    max_dd_pct = 0.0
    for _d, e in equity_curve:
        peak = max(peak, e)
        if peak > 0:
            max_dd_pct = max(max_dd_pct, (peak - e) / peak * 100.0)
    span_days = (days[-1] - days[0]).days if len(days) > 1 else 1
    years = max(span_days / 365.25, 1e-9)
    cagr = ((final / CAPITAL) ** (1 / years) - 1) * 100 if final > 0 else -100.0

    pcts = [t["pnl_pct"] for t in trades]
    wins = [p for p in pcts if p > 0]
    gw = sum(t["pnl_usd"] for t in trades if t["pnl_usd"] > 0)
    gl = abs(sum(t["pnl_usd"] for t in trades if t["pnl_usd"] < 0))

    cfg = (
        f"qt_R={settings.hv_dip_qt_target_r} stop={settings.hv_dip_qt_stop_pct}% "
        f"hold={settings.hv_dip_qt_max_hold_days}d risk={RISK_PCT}% "
        f"slots={SLOTS} slip={SLIP*100:.2f}% floor={FLOOR_PCT}% period={PERIOD}"
    )
    out = {
        "config": cfg,
        "start_usd": round(CAPITAL, 2),
        "final_usd": round(final, 2),
        "return_pct": round((final / CAPITAL - 1) * 100, 2),
        "cagr_pct": round(cagr, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "trades": len(trades),
        "win_rate_pct": round(len(wins) / len(pcts) * 100, 1) if pcts else 0.0,
        "avg_return_pct": round(statistics.fmean(pcts), 2) if pcts else 0.0,
        "profit_factor": round(gw / gl, 2) if gl else None,
        "avg_hold_days": round(statistics.fmean([t["hold_days"] for t in trades]), 1)
        if trades
        else 0.0,
        "span_days": span_days,
        "signals_dropped_no_slot": skipped_no_slot,
        "signals_dropped_no_cash": skipped_no_cash,
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
