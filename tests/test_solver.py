from __future__ import annotations

from datetime import datetime, timedelta, timezone

from gridshift.models import Load, Slot
from gridshift.solver import Weights, feasible_range, rank_starts, solve


def make_slots(carbon: list[float], price: list[float] | None = None, solar: float = 0.0) -> list[Slot]:
    start = datetime(2026, 11, 13, 0, 0, tzinfo=timezone.utc)
    price = price or [0.25] * len(carbon)
    return [
        Slot(
            start=start + timedelta(minutes=30 * i),
            carbon_g_per_kwh=c,
            price_per_kwh=price[i],
            solar_kw_per_kwp=solar,
        )
        for i, c in enumerate(carbon)
    ]


def make_load(slots: list[Slot], name="load", power=1.0, minutes=60, first=0, last=None, priority=1) -> Load:
    last = len(slots) - 1 if last is None else last
    return Load(
        name=name,
        power_kw=power,
        duration_min=minutes,
        window_start=slots[first].start,
        window_end=slots[last].end,
        priority=priority,
    )


def test_placement_is_contiguous_and_inside_window():
    slots = make_slots([200, 190, 180, 170, 160, 150, 140, 130])
    load = make_load(slots, minutes=90, first=1, last=5)
    placements, _, unplaced, _ = solve(slots, [load], Weights(1, 0))
    assert not unplaced
    p = placements[0]
    assert p.slot_count == 3
    assert p.start >= load.window_start
    assert p.end <= load.window_end
    assert p.start_index >= 1
    assert p.start_index + p.slot_count - 1 <= 5


def test_prefers_low_carbon_slot():
    slots = make_slots([300, 100, 300, 100, 300, 100])
    load = make_load(slots, minutes=30)
    placements, _, _, _ = solve(slots, [load], Weights(1.0, 0.0))
    assert placements[0].start_index == 1


def test_prefers_cheap_slot_when_price_weight_dominates():
    slots = make_slots([200] * 6, price=[0.40, 0.10, 0.20, 0.30, 0.50, 0.60])
    load = make_load(slots)
    placements, _, _, _ = solve(slots, [load], Weights(0.0, 1.0))
    assert placements[0].start_index == 1


def test_equal_weights_balance_both_signals():
    slots = make_slots([400, 100, 100], price=[0.10, 0.45, 0.12])
    load = make_load(slots, minutes=30)
    placements, _, _, _ = solve(slots, [load], Weights(0.5, 0.5))
    # Slot 1 is cleanest but costly. Slot 0 is cheap but dirty. Slot 2 wins on the blend.
    assert placements[0].start_index == 2


def test_site_limit_prevents_overlap():
    slots = make_slots([200, 200, 200, 200])
    a = make_load(slots, name="a", power=3.0, minutes=60, first=0, last=3)
    b = make_load(slots, name="b", power=3.0, minutes=60, first=0, last=3)
    placements, _, unplaced, _ = solve(slots, [a, b], Weights(1, 0), max_load_kw=4.0)
    assert not unplaced
    assert len(placements) == 2
    assert placements[0].start_index != placements[1].start_index


def test_plan_is_not_worse_than_baseline():
    slots = make_slots([320, 300, 280, 140, 120, 130, 260, 300])
    load = make_load(slots, minutes=60, first=0, last=7)
    placements, baseline, _, _ = solve(slots, [load], Weights(1.0, 0.0))
    assert placements[0].carbon_kg < baseline[0].carbon_kg
    assert baseline[0].start_index == 0


def test_infeasible_load_is_reported_not_raised():
    slots = make_slots([200] * 4)
    load = make_load(slots, minutes=240, first=0, last=1)
    placements, baseline, unplaced, _ = solve(slots, [load])
    assert placements == []
    assert baseline == []
    assert unplaced == ["load"]


def test_solar_covers_the_load():
    slots = make_slots([400] * 4, solar=1.0)
    load = make_load(slots)
    placements, _, _, _ = solve(slots, [load], Weights(1, 0), kwp=10.0)
    assert placements[0].energy_kwh == 0.0
    assert placements[0].solar_kwh == 1.0
    assert placements[0].carbon_kg == 0.0


def test_solar_is_shared_between_loads():
    slots = make_slots([400] * 4, solar=1.2)
    a = make_load(slots, name="a", power=1.0, minutes=60, first=0, last=1)
    b = make_load(slots, name="b", power=1.0, minutes=60, first=0, last=1)
    placements, _, _, _ = solve(slots, [a, b], Weights(1, 0), max_load_kw=5.0, kwp=1.0)
    energy = sum(p.energy_kwh for p in placements)
    # 1.2 kWh of solar is available and 2 kWh of load runs. 0.8 kWh must come from the grid.
    assert abs(energy - 0.8) < 1e-9


def test_rank_starts_returns_best_first():
    slots = make_slots([300, 90, 250, 80, 200])
    load = make_load(slots, minutes=30)
    ranked = rank_starts(slots, load, Weights(1, 0), top=3)
    assert [p.start_index for p in ranked] == [3, 1, 4]


def test_feasible_range_matches_window():
    slots = make_slots([200] * 6)
    load = make_load(slots, minutes=90, first=1, last=3)
    lo, hi = feasible_range(slots, load)
    assert lo == 1
    assert hi == 1


def test_zero_weight_is_rejected():
    import pytest

    with pytest.raises(ValueError):
        Weights(0, 0)


def test_solver_is_deterministic():
    slots = make_slots([200, 180, 160, 140, 120, 130, 170, 210])
    loads = [make_load(slots, name=f"l{i}", first=0, last=5, priority=i % 3) for i in range(5)]
    first, _, _, _ = solve(slots, loads, Weights(0.5, 0.5))
    second, _, _, _ = solve(slots, loads, Weights(0.5, 0.5))
    assert [(p.name, p.start_index) for p in first] == [(p.name, p.start_index) for p in second]