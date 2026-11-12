"""Data model for gridshift."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Slot:
    """One planning slot with grid signals."""

    start: datetime
    carbon_g_per_kwh: float
    price_per_kwh: float
    solar_kw_per_kwp: float = 0.0
    duration_min: int = 30

    @property
    def end(self) -> datetime:
        return self.start + timedelta(minutes=self.duration_min)

    @property
    def hours(self) -> float:
        return self.duration_min / 60.0


@dataclass(frozen=True)
class Load:
    """A flexible appliance run."""

    name: str
    power_kw: float
    duration_min: int
    window_start: datetime
    window_end: datetime
    priority: int = 1

    def __post_init__(self) -> None:
        if self.power_kw <= 0:
            raise ValueError(f"load {self.name!r}: power_kw must be positive")
        if self.duration_min <= 0:
            raise ValueError(f"load {self.name!r}: duration_min must be positive")
        if self.window_end <= self.window_start:
            raise ValueError(f"load {self.name!r}: empty run window")


@dataclass
class Placement:
    """A load placed on the horizon."""

    name: str
    start: datetime
    end: datetime
    energy_kwh: float
    solar_kwh: float
    carbon_kg: float
    cost: float
    score: float
    mean_carbon: float
    start_index: int = 0
    slot_count: int = 0


@dataclass
class Plan:
    """A full schedule plus the naive baseline."""

    slots: list[Slot]
    placements: list[Placement]
    baseline: list[Placement]
    unplaced: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    @property
    def energy_kwh(self) -> float:
        return sum(p.energy_kwh for p in self.placements)

    @property
    def carbon_kg(self) -> float:
        return sum(p.carbon_kg for p in self.placements)

    @property
    def cost(self) -> float:
        return sum(p.cost for p in self.placements)

    @property
    def baseline_energy_kwh(self) -> float:
        return sum(p.energy_kwh for p in self.baseline)

    @property
    def baseline_carbon_kg(self) -> float:
        return sum(p.carbon_kg for p in self.baseline)

    @property
    def baseline_cost(self) -> float:
        return sum(p.cost for p in self.baseline)

    @property
    def carbon_saving_kg(self) -> float:
        return self.baseline_carbon_kg - self.carbon_kg

    @property
    def cost_saving(self) -> float:
        return self.baseline_cost - self.cost

    @property
    def carbon_saving_pct(self) -> float:
        if self.baseline_carbon_kg <= 0:
            return 0.0
        return 100.0 * self.carbon_saving_kg / self.baseline_carbon_kg

    @property
    def cost_saving_pct(self) -> float:
        if self.baseline_cost <= 0:
            return 0.0
        return 100.0 * self.cost_saving / self.baseline_cost

    def mean_carbon(self) -> float:
        if self.energy_kwh <= 0:
            return 0.0
        return 1000.0 * self.carbon_kg / self.energy_kwh