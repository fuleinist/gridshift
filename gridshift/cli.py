"""Command line interface for gridshift."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .appliances import default_loads
from .engine import horizon_text, make_plan, plan_dict, ranked
from .providers.base import Cache, ProviderError
from .providers.octopus import DEFAULT_PRODUCT, DEFAULT_TARIFF
from .providers.tariff import TariffConfig
from .solver import Weights
from .sources import GB_TZ, build_slots, local_label, postcode_lookup

console = Console()
BLOCKS = "▁▂▃▄▅▆▇█"


def spark(values: list[float]) -> str:
    if not values:
        return ""
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return BLOCKS[3] * len(values)
    out = []
    for value in values:
        idx = int((value - lo) / (hi - lo) * (len(BLOCKS) - 1))
        out.append(BLOCKS[idx])
    text = "".join(out)
    try:
        text.encode(sys.stdout.encoding or "utf-8")
        return text
    except (UnicodeEncodeError, LookupError):
        ascii_blocks = "_.,:-=+*#"
        return "".join(ascii_blocks[int((v - lo) / (hi - lo) * (len(ascii_blocks) - 1))] for v in values)


def money(value: float) -> str:
    return f"£{value:,.2f}"


def cache_path() -> Path:
    base = Path.home() / ".cache" / "gridshift"
    base.mkdir(parents=True, exist_ok=True)
    return base / "cache.sqlite"


def render_plan(plan, title: str) -> None:
    console.print(Panel.fit(title, style="bold cyan"))

    summary = Table.grid(padding=(0, 2))
    summary.add_column(justify="right", style="dim")
    summary.add_column(justify="left", style="bold")
    summary.add_row("Energy", f"{plan.energy_kwh:,.1f} kWh")
    summary.add_row("Carbon", f"{plan.carbon_kg:,.2f} kg CO2e")
    summary.add_row("Cost", money(plan.cost))
    summary.add_row(
        "Saving",
        f"{plan.carbon_saving_kg:,.2f} kg ({plan.carbon_saving_pct:,.0f}%) · "
        f"{money(plan.cost_saving)} ({plan.cost_saving_pct:,.0f}%)",
    )
    console.print(summary)
    console.print()

    table = Table(show_header=True, header_style="bold", box=None)
    table.add_column("Load")
    table.add_column("Start", no_wrap=True)
    table.add_column("End", no_wrap=True)
    table.add_column("kWh", justify="right")
    table.add_column("gCO2/kWh", justify="right")
    table.add_column("kg CO2", justify="right")
    table.add_column("Cost", justify="right")
    table.add_column("Saved", justify="right")
    base = {p.name: p for p in plan.baseline}
    for placement in plan.placements:
        old = base.get(placement.name)
        saved_carbon = (old.carbon_kg - placement.carbon_kg) if old else 0.0
        table.add_row(
            placement.name,
            local_label(placement.start, plan.meta.get("timezone", GB_TZ)),
            local_label(placement.end, plan.meta.get("timezone", GB_TZ)),
            f"{placement.energy_kwh:.2f}",
            f"{placement.mean_carbon:.0f}",
            f"{placement.carbon_kg:.3f}",
            money(placement.cost),
            f"{saved_carbon:+.3f} kg",
        )
    console.print(table)

    if plan.unplaced:
        console.print(f"[red]Not placed:[/red] {', '.join(plan.unplaced)}")
    for note in plan.notes:
        console.print(f"[yellow]note:[/yellow] {note}")

    values = [slot.carbon_g_per_kwh for slot in plan.slots]
    console.print()
    console.print(Text("Carbon intensity over the horizon", style="dim"))
    console.print(spark(values), style="green")
    labels = [local_label(slot.start, plan.meta.get("timezone", GB_TZ)) for slot in plan.slots]
    console.print(f"{labels[0]} … {labels[-1]}   min {min(values):.0f} · max {max(values):.0f} gCO2/kWh")


def cmd_plan(args: argparse.Namespace) -> int:
    if args.postcode:
        try:
            lat, lon = postcode_lookup(args.postcode)
        except ProviderError as exc:
            console.print(f"[red]postcode error:[/red] {exc}")
            return 1
    else:
        lat, lon = args.lat, args.lon

    tariff = TariffConfig(
        peak_price=args.peak_price,
        shoulder_price=args.shoulder_price,
        offpeak_price=args.offpeak_price,
    )
    cache = None if args.no_cache else Cache(cache_path())
    try:
        slots, meta = build_slots(
            lat,
            lon,
            start=None,
            hours=args.hours,
            source=args.source,
            tariff=tariff,
            agile=(args.agile_product, args.agile_tariff) if args.agile else None,
            tz=args.tz,
            cache=cache,
        )
    except Exception as exc:  # noqa: BLE001 - report provider failure once
        console.print(f"[red]could not build the horizon:[/red] {exc}")
        return 1
    finally:
        if cache:
            cache.close()

    loads = default_loads(slots[0].start, args.tz, include_ev=not args.no_ev)
    plan = make_plan(
        slots,
        loads,
        weights=Weights(args.carbon_weight, args.price_weight),
        max_load_kw=args.max_load_kw,
        kwp=args.solar_kwp,
        meta=meta,
    )
    plan.meta["command"] = "plan"

    if args.json:
        payload = plan_dict(plan)
        text = json.dumps(payload, indent=2)
        if args.json == "-":
            console.print_json(text)
        else:
            Path(args.json).write_text(text, encoding="utf-8")
            console.print(f"wrote {args.json}")
        return 0

    title = f"gridshift · {lat:.3f}, {lon:.3f} · {horizon_text(plan, args.tz)}"
    render_plan(plan, title)
    console.print()
    console.print(f"[dim]carbon: {meta['carbon_source']} · price: {meta['price_source']} · solar: {meta['solar_source']}[/dim]")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    slots, meta = build_slots(
        args.lat,
        args.lon,
        start=None,
        hours=args.hours,
        source="demo",
        tariff=TariffConfig(),
        tz=args.tz,
        cache=None,
        use_cache=False,
    )
    loads = default_loads(slots[0].start, args.tz, include_ev=True)
    plan = make_plan(
        slots,
        loads,
        weights=Weights(args.carbon_weight, args.price_weight),
        max_load_kw=args.max_load_kw,
        kwp=args.solar_kwp,
        meta=meta,
    )
    render_plan(plan, f"gridshift demo · {horizon_text(plan, args.tz)}")
    console.print()
    console.print("[dim]Offline demo curve. No network call was made.[/dim]")
    return 0


def cmd_loads(args: argparse.Namespace) -> int:
    loads = default_loads(datetime.now(timezone.utc), args.tz)
    table = Table(title="Default flexible loads", box=None)
    table.add_column("Load")
    table.add_column("kW", justify="right")
    table.add_column("Minutes", justify="right")
    table.add_column("Window")
    table.add_column("Priority", justify="right")
    for load in loads:
        table.add_row(
            load.name,
            f"{load.power_kw:.1f}",
            str(load.duration_min),
            f"{load.window_start:%H:%M}–{load.window_end:%H:%M}",
            str(load.priority),
        )
    console.print(table)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .api import run_server

    console.print(f"[bold]gridshift[/bold] on http://{args.host}:{args.port}")
    run_server(args.host, args.port)
    return 0


def cmd_mqtt(args: argparse.Namespace) -> int:
    from .mqtt import publish_plan

    return publish_plan(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gridshift", description="Run flexible loads when the grid is clean and cheap.")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="plan the next 24 hours")
    plan.add_argument("--lat", type=float, default=51.5074)
    plan.add_argument("--lon", type=float, default=-0.1278)
    plan.add_argument("--postcode", help="UK postcode, resolved with postcodes.io")
    plan.add_argument("--hours", type=float, default=24.0)
    plan.add_argument("--carbon-weight", type=float, default=0.6)
    plan.add_argument("--price-weight", type=float, default=0.4)
    plan.add_argument("--solar-kwp", type=float, default=0.0)
    plan.add_argument("--max-load-kw", type=float, default=8.0)
    plan.add_argument("--source", choices=["auto", "neso", "demo"], default="auto")
    plan.add_argument("--agile", action="store_true", help="use Octopus Agile public rates")
    plan.add_argument("--agile-product", default=DEFAULT_PRODUCT)
    plan.add_argument("--agile-tariff", default=DEFAULT_TARIFF)
    plan.add_argument("--peak-price", type=float, default=0.42)
    plan.add_argument("--shoulder-price", type=float, default=0.26)
    plan.add_argument("--offpeak-price", type=float, default=0.12)
    plan.add_argument("--no-ev", action="store_true")
    plan.add_argument("--no-cache", action="store_true")
    plan.add_argument("--tz", default=GB_TZ)
    plan.add_argument("--json", nargs="?", const="-", default=None)
    plan.set_defaults(func=cmd_plan)

    demo = sub.add_parser("demo", help="run offline with the demo curve")
    demo.add_argument("--lat", type=float, default=51.5074)
    demo.add_argument("--lon", type=float, default=-0.1278)
    demo.add_argument("--hours", type=float, default=24.0)
    demo.add_argument("--carbon-weight", type=float, default=0.6)
    demo.add_argument("--price-weight", type=float, default=0.4)
    demo.add_argument("--solar-kwp", type=float, default=4.0)
    demo.add_argument("--max-load-kw", type=float, default=8.0)
    demo.add_argument("--tz", default=GB_TZ)
    demo.set_defaults(func=cmd_demo)

    loads = sub.add_parser("loads", help="list the default loads")
    loads.add_argument("--tz", default=GB_TZ)
    loads.set_defaults(func=cmd_loads)

    serve = sub.add_parser("serve", help="start the local web UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=cmd_serve)

    mqtt = sub.add_parser("mqtt", help="publish the plan to an MQTT broker")
    mqtt.add_argument("--host", default="localhost")
    mqtt.add_argument("--port", type=int, default=1883)
    mqtt.add_argument("--topic", default="gridshift/plan")
    mqtt.add_argument("--lat", type=float, default=51.5074)
    mqtt.add_argument("--lon", type=float, default=-0.1278)
    mqtt.add_argument("--solar-kwp", type=float, default=0.0)
    mqtt.set_defaults(func=cmd_mqtt)

    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except ValueError as exc:
        console.print(f"[red]error:[/red] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())