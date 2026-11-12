"""Deterministic scheduler for flexible loads.

The solver has no network code. Give it slots and loads, and it returns a plan.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from .models import Load, Placement, Slot


class ScheduleError(RuntimeError):
    """Raised when the input cannot produce a plan."""


@dataclass(frozen=True)
class Weights:
    """Relative weight of carbon and price in the objective."""

    carbon: float = 0.6
    price: float = 0.4

    def __post_init__(self) -> None:
        if self.carbon < 0 or self.price < 0:
            raise ValueError("weights must be zero or positive")
        if self.carbon + self.price <= 0:
            raise ValueError("at least one weight must be positive")

    def normalised(self) -> "Weights":
        total = self.carbon + self.price
        return Weights(self.carbon / total, self.price / total)


@dataclass
class Context:
    slots: list[Slot]
    carbon_norm: list[float]
    price_norm: list[float]
    weights: Weights
    kwp: float


def _normalise(values: list[float]) -> list[float]:
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if hi - lo < 1e-9:
        return [0.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def build_context(slots: list[Slot], weights: Weights, kwp: float) -> Context:
    if not slots:
        raise ScheduleError("the horizon has no slots")
    w = weights.normalised()
    return Context(
        slots=slots,
        carbon_norm=_normalise([s.carbon_g_per_kwh for s in slots]),
        price_norm=_normalise([s.price_per_kwh for s in slots]),
        weights=w,
        kwp=max(0.0, kwp),
    )


def slot_count(load: Load, step_min: int = 30) -> int:
    return max(1, math.ceil(load.duration_min / step_min))


def _first_index(slots: list[Slot], when: datetime) -> int:
    for i, slot in enumerate(slots):
        if slot.start >= when:
            return i
    return len(slots)


def feasible_range(slots: list[Slot], load: Load) -> tuple[int, int]:
    """Return the inclusive range of start indices that fit the window."""
    if not slots:
        return (0, -1)
    n = slot_count(load, slots[0].duration_min)
    lo = _first_index(slots, load.window_start)
    hi = lo - 1
    for i in range(lo, len(slots) - n + 1):
        if slots[i + n - 1].end <= load.window_end:
            hi = i
        else:
            break
    return (lo, hi)


def _grid_energy(slot: Slot, power_kw: float, other_kw: float, kwp: float) -> tuple[float, float]:
    """Split a load between solar and grid. Solar covers other loads first."""
    solar_kw = max(0.0, slot.solar_kw_per_kwp) * max(0.0, kwp)
    residual = max(0.0, solar_kw - max(0.0, other_kw))
    grid_kw = max(0.0, power_kw - residual)
    return grid_kw * slot.hours, (power_kw - grid_kw) * slot.hours


def evaluate_start(ctx: Context, load: Load, start: int, profile: list[float]) -> Placement:
    n = slot_count(load, ctx.slots[0].duration_min)
    energy = solar = carbon = cost = score = 0.0
    for i in range(start, start + n):
        slot = ctx.slots[i]
        other = profile[i] if profile else 0.0
        grid_kwh, solar_kwh = _grid_energy(slot, load.power_kw, other, ctx.kwp)
        energy += grid_kwh
        solar += solar_kwh
        carbon += grid_kwh * slot.carbon_g_per_kwh / 1000.0
        cost += grid_kwh * slot.price_per_kwh
        score += grid_kwh * (
            ctx.weights.carbon * ctx.carbon_norm[i] + ctx.weights.price * ctx.price_norm[i]
        )
    return Placement(
        name=load.name,
        start=ctx.slots[start].start,
        end=ctx.slots[start + n - 1].end,
        energy_kwh=energy,
        solar_kwh=solar,
        carbon_kg=carbon,
        cost=cost,
        score=score,
        mean_carbon=(1000.0 * carbon / energy) if energy > 0 else 0.0,
        start_index=start,
        slot_count=n,
    )


def _fits(profile: list[float], load: Load, start: int, n: int, max_load_kw: float) -> bool:
    for i in range(start, start + n):
        if profile[i] + load.power_kw > max_load_kw + 1e-9:
            return False
    return True


def best_start(
    ctx: Context,
    load: Load,
    profile: list[float],
    max_load_kw: float,
    respect_cap: bool = True,
) -> Placement | None:
    lo, hi = feasible_range(ctx.slots, load)
    if hi < lo:
        return None
    n = slot_count(load, ctx.slots[0].duration_min)
    best: Placement | None = None
    best_key: tuple[float, int] | None = None
    for start in range(lo, hi + 1):
        if respect_cap and not _fits(profile, load, start, n, max_load_kw):
            continue
        candidate = evaluate_start(ctx, load, start, profile)
        key = (round(candidate.score, 9), start)
        if best_key is None or key < best_key:
            best = candidate
            best_key = key
    return best


def _apply(profile: list[float], placement: Placement, power_kw: float, sign: float) -> None:
    for i in range(placement.start_index, placement.start_index + placement.slot_count):
        profile[i] += sign * power_kw


def _greedy(ctx: Context, loads: list[Load], max_load_kw: float, earliest: bool) -> tuple[list[Placement], list[str]]:
    profile = [0.0] * len(ctx.slots)
    placements: list[Placement] = []
    unplaced: list[str] = []
    order = sorted(loads, key=lambda l: (-l.priority, -l.duration_min, l.name))
    for load in order:
        n = slot_count(load, ctx.slots[0].duration_min)
        lo, hi = feasible_range(ctx.slots, load)
        chosen: Placement | None = None
        if earliest:
            # The baseline is what a household does without a plan: run at once.
            # It ignores the site limit, so both plans carry the same loads.
            for start in range(lo, max(lo, hi) + 1):
                if hi < lo:
                    break
                chosen = evaluate_start(ctx, load, start, profile)
                break
        else:
            chosen = best_start(ctx, load, profile, max_load_kw)
        if chosen is None:
            unplaced.append(load.name)
            continue
        _apply(profile, chosen, load.power_kw, +1.0)
        placements.append(chosen)
    return placements, unplaced


def solve(
    slots: list[Slot],
    loads: list[Load],
    weights: Weights | None = None,
    max_load_kw: float = 8.0,
    kwp: float = 0.0,
    passes: int = 8,
) -> tuple[list[Placement], list[Placement], list[str], Context]:
    """Return the optimised plan, the earliest-start baseline and unplaced names."""
    if max_load_kw <= 0:
        raise ValueError("max_load_kw must be positive")
    ctx = build_context(slots, weights or Weights(), kwp)

    # Baseline first: it has no effect on the optimised plan.
    baseline, base_unplaced = _greedy(ctx, loads, max_load_kw, earliest=True)

    placements, unplaced = _greedy(ctx, loads, max_load_kw, earliest=False)
    by_name = {p.name: p for p in placements}
    power = {l.name: l.power_kw for l in loads}
    profile = [0.0] * len(slots)
    for p in placements:
        _apply(profile, p, power[p.name], +1.0)

    for _ in range(passes):
        moved = False
        for load in sorted(loads, key=lambda l: (l.priority, l.name)):
            current = by_name.get(load.name)
            if current is None:
                continue
            _apply(profile, current, load.power_kw, -1.0)
            candidate = best_start(ctx, load, profile, max_load_kw)
            if candidate is not None and candidate.score < current.score - 1e-9:
                _apply(profile, candidate, load.power_kw, +1.0)
                by_name[load.name] = candidate
                moved = True
            else:
                _apply(profile, current, load.power_kw, +1.0)
        if not moved:
            break

    result = sorted(by_name.values(), key=lambda p: (p.start, p.name))
    notes: list[str] = []
    missing = [name for name in unplaced if name not in by_name]
    for name in base_unplaced:
        if name not in missing:
            notes.append(f"{name}: no slot fits the run window at the site limit")
    return result, baseline, missing, ctx


def rank_starts(
    slots: list[Slot],
    load: Load,
    weights: Weights | None = None,
    max_load_kw: float = 8.0,
    kwp: float = 0.0,
    top: int = 3,
) -> list[Placement]:
    """Best independent start times for one load, ignoring other loads."""
    ctx = build_context(slots, weights or Weights(), kwp)
    profile = [0.0] * len(slots)
    lo, hi = feasible_range(slots, load)
    candidates: list[Placement] = []
    for start in range(lo, max(lo, hi) + 1):
        if hi < lo:
            break
        if not _fits(profile, load, start, slot_count(load, slots[0].duration_min), max_load_kw):
            continue
        candidates.append(evaluate_start(ctx, load, start, profile))
    candidates.sort(key=lambda p: (round(p.score, 9), p.start_index))
    return candidates[:top]