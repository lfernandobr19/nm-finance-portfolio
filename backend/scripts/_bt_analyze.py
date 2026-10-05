"""Rank the hv_dip backtest report by per-ticker edge and summarise exit mix."""

import json
import statistics
import sys
from pathlib import Path

path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/bt_full.json"
rep = json.loads(Path(path).read_text(encoding="utf-8"))
per = rep["per_ticker"]
trades = rep["trades"]

rows = []
for t, s in per.items():
    if not s.get("trades"):
        continue
    rows.append(
        (
            t,
            s["trades"],
            s["win_rate_pct"],
            s["avg_return_pct"],
            s["total_pnl_usd"],
            s.get("profit_factor"),
            s["max_drawdown_usd"],
        )
    )

rows.sort(key=lambda r: r[4])

print("=== WORST 15 (by total PnL) ===")
print(f"{'tkr':<6}{'n':>4}{'win%':>7}{'avg%':>8}{'pnl$':>9}{'PF':>7}{'maxDD$':>9}")
for r in rows[:15]:
    pf = f"{r[5]:.2f}" if r[5] is not None else "  na"
    print(f"{r[0]:<6}{r[1]:>4}{r[2]:>7.1f}{r[3]:>8.2f}{r[4]:>9.2f}{pf:>7}{r[6]:>9.2f}")

print("\n=== BEST 15 (by total PnL) ===")
for r in rows[-15:][::-1]:
    pf = f"{r[5]:.2f}" if r[5] is not None else "  na"
    print(f"{r[0]:<6}{r[1]:>4}{r[2]:>7.1f}{r[3]:>8.2f}{r[4]:>9.2f}{pf:>7}{r[6]:>9.2f}")

losers = [r for r in rows if r[4] < 0]
winners = [r for r in rows if r[4] >= 0]
print(
    f"\ntickers profitable={len(winners)} losing={len(losers)} "
    f"| loser drag=${sum(r[4] for r in losers):.2f} "
    f"| winner lift=${sum(r[4] for r in winners):.2f}"
)

# Exit-mix payoff asymmetry
print("\n=== EXIT MIX ===")
by = {}
for t in trades:
    by.setdefault(t["reason"], []).append(t["pnl_pct"])
tot = len(trades)
for reason, vals in sorted(by.items(), key=lambda kv: -len(kv[1])):
    print(
        f"{reason:<9} n={len(vals):>4} ({len(vals)/tot*100:>5.1f}%) "
        f"avg={statistics.fmean(vals):>7.2f}% median={statistics.median(vals):>7.2f}%"
    )

# What if the protect exit did not exist (hold to stop/target)? Proxy:
prot = by.get("protect", [])
stop = by.get("stop", [])
tgt = by.get("target", [])
print(
    f"\nprotect avg gain {statistics.fmean(prot):.2f}% vs stop avg loss "
    f"{statistics.fmean(stop):.2f}% -> payoff ratio "
    f"{abs(statistics.fmean(prot)/statistics.fmean(stop)):.2f}"
)

# Dip-bucket edge: does "deeper dip = better" actually hold?
print("\n=== EDGE BY DIP DEPTH (tests 'quanto maior a queda, maior a oportunidade') ===")
buckets = [(12, 15), (15, 18), (18, 22), (22, 28), (28, 100)]
for lo, hi in buckets:
    sel = [t for t in trades if lo <= t["dip_pct"] < hi]
    if not sel:
        continue
    pnls = [t["pnl_pct"] for t in sel]
    wins = len([p for p in pnls if p > 0])
    print(
        f"dip {lo:>3}-{hi:<3} n={len(sel):>4} win={wins/len(sel)*100:>5.1f}% "
        f"avg={statistics.fmean(pnls):>7.2f}% total=${sum(t['pnl_usd'] for t in sel):>8.2f}"
    )

# Hold-time distribution vs the 14-day review
print("\n=== HOLD DAYS ===")
hd = [t["hold_days"] for t in trades]
over14 = len([h for h in hd if h > 14])
print(
    f"median={statistics.median(hd):.0f} mean={statistics.fmean(hd):.1f} "
    f"p90={sorted(hd)[int(len(hd)*0.9)]} >14d={over14} ({over14/len(hd)*100:.1f}%)"
)
