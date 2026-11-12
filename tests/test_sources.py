from __future__ import annotations

from datetime import datetime, timezone

import pytest

from gridshift.appliances import default_loads
from gridshift.engine import make_plan, plan_dict
from gridshift.providers.base import Cache
from gridshift.providers.tariff import TariffConfig
from gridshift.solver import Weights
from gridshift.sources import align_up, build_slots, demo_carbon, postcode_lookup


def test_align_up_rounds_to_next_half_hour():
    dt = datetime(2026, 11, 13, 6, 7, 45, tzinfo=timezone.utc)
    assert align_up(dt) == datetime(2026, 11, 13, 6, 30, tzinfo=timezone.utc)
    exact = datetime(2026, 11, 13, 6, 30, 0, tzinfo=timezone.utc)
    assert align_up(exact) == exact


def test_demo_curve_is_deterministic_and_positive():
    dt = datetime(2026, 11, 13, 18, 0, tzinfo=timezone.utc)
    assert demo_carbon(dt) == demo_carbon(dt)
    assert demo_carbon(dt) > 30


def test_demo_slots_have_no_network_source():
    slots, meta = build_slots(
        51.5074,
        -0.1278,
        start=datetime(2026, 11, 13, 6, 0, tzinfo=timezone.utc),
        hours=6,
        source="demo",
        tariff=TariffConfig(),
        cache=None,
        use_cache=False,
    )
    assert len(slots) == 12
    assert meta["carbon_source"] == "demo curve"
    assert all(slot.carbon_g_per_kwh > 0 for slot in slots)


def test_cache_round_trip(tmp_path):
    cache = Cache(tmp_path / "cache.sqlite")
    start = datetime(2026, 11, 13, 6, 0, tzinfo=timezone.utc)
    slots, meta = build_slots(
        51.5074, -0.1278, start=start, hours=2, source="demo", cache=cache
    )
    assert meta["cached"] is False
    again, meta2 = build_slots(
        51.5074, -0.1278, start=start, hours=2, source="demo", cache=cache
    )
    assert meta2["cached"] is True
    assert [s.carbon_g_per_kwh for s in again] == [s.carbon_g_per_kwh for s in slots]
    cache.close()


def test_default_loads_fit_the_horizon():
    start = datetime(2026, 11, 13, 6, 30, tzinfo=timezone.utc)
    loads = default_loads(start, "Europe/London")
    assert {load.name for load in loads} >= {"dishwasher", "ev_charger"}
    for load in loads:
        assert load.window_end > load.window_start
        assert load.duration_min > 0


def test_plan_dict_is_json_ready():
    import json

    slots, meta = build_slots(
        51.5074,
        -0.1278,
        start=datetime(2026, 11, 13, 6, 0, tzinfo=timezone.utc),
        hours=24,
        source="demo",
        cache=None,
        use_cache=False,
    )
    loads = default_loads(slots[0].start, "Europe/London")
    plan = make_plan(slots, loads, Weights(0.6, 0.4), 8.0, 0.0, meta)
    payload = plan_dict(plan)
    text = json.dumps(payload)
    assert len(payload["slots"]) == 48
    assert payload["summary"]["energy_kwh"] >= 0
    assert "placements" in payload
    assert text


def test_postcode_lookup_rejects_missing_value(monkeypatch):
    from gridshift.providers import base

    monkeypatch.setattr(base, "get_json", lambda *a, **k: {"result": None})
    with pytest.raises(Exception):
        postcode_lookup("ZZ99 9ZZ")