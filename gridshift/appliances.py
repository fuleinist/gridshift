"""Default flexible loads for a typical home."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .models import Load
from .sources import GB_TZ


def window(
    start: datetime,
    tz: str,
    start_hh: int,
    start_mm: int,
    end_hh: int,
    end_mm: int,
) -> tuple[datetime, datetime]:
    """Resolve a clock-time window that starts after the horizon start."""
    local = start.astimezone(ZoneInfo(tz))
    ws = local.replace(hour=start_hh, minute=start_mm, second=0, microsecond=0)
    we = local.replace(hour=end_hh, minute=end_mm, second=0, microsecond=0)
    if we <= ws:
        we += timedelta(days=1)
    while we <= local:
        ws += timedelta(days=1)
        we += timedelta(days=1)
    return ws, we


def default_loads(start: datetime, tz: str = GB_TZ, include_ev: bool = True) -> list[Load]:
    loads = [
        Load(
            name="dishwasher",
            power_kw=1.2,
            duration_min=105,
            window_start=window(start, tz, 17, 0, 23, 30)[0],
            window_end=window(start, tz, 17, 0, 23, 30)[1],
            priority=2,
        ),
        Load(
            name="washing_machine",
            power_kw=0.9,
            duration_min=90,
            window_start=window(start, tz, 8, 0, 22, 0)[0],
            window_end=window(start, tz, 8, 0, 22, 0)[1],
            priority=2,
        ),
        Load(
            name="tumble_dryer",
            power_kw=2.5,
            duration_min=60,
            window_start=window(start, tz, 9, 0, 22, 0)[0],
            window_end=window(start, tz, 9, 0, 22, 0)[1],
            priority=1,
        ),
        Load(
            name="hot_water",
            power_kw=2.0,
            duration_min=120,
            window_start=window(start, tz, 21, 0, 6, 0)[0],
            window_end=window(start, tz, 21, 0, 6, 0)[1],
            priority=2,
        ),
    ]
    if include_ev:
        loads.append(
            Load(
                name="ev_charger",
                power_kw=7.4,
                duration_min=150,
                window_start=window(start, tz, 18, 0, 6, 30)[0],
                window_end=window(start, tz, 18, 0, 6, 30)[1],
                priority=3,
            )
        )
    return loads