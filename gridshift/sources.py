"""Build the half-hour slot table from public data sources."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .models import Slot
from .providers import (
    ProviderError,
    TariffConfig,
    demo_solar,
    fetch_agile,
    fetch_intensity,
    fetch_solar,
    price_at,
)
from .providers.base import Cache
from .providers.neso import gb_region

GB_TZ = "Europe/London"


def align_up(dt: datetime, step_min: int = 30) -> datetime:
    dt = dt.astimezone(timezone.utc).replace(second=0, microsecond=0)
    rem = dt.minute % step_min
    if rem:
        dt += timedelta(minutes=step_min - rem)
    return dt


def demo_carbon(dt: datetime) -> float:
    """A deterministic daily carbon curve for offline use."""
    import math

    hour = dt.hour + dt.minute / 60.0
    base = 150.0 + 70.0 * math.sin(((hour - 3.0) / 24.0) * 2.0 * math.pi)
    evening = 90.0 * math.exp(-(((hour - 19.0) ** 2) / 6.0))
    return max(30.0, base + evening)


def _lookup(rows: list[tuple], at: datetime) -> float | None:
    for row in rows:
        start, end, value = row[0], row[1], row[2]
        if start <= at < end:
            return value
    if not rows:
        return None
    nearest = min(rows, key=lambda row: abs((row[0] - at).total_seconds()))
    return nearest[2]


def _solar_at(series: dict[datetime, float] | None, at: datetime, lat: float) -> float:
    if series:
        hour = at.replace(minute=0, second=0, microsecond=0)
        if hour in series:
            return series[hour]
        nearest = min(series, key=lambda dt: abs((dt - at).total_seconds()))
        if abs((nearest - at).total_seconds()) <= 3600:
            return series[nearest]
    return demo_solar(at, lat)


def _cache_key(lat: float, lon: float, start: datetime, hours: float, step_min: int, source: str) -> str:
    return f"slots:{lat:.3f}:{lon:.3f}:{start.isoformat()}:{hours}:{step_min}:{source}"


def _serialise(slots: list[Slot], meta: dict) -> dict:
    return {
        "meta": meta,
        "slots": [
            {
                "start": s.start.isoformat(),
                "carbon_g_per_kwh": s.carbon_g_per_kwh,
                "price_per_kwh": s.price_per_kwh,
                "solar_kw_per_kwp": s.solar_kw_per_kwp,
                "duration_min": s.duration_min,
            }
            for s in slots
        ],
    }


def _deserialise(payload: dict) -> tuple[list[Slot], dict]:
    slots = [
        Slot(
            start=datetime.fromisoformat(item["start"]),
            carbon_g_per_kwh=float(item["carbon_g_per_kwh"]),
            price_per_kwh=float(item["price_per_kwh"]),
            solar_kw_per_kwp=float(item["solar_kw_per_kwp"]),
            duration_min=int(item["duration_min"]),
        )
        for item in payload["slots"]
    ]
    return slots, payload["meta"]


def build_slots(
    lat: float,
    lon: float,
    start: datetime | None = None,
    hours: float = 24.0,
    step_min: int = 30,
    source: str = "auto",
    tariff: TariffConfig | None = None,
    agile: tuple[str, str] | None = None,
    tz: str = GB_TZ,
    cache: Cache | None = None,
    use_cache: bool = True,
) -> tuple[list[Slot], dict]:
    """Return slots and a metadata dict that names each source."""
    start = align_up(start or datetime.now(timezone.utc), step_min)
    count = int((hours * 60) // step_min)
    times = [start + timedelta(minutes=step_min * i) for i in range(count)]
    end = start + timedelta(minutes=step_min * count)
    notes: list[str] = []

    key = _cache_key(lat, lon, start, hours, step_min, source)
    if cache and use_cache:
        hit = cache.get(key, max_age_s=900)
        if hit:
            slots, meta = _deserialise(hit)
            meta = dict(meta)
            meta["cached"] = True
            return slots, meta

    carbon_rows: list[tuple[datetime, datetime, float]] = []
    carbon_source = "demo curve"
    if source == "demo":
        notes.append("carbon: demo curve requested")
    elif gb_region(lat, lon):
        try:
            carbon_rows = fetch_intensity(start, end)
            carbon_source = "NESO Carbon Intensity API"
        except ProviderError as exc:
            notes.append(f"carbon: NESO failed ({exc}); used the demo curve")
    else:
        notes.append("carbon: outside Great Britain; used the demo curve")

    price_rows: list[tuple[datetime, datetime, float]] = []
    price_source = "time-of-use model"
    if source != "demo" and agile:
        try:
            price_rows = fetch_agile(start, end, product=agile[0], tariff=agile[1])
            price_source = f"Octopus Agile {agile[0]}"
        except ProviderError as exc:
            notes.append(f"price: Octopus failed ({exc}); used the time-of-use model")

    solar_series: dict[datetime, float] | None = None
    solar_source = "clear-sky model"
    if source != "demo":
        try:
            solar_series = fetch_solar(lat, lon)
            solar_source = "Open-Meteo shortwave radiation"
        except ProviderError as exc:
            notes.append(f"solar: Open-Meteo failed ({exc}); used the clear-sky model")

    slots: list[Slot] = []
    for at in times:
        carbon = _lookup(carbon_rows, at)
        if carbon is None:
            carbon = demo_carbon(at)
        price = _lookup(price_rows, at)
        if price is None:
            price = price_at(at, tariff, tz)
        irradiance = _solar_at(solar_series, at, lat)
        slots.append(
            Slot(
                start=at,
                carbon_g_per_kwh=float(carbon),
                price_per_kwh=float(price),
                solar_kw_per_kwp=max(0.0, irradiance / 1000.0 * 0.8),
                duration_min=step_min,
            )
        )

    meta = {
        "lat": lat,
        "lon": lon,
        "horizon_start": start.isoformat(),
        "horizon_end": end.isoformat(),
        "hours": hours,
        "step_min": step_min,
        "timezone": tz,
        "carbon_source": carbon_source,
        "price_source": price_source,
        "solar_source": solar_source,
        "notes": notes,
        "cached": False,
    }
    if cache and use_cache:
        cache.put(key, _serialise(slots, meta))
    return slots, meta


def postcode_lookup(postcode: str) -> tuple[float, float]:
    """Resolve a UK postcode with postcodes.io. Free and keyless."""
    from .providers.base import get_json

    payload = get_json(f"https://api.postcodes.io/postcodes/{postcode.strip()}")
    result = payload.get("result") or {}
    if "latitude" not in result:
        raise ProviderError(f"postcode not found: {postcode}")
    return float(result["latitude"]), float(result["longitude"])


def local_label(dt: datetime, tz: str = GB_TZ) -> str:
    return dt.astimezone(ZoneInfo(tz)).strftime("%a %H:%M")