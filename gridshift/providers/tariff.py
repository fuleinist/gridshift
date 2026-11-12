"""Time-of-use tariff model. Used when no Agile rates are available."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class TariffConfig:
    peak_price: float = 0.42
    shoulder_price: float = 0.26
    offpeak_price: float = 0.12
    peak_start: int = 16
    peak_end: int = 21
    offpeak_start: int = 0
    offpeak_end: int = 7

    def validate(self) -> None:
        if min(self.peak_price, self.shoulder_price, self.offpeak_price) < 0:
            raise ValueError("tariff prices must be zero or positive")
        if not (0 <= self.peak_start < 24 and 0 <= self.peak_end <= 24):
            raise ValueError("peak window must be inside one day")
        if not (0 <= self.offpeak_start < 24 and 0 <= self.offpeak_end <= 24):
            raise ValueError("off-peak window must be inside one day")


def price_at(dt: datetime, config: TariffConfig | None = None, tz: str = "Europe/London") -> float:
    cfg = config or TariffConfig()
    local = dt.astimezone(ZoneInfo(tz))
    hour = local.hour + local.minute / 60.0

    def inside(start: int, end: int) -> bool:
        if start <= end:
            return start <= hour < end
        return hour >= start or hour < end

    if inside(cfg.peak_start, cfg.peak_end):
        return cfg.peak_price
    if inside(cfg.offpeak_start, cfg.offpeak_end):
        return cfg.offpeak_price
    return cfg.shoulder_price


def average_price(config: TariffConfig | None = None) -> float:
    cfg = config or TariffConfig()
    peak_hours = (cfg.peak_end - cfg.peak_start) % 24
    off_hours = (cfg.offpeak_end - cfg.offpeak_start) % 24
    shoulder_hours = 24 - peak_hours - off_hours
    return (
        peak_hours * cfg.peak_price
        + off_hours * cfg.offpeak_price
        + max(0, shoulder_hours) * cfg.shoulder_price
    ) / 24.0