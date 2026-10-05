"""Offline replay of intraday bars through day trade rules."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.day_trade.bars import IntradayBar
from app.services.day_trade.rules import RULE_EVALUATORS


def _load_csv(path: Path) -> list[IntradayBar]:
    bars: list[IntradayBar] = []
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = datetime.fromisoformat(row["ts"].replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            bars.append(
                IntradayBar(
                    ts=ts,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume") or 0),
                )
            )
    return sorted(bars, key=lambda b: b.ts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay CSV bars through DT rules")
    parser.add_argument("csv_path", type=Path)
    args = parser.parse_args()
    bars = _load_csv(args.csv_path)
    hits = []
    for i in range(4, len(bars) + 1):
        window = bars[:i]
        for evaluate in RULE_EVALUATORS:
            signal = evaluate(window)
            if signal:
                hits.append(
                    {
                        "ts": window[-1].ts.isoformat(),
                        "rule_id": signal.rule_id,
                        "side": signal.side,
                        "entry": signal.entry_price,
                        "stop": signal.stop_price,
                        "target": signal.target_price,
                    }
                )
    print(json.dumps(hits, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
