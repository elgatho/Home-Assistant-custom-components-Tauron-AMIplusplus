"""Polling schedule aligned with the moments when Tauron publishes data (no Home Assistant dependencies)."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

WARSAW = ZoneInfo("Europe/Warsaw")
# Tauron finishes the overnight recalculation before 06:30; 14:30 is the afternoon synchronisation
SCHEDULED_TIMES = (time(6, 30), time(14, 30))
# Late retry, used only when yesterday's data is still incomplete after the 14:30 poll
RETRY_TIME = time(22, 30)


def next_update(now: datetime, yesterday_complete: bool) -> datetime:
    """Next poll time (timezone aware, Warsaw): 06:30, 14:30 and 22:30 only while yesterday is incomplete."""
    now = now.astimezone(WARSAW)
    times = SCHEDULED_TIMES if yesterday_complete else (*SCHEDULED_TIMES, RETRY_TIME)
    for day_offset in (0, 1):
        day = now.date() + timedelta(days=day_offset)
        for at in times:
            candidate = datetime.combine(day, at, tzinfo=WARSAW)
            if candidate > now:
                return candidate
    raise AssertionError("unreachable")
