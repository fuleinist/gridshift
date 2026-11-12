"""Open-Meteo solar forecast and a deterministic offline fallback."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from .base import ProviderError, get_json

BASE = "https://api.open-meteo.com/v1/forecast"


def parse_solar(payload: dict) -> dict[datetime, float]:
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    values = hourly.get("shortwave_radiation") or []
    out: dict[datetime, float] = {}
    for stamp, value in zip(times, values):
        if value is None:
            continue
        dt = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)
        out[dt] = float(value)
    if not out:
        raise ProviderError("Open-Meteo returned no solar values")
    return out


def fetch_solar(lat: float, lon: float, days: int = 2) -> dict[datetime, float]:
    payload = get_json(
        BASE,
        params={
            "latitude": lat,
            "longitude": lon,
            "hourly": "shortwave_radiation",
            "forecast_days": days,
            "timezone": "UTC",
        },
    )
    return parse_solar(payload)


def demo_solar(dt: datetime, lat: float = 51.5) -> float:
    """Clear-sky style curve in W/m2. Used when the API is unavailable."""
    hour = dt.hour + dt.minute / 60.0
    day_length = 12.0
    sunrise = 12.0 - day_length / 2
    x = (hour - sunrise) / day_length
    if x <= 0 or x >= 1:
        return 0.0
    peak = 850.0 if abs(lat) < 35 else 700.0
    return max(0.0, peak * math.sin(math.pi * x))