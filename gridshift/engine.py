"""Glue the solver and the sources into one plan."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from zoneinfo import ZoneInfo

from .models import Load, Plan, Slot
from .solver import Weights, rank_starts, solve


def make_plan(
    slots: list[Slot],
    loads: list[Load],
    weights: Weights | None = None,
    max_load_kw: float = 8.0,
    kwp: float = 0.0,
    meta: dict | None = None,
) -> Plan:
    placements, baseline, unplaced, _ = solve(
        slots, loads, weights=weights, max_load_kw=max_load_kw, kwp=kwp
    )
    notes = list((meta or {}).get("notes", [])) if meta else []
    for name in unplaced:
        notes.append(f"{name}: no feasible slot in the run window")
    return Plan(
        slots=slots,
        placements=placements,
        baseline=baseline,
        unplaced=unplaced,
        notes=notes,
        meta=meta or {},
    )


def _placement_dict(placement) -> dict:
    data = asdict(placement)
    data["start"] = placement.start.isoformat()
    data["end"] = placement.end.isoformat()
    return data


def plan_dict(plan: Plan) -> dict:
    return {
        "meta": plan.meta,
        "summary": {
            "energy_kwh": round(plan.energy_kwh, 3),
            "carbon_kg": round(plan.carbon_kg, 3),
            "cost": round(plan.cost, 2),
            "mean_carbon_g_per_kwh": round(plan.mean_carbon(), 1),
            "baseline_energy_kwh": round(plan.baseline_energy_kwh, 3),
            "baseline_carbon_kg": round(plan.baseline_carbon_kg, 3),
            "baseline_cost": round(plan.baseline_cost, 2),
            "carbon_saving_kg": round(plan.carbon_saving_kg, 3),
            "cost_saving": round(plan.cost_saving, 2),
            "carbon_saving_pct": round(plan.carbon_saving_pct, 1),
            "cost_saving_pct": round(plan.cost_saving_pct, 1),
        },
        "placements": [_placement_dict(p) for p in plan.placements],
        "baseline": [_placement_dict(p) for p in plan.baseline],
        "unplaced": plan.unplaced,
        "notes": plan.notes,
        "slots": [
            {
                "start": s.start.isoformat(),
                "carbon_g_per_kwh": round(s.carbon_g_per_kwh, 1),
                "price_per_kwh": round(s.price_per_kwh, 3),
                "solar_kw_per_kwp": round(s.solar_kw_per_kwp, 3),
            }
            for s in plan.slots
        ],
    }


def ranked(plan: Plan, loads: list[Load], weights: Weights | None, max_load_kw: float, kwp: float) -> dict:
    out = {}
    for load in loads:
        out[load.name] = [
            {
                "start": p.start.isoformat(),
                "end": p.end.isoformat(),
                "carbon_kg": round(p.carbon_kg, 3),
                "cost": round(p.cost, 2),
                "score": round(p.score, 4),
            }
            for p in rank_starts(plan.slots, load, weights, max_load_kw, kwp, top=3)
        ]
    return out


def horizon_text(plan: Plan, tz: str) -> str:
    zone = ZoneInfo(tz)
    start = plan.slots[0].start.astimezone(zone)
    end = plan.slots[-1].end.astimezone(zone)
    return f"{start:%a %d %b %H:%M} to {end:%a %d %b %H:%M} ({tz})"