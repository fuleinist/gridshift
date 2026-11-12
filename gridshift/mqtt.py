"""Optional MQTT publisher for Home Assistant."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .appliances import default_loads
from .engine import make_plan, plan_dict
from .providers.tariff import TariffConfig
from .solver import Weights
from .sources import GB_TZ, build_slots


def publish_plan(args) -> int:
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        print("paho-mqtt is not installed. Run: pip install 'gridshift[mqtt]'")
        return 1

    slots, meta = build_slots(args.lat, args.lon, source="auto", tariff=TariffConfig(), tz=GB_TZ)
    loads = default_loads(slots[0].start, GB_TZ)
    plan = make_plan(slots, loads, weights=Weights(), kwp=args.solar_kwp, meta=meta)
    payload = plan_dict(plan)
    payload["published_at"] = datetime.now(timezone.utc).isoformat()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(args.host, args.port, keepalive=30)
    client.publish(args.topic, json.dumps(payload), retain=True)
    for placement in plan.placements:
        client.publish(
            f"{args.topic}/{placement.name}/start",
            placement.start.isoformat(),
            retain=True,
        )
        client.publish(
            f"{args.topic}/{placement.name}/carbon_kg",
            round(placement.carbon_kg, 3),
            retain=True,
        )
    client.disconnect()
    print(f"published {len(plan.placements)} loads to {args.host}:{args.port} {args.topic}")
    return 0