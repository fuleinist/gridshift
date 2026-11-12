from __future__ import annotations

from datetime import datetime, timezone

import pytest

from gridshift.providers.neso import parse_intensity
from gridshift.providers.octopus import parse_rates
from gridshift.providers.solar import demo_solar, parse_solar
from gridshift.providers.tariff import TariffConfig, price_at


def test_parse_intensity_prefers_actual_over_forecast():
    payload = {
        "data": [
            {
                "from": "2026-11-13T00:00Z",
                "to": "2026-11-13T00:30Z",
                "intensity": {"forecast": 120, "actual": 98, "index": "low"},
            },
            {
                "from": "2026-11-13T00:30Z",
                "to": "2026-11-13T01:00Z",
                "intensity": {"forecast": 130, "actual": None, "index": "moderate"},
            },
        ]
    }
    rows = parse_intensity(payload)
    assert [row[2] for row in rows] == [98, 130]
    assert rows[0][0] == datetime(2026, 11, 13, 0, 0, tzinfo=timezone.utc)


def test_parse_intensity_rejects_empty_payload():
    from gridshift.providers.base import ProviderError

    with pytest.raises(ProviderError):
        parse_intensity({"data": []})


def test_parse_agile_rates_converts_pence_to_pounds():
    payload = {
        "results": [
            {
                "valid_from": "2026-11-13T00:00:00Z",
                "valid_to": "2026-11-13T00:30:00Z",
                "value_inc_vat": 21.5,
            }
        ]
    }
    rows = parse_rates(payload)
    assert rows[0][2] == pytest.approx(0.215)


def test_parse_solar_reads_hourly_series():
    payload = {
        "hourly": {
            "time": ["2026-11-13T00:00", "2026-11-13T01:00"],
            "shortwave_radiation": [0.0, 120.0],
        }
    }
    series = parse_solar(payload)
    assert series[datetime(2026, 11, 13, 1, 0, tzinfo=timezone.utc)] == 120.0


def test_demo_solar_is_zero_at_night():
    night = datetime(2026, 11, 13, 2, 0, tzinfo=timezone.utc)
    noon = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
    assert demo_solar(night) == 0.0
    assert demo_solar(noon) > 500.0


def test_time_of_use_peak_and_offpeak():
    config = TariffConfig()
    peak = datetime(2026, 11, 13, 17, 0, tzinfo=timezone.utc)
    offpeak = datetime(2026, 11, 13, 3, 0, tzinfo=timezone.utc)
    shoulder = datetime(2026, 11, 13, 11, 0, tzinfo=timezone.utc)
    assert price_at(peak, config, "UTC") == config.peak_price
    assert price_at(offpeak, config, "UTC") == config.offpeak_price
    assert price_at(shoulder, config, "UTC") == config.shoulder_price


def test_tariff_validation_rejects_bad_hour():
    with pytest.raises(ValueError):
        TariffConfig(peak_start=25, peak_end=6).validate()


def test_tariff_validation_rejects_negative_price():
    with pytest.raises(ValueError):
        TariffConfig(peak_price=-0.1).validate()