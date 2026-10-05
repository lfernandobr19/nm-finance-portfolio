"""Performance analytics for closed day trade signals.

Pure-Python (no numpy) with Wilson win-rate intervals and bootstrap expectancy
intervals so the system can distinguish real edge from small-sample noise.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import DayTradeSignal, DayTradeSignalStatus

Z = 1.96  # 95% confidence


def _r_multiple(sig: DayTradeSignal) -> float | None:
    risk = abs(float(sig.entry_price) - float(sig.stop_price))
    pnl = sig.simulated_pnl_usd
    if risk <= 0 or pnl is None:
        return None
    return float(pnl) / risk


def wilson_interval(wins: int, n: int, z: float = Z) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = wins / n
    z2 = z * z
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    margin = z * math.sqrt((p * (1 - p) + z2 / (4 * n)) / n) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def _bootstrap_mean_ci(
    values: list[float],
    n_boot: int = 1000,
    seed: int = 42,
    alpha: float = 0.05,
) -> tuple[float, float, float] | None:
    if not values:
        return None
    mean = sum(values) / len(values)
    if len(values) < 5:
        return (mean, mean, mean)
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(n_boot):
        sample = [values[rng.randrange(len(values))] for _ in range(len(values))]
        means.append(sum(sample) / len(sample))
    means.sort()
    lo = means[int(alpha / 2 * len(means))]
    hi = means[int((1 - alpha / 2) * len(means))]
    return (mean, lo, hi)


@dataclass
class GroupStat:
    key: str
    n: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    win_rate_lo: float = 0.0
    win_rate_hi: float = 0.0
    expectancy_r: float | None = None
    expectancy_r_lo: float | None = None
    expectancy_r_hi: float | None = None
    profit_factor: float | None = None
    avg_hold_minutes: float | None = None
    total_pnl: float = 0.0
    total_r: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "n": self.n,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.win_rate * 100, 1),
            "win_rate_lo": round(self.win_rate_lo * 100, 1),
            "win_rate_hi": round(self.win_rate_hi * 100, 1),
            "expectancy_r": round(self.expectancy_r, 3) if self.expectancy_r is not None else None,
            "expectancy_r_lo": round(self.expectancy_r_lo, 3) if self.expectancy_r_lo is not None else None,
            "expectancy_r_hi": round(self.expectancy_r_hi, 3) if self.expectancy_r_hi is not None else None,
            "profit_factor": round(self.profit_factor, 2) if self.profit_factor is not None else None,
            "avg_hold_minutes": round(self.avg_hold_minutes, 0) if self.avg_hold_minutes is not None else None,
            "total_pnl": round(self.total_pnl, 4),
            "total_r": round(self.total_r, 3),
        }


def _group_stats(rows: list[DayTradeSignal], key_fn) -> list[GroupStat]:
    buckets: dict[str, list[DayTradeSignal]] = {}
    for sig in rows:
        buckets.setdefault(key_fn(sig), []).append(sig)

    out: list[GroupStat] = []
    for key in sorted(buckets):
        sigs = buckets[key]
        n = len(sigs)
        wins = sum(1 for s in sigs if (s.simulated_pnl_usd or 0) > 0)
        losses = sum(1 for s in sigs if (s.simulated_pnl_usd or 0) <= 0)
        wr_lo, wr_hi = wilson_interval(wins, n)
        rs = [r for r in (_r_multiple(s) for s in sigs) if r is not None]
        exp_boot = _bootstrap_mean_ci(rs)
        gross_win = sum(max(float(s.simulated_pnl_usd or 0), 0) for s in sigs)
        gross_loss = sum(abs(min(float(s.simulated_pnl_usd or 0), 0)) for s in sigs)
        pf = (gross_win / gross_loss) if gross_loss > 0 else None
        holds = []
        for s in sigs:
            if s.closed_at is not None and s.created_at is not None:
                holds.append((s.closed_at - s.created_at).total_seconds() / 60.0)
        avg_hold = (sum(holds) / len(holds)) if holds else None
        stat = GroupStat(
            key=key,
            n=n,
            wins=wins,
            losses=losses,
            win_rate=wins / n if n else 0.0,
            win_rate_lo=wr_lo,
            win_rate_hi=wr_hi,
            expectancy_r=exp_boot[0] if exp_boot else None,
            expectancy_r_lo=exp_boot[1] if exp_boot else None,
            expectancy_r_hi=exp_boot[2] if exp_boot else None,
            profit_factor=pf,
            avg_hold_minutes=avg_hold,
            total_pnl=sum(float(s.simulated_pnl_usd or 0) for s in sigs),
            total_r=sum(rs) if rs else 0.0,
        )
        out.append(stat)
    return out


def closed_signals(
    db: Session, account_id: str | None = None
) -> list[DayTradeSignal]:
    stmt = select(DayTradeSignal).where(
        DayTradeSignal.status == DayTradeSignalStatus.closed,
    )
    if account_id:
        stmt = stmt.where(DayTradeSignal.account_id == account_id)
    rows = db.execute(stmt.order_by(DayTradeSignal.created_at.asc())).scalars().all()
    return list(rows)


def analytics_summary(db: Session, account_id: str) -> dict[str, Any]:
    rows = closed_signals(db, account_id)
    by_rule = _group_stats(rows, lambda s: s.rule_id)
    by_ticker = _group_stats(rows, lambda s: s.ticker)
    by_side = _group_stats(rows, lambda s: str(s.side.value if hasattr(s.side, "value") else s.side))
    return {
        "total_closed": len(rows),
        "by_rule": [g.as_dict() for g in by_rule],
        "by_ticker": [g.as_dict() for g in by_ticker],
        "by_side": [g.as_dict() for g in by_side],
    }


__all__ = [
    "GroupStat",
    "wilson_interval",
    "closed_signals",
    "analytics_summary",
]
