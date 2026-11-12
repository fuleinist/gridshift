# gridshift — Specification

Status: MVP, version 0.1.0.
Owner: fuleinist.
Last updated: 2026-11-13.

## 1. Problem

A household can run some loads at any time. A dishwasher, a washing machine, a dryer and an EV charger do not care when they run. The grid does. Carbon intensity and price change through the day. Most people run these loads when they get home, which is often the dirtiest and most expensive hour.

## 2. Goal

Plan the next 24 hours of flexible loads. Put each load in the slot with the lowest combined carbon and price cost. Show the saving against a "run it now" baseline.

Success metric from the idea queue: a user shifts at least 2 kWh per week. Target: 20 percent cut in the carbon intensity of the shifted load.

## 3. Users

- A home owner with a time-of-use tariff.
- A home owner with rooftop solar who wants to use the surplus.
- A Home Assistant user who wants a schedule they can automate.

## 4. Scope

### 4.1 In scope

1. A 24-hour horizon at 30-minute resolution.
2. Carbon intensity from the NESO Carbon Intensity API for Great Britain.
3. Price from one of these sources:
   - Octopus Agile public unit rates.
   - A time-of-use tariff model with peak, shoulder and off-peak windows.
4. Solar forecast from Open-Meteo global horizontal irradiance, scaled by an array size in kWp.
5. A load list with these fields: name, power in kW, duration in minutes, run window, priority.
6. A scheduler with these rules:
   - Each load runs once, for its full duration, in contiguous slots.
   - Each load starts and ends inside its run window.
   - The total load in any slot does not exceed a site limit in kW.
   - The objective is a weighted sum of normalised carbon intensity and normalised price.
7. A baseline plan that starts each load at the first feasible slot. Use it to measure savings.
8. A ranked list of the best three start times for each load.
9. A CLI with a table view and a JSON view.
10. A local web UI with a chart, a schedule and a savings panel.
11. An optional MQTT publisher for Home Assistant.
12. A SQLite cache for provider responses.

### 4.2 Out of scope

- Live control of appliances. The tool plans. The user or Home Assistant runs the plan.
- AEMO and the Australian grid. The first release covers Great Britain and an offline demo curve.
- Battery dispatch, export limits and tariffs with demand charges.
- Carbon accounting for the full lifecycle of an appliance.

## 5. Functional requirements

| ID | Requirement |
|----|-------------|
| F1 | `gridshift plan` accepts a latitude and longitude, or a GB postcode. |
| F2 | The tool fetches carbon intensity for the horizon. It falls back to the demo curve when the region is outside Great Britain or the source is set to `demo`. |
| F3 | The tool fetches prices from Octopus Agile when a product code is given. It falls back to the time-of-use model with a warning. |
| F4 | The tool fetches a solar forecast when `--solar-kwp` is greater than zero. |
| F5 | The scheduler returns one start time for each load. |
| F6 | The result shows energy, carbon and cost for each load. |
| F7 | The result shows carbon and cost savings against the baseline. |
| F8 | `--json` writes the full result as JSON. |
| F9 | `gridshift serve` starts the web UI and the JSON API on a local port. |
| F10 | The web UI redraws the plan when the user changes the weights, the solar size or the site limit. |
| F11 | `gridshift mqtt` publishes the plan to an MQTT broker. |
| F12 | A failed provider call returns a clear error. The CLI falls back when a fallback exists. |

## 6. Non-functional requirements

- Python 3.10 or later.
- Pure functions for the scheduler. No network in the solver.
- Tests run offline. No test may call a public API.
- The solver is deterministic. Equal scores break on the earlier start.
- The solver must finish 48 slots and 20 loads in under one second.
- The web UI is one HTML file with no CDN and no build step.
- All public data sources are free and need no key.

## 7. Algorithm

1. Build slots from the horizon start. Each slot is 30 minutes.
2. Normalise carbon and price across the horizon to the range 0 to 1.
3. Score a slot per grid kWh: `carbon_weight * carbon_norm + price_weight * price_norm`.
4. Start each load at its best feasible slot, in priority order.
5. Improve the plan with coordinate descent. For each load, remove it, then find its best feasible slot given the other loads. Repeat until no load moves, with a cap of 8 passes.
6. Compute the baseline with the same cap rule, but always choose the earliest feasible slot.
7. Report the plan, the baseline and the difference.

A load only pays for grid energy. Solar output first covers the other scheduled loads, then this load. The remainder comes from the grid. This makes the model conservative when two loads overlap.

## 8. Acceptance criteria

- [x] A dishwasher with a 17:00 to 23:00 window lands in the cleanest and cheapest part of that window when weights are equal.
- [x] No load overlaps another when the site limit is too small for both.
- [x] The plan is never worse than the baseline on the weighted objective.
- [x] Every load starts and ends inside its run window.
- [x] The test suite runs offline and passes.
- [x] The web UI shows a chart and a schedule from a live or demo source.
- [x] The README explains the data sources and the limits of the model.

## 9. Risks and limits

- NESO covers Great Britain only.
- Octopus Agile is one tariff. Other tariffs use the time-of-use model.
- Carbon intensity is national or regional. A local street can differ.
- Solar output is a forecast. Clouds move.
- A plan is advice. The user must confirm each run.

## 10. Milestones

1. M1: spec, models, solver and tests.
2. M2: providers, cache and CLI.
3. M3: web UI and screenshots.
4. M4: README, logo and release.