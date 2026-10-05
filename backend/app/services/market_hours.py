"""US/B3 market session helpers (mirrors app/lib/core/market_hours.dart)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone


@dataclass(frozen=True)
class MarketSession:
    id: str
    name: str
    is_open: bool
    status_label: str


def _us_eastern_offset_hours(utc: datetime) -> int:
    year = utc.year

    def nth_weekday(month: int, weekday: int, nth: int) -> datetime:
        d = datetime(year, month, 1, tzinfo=timezone.utc)
        count = 0
        while d.month == month:
            if d.weekday() == weekday:
                count += 1
                if count == nth:
                    return d
            d += timedelta(days=1)
        return datetime(year, month, 1, tzinfo=timezone.utc)

    dst_start = nth_weekday(3, 6, 2)  # 2nd Sunday March
    dst_end = nth_weekday(11, 6, 1)  # 1st Sunday November
    in_dst = dst_start <= utc < dst_end
    return -4 if in_dst else -5


def now_us_eastern(utc: datetime | None = None) -> datetime:
    utc = utc or datetime.now(timezone.utc)
    return utc + timedelta(hours=_us_eastern_offset_hours(utc))


def us_session_open(utc: datetime | None = None) -> bool:
    et = now_us_eastern(utc)
    if et.weekday() >= 5:
        return False
    minutes = et.hour * 60 + et.minute
    open_m = 9 * 60 + 30
    close_m = 16 * 60
    return open_m <= minutes < close_m


def us_session_date(utc: datetime | None = None) -> date:
    return now_us_eastern(utc).date()


def us_market_session(utc: datetime | None = None) -> MarketSession:
    open_ = us_session_open(utc)
    return MarketSession(
        id="us",
        name="Nasdaq / NYSE",
        is_open=open_,
        status_label="Aberto" if open_ else "Fechado",
    )
