"""Registry of every hypothesis the desk has ever tested.

The Deflated Sharpe Ratio only deflates correctly when ``n_trials`` is the total
number of configurations searched, not the number searched in the current run.
A loop that tries 60 parameter combinations nightly and reports ``n_trials=60``
every night is claiming, each time, that it got lucky only once — while the true
count climbs into the thousands. Under that accounting a spurious winner is
guaranteed to eventually clear the bar.

This module keeps the running total on disk, keyed by family, so the count
survives restarts and accumulates the way the statistic assumes.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("fiidesk.learn.trials")

_TRIALS_PATH = Path(".cache/fiidesk/trial_registry.json")


def _load() -> dict[str, Any]:
    try:
        data = json.loads(_TRIALS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data: dict[str, Any]) -> None:
    _TRIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _TRIALS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def record_trials(family: str, count: int) -> int:
    """Add ``count`` tested configurations to ``family`` and return the new total."""
    if count <= 0:
        return trial_count(family)
    data = _load()
    entry = data.get(family) or {"n_trials": 0, "runs": 0}
    entry["n_trials"] = int(entry.get("n_trials", 0)) + int(count)
    entry["runs"] = int(entry.get("runs", 0)) + 1
    entry["last_run_trials"] = int(count)
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    data[family] = entry
    _save(data)
    return int(entry["n_trials"])


def trial_count(family: str) -> int:
    """Cumulative trials for a family, floored at 1 so DSR never divides by zero."""
    entry = _load().get(family) or {}
    return max(1, int(entry.get("n_trials", 0) or 0))


def all_counts() -> dict[str, int]:
    return {k: int((v or {}).get("n_trials", 0)) for k, v in _load().items()}


def load_all() -> dict[str, Any]:
    return _load()


def reset(family: str | None = None) -> None:
    """Clear the registry. Only for tests and deliberate re-baselining."""
    if family is None:
        _save({})
        return
    data = _load()
    data.pop(family, None)
    _save(data)


__all__ = ["record_trials", "trial_count", "all_counts", "load_all", "reset"]
