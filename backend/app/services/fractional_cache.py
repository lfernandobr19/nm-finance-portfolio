"""Cache tickers where tastytrade sandbox blocks fractional orders."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger("fiidesk.fractional_cache")

_CACHE_NAME = "fractional_blocked.json"


def _path() -> Path:
    base = Path(get_settings().hv_dip_cache_dir)
    base.mkdir(parents=True, exist_ok=True)
    return base / _CACHE_NAME


def is_fractional_blocked(ticker: str) -> bool:
    p = _path()
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        blocked = {str(t).upper() for t in (data.get("tickers") or [])}
        return ticker.upper() in blocked
    except (OSError, json.JSONDecodeError):
        return False


def mark_fractional_blocked(ticker: str) -> None:
    p = _path()
    tickers: set[str] = set()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            tickers = {str(t).upper() for t in (data.get("tickers") or [])}
        except (OSError, json.JSONDecodeError):
            tickers = set()
    tickers.add(ticker.upper())
    p.write_text(json.dumps({"tickers": sorted(tickers)}), encoding="utf-8")
    logger.info("fractional blocked cache +%s", ticker.upper())
