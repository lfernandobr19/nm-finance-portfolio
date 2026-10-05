"""Watchdog: alert owners when the worker heartbeat goes stale.

Reads `.cache/fiidesk/worker_heartbeat.json` (written by the worker every cycle).
If `last_run_at` is older than `--stale-minutes` (default 15), send an FCM
`worker_down` notification. Re-notifies at most once per `--cooldown-minutes`
(default 30) to avoid spam. Intended to run from a systemd timer.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.db import SessionLocal
from app.domain.models import User
from app.services.notify import notify_worker_down

HEARTBEAT = Path(".cache/fiidesk/worker_heartbeat.json")
STATE = Path(".cache/fiidesk/watchdog_state.json")


def _last_heartbeat() -> datetime | None:
    if not HEARTBEAT.exists():
        return None
    try:
        data = json.loads(HEARTBEAT.read_text(encoding="utf-8"))
        raw = data.get("last_run_at")
        if not raw:
            return None
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stale-minutes", type=int, default=15)
    parser.add_argument("--cooldown-minutes", type=int, default=30)
    parser.add_argument("--no-notify", action="store_true", help="only print status")
    args = parser.parse_args()

    last = _last_heartbeat()
    now = datetime.now(timezone.utc)

    if last is None:
        print("WORKER_DOWN: no heartbeat file yet")
        stale = True
        age_min = None
    else:
        age_min = (now - last).total_seconds() / 60.0
        stale = age_min > args.stale_minutes
        print(
            f"heartbeat age={age_min:.1f}min stale={stale} "
            f"(threshold={args.stale_minutes}min)"
        )

    if not stale:
        return 0

    # Cooldown guard: don't re-notify within the cooldown window.
    if STATE.exists():
        try:
            prev = json.loads(STATE.read_text(encoding="utf-8"))
            last_alert = datetime.fromisoformat(prev.get("last_alert_at"))
            if last_alert.tzinfo is None:
                last_alert = last_alert.replace(tzinfo=timezone.utc)
            if (now - last_alert).total_seconds() < args.cooldown_minutes * 60:
                print("cooldown active; skipping re-notify")
                return 0
        except (OSError, ValueError, json.JSONDecodeError, KeyError):
            pass

    if args.no_notify:
        return 0

    db = SessionLocal()
    try:
        user_ids = [u.id for u in db.query(User).all()]
        if not user_ids:
            print("no users; skipping notify")
            return 0
        sent = notify_worker_down(
            db,
            user_ids=user_ids,
            stale_minutes=int(round(age_min)) if age_min is not None else args.stale_minutes,
        )
        db.commit()
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(
            json.dumps({"last_alert_at": now.isoformat()}),
            encoding="utf-8",
        )
        print(f"WORKER_DOWN notified {sent} device(s)")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
