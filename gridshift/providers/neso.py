"""NESO Carbon Intensity API client (Great Britain)."""

from __future__ import annotations

from datetime import datetime, timezone

from .base import ProviderError, get_json

BASE = "https://api.carbonintensity.org.uk"


def _fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def _parse_dt(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def parse_intensity(payload: dict) -> list[tuple[datetime, datetime, float, str | None]]:
    rows: list[tuple[datetime, datetime, float, str | None]] = []
    for item in payload.get("data", []):
        intensity = item.get("intensity") or {}
        value = intensity.get("actual")
        if value is None:
            value = intensity.get("forecast")
        if value is None:
            continue
        rows.append(
            (
                _parse_dt(item["from"]),
                _parse_dt(item["to"]),
                float(value),
                intensity.get("index"),
            )
        )
    if not rows:
        raise ProviderError("NESO response contained no intensity rows")
    return rows


def fetch_intensity(
    start: datetime,
    end: datetime,
    region_id: int | None = None,
) -> list[tuple[datetime, datetime, float, str | None]]:
    if region_id is None:
        url = f"{BASE}/intensity/{_fmt(start)}/{_fmt(end)}"
    else:
        url = f"{BASE}/regional/intensity/{_fmt(start)}/{_fmt(end)}/regionid/{region_id}"
    payload = get_json(url)
    if region_id is not None:
        payload = {"data": (payload.get("data") or {}).get("data", [])}
    return parse_intensity(payload)


def gb_region(lat: float, lon: float) -> bool:
    """Rough bounding box for Great Britain."""
    return 49.8 <= lat <= 60.9 and -8.2 <= lon <= 1.9