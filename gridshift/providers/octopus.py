"""Octopus Energy Agile public unit rates. No API key is needed."""

from __future__ import annotations

from datetime import datetime, timezone

from .base import ProviderError, get_json

BASE = "https://api.octopus.energy/v1"
DEFAULT_PRODUCT = "AGILE-24-10-01"
DEFAULT_TARIFF = "E-1R-AGILE-24-10-01-C"


def parse_rates(payload: dict) -> list[tuple[datetime, datetime, float]]:
    rows: list[tuple[datetime, datetime, float]] = []
    for item in payload.get("results", []):
        value = item.get("value_inc_vat")
        if value is None:
            continue
        rows.append(
            (
                datetime.fromisoformat(item["valid_from"].replace("Z", "+00:00")),
                datetime.fromisoformat(item["valid_to"].replace("Z", "+00:00")),
                float(value) / 100.0,
            )
        )
    rows.sort(key=lambda row: row[0])
    return rows


def fetch_agile(
    start: datetime,
    end: datetime,
    product: str = DEFAULT_PRODUCT,
    tariff: str = DEFAULT_TARIFF,
    max_pages: int = 4,
) -> list[tuple[datetime, datetime, float]]:
    url = f"{BASE}/products/{product}/electricity-tariffs/{tariff}/standard-unit-rates/"
    params = {
        "period_from": start.astimezone(timezone.utc).isoformat(),
        "period_to": end.astimezone(timezone.utc).isoformat(),
        "page_size": 1500,
    }
    rows: list[tuple[datetime, datetime, float]] = []
    for _ in range(max_pages):
        payload = get_json(url, params=params)
        rows.extend(parse_rates(payload))
        next_url = payload.get("next")
        if not next_url:
            break
        url, params = next_url, None  # type: ignore[assignment]
    if not rows:
        raise ProviderError("Octopus returned no unit rates for this period")
    rows.sort(key=lambda row: row[0])
    return rows