# Home Assistant

The MQTT publisher sends one retained JSON document and one topic per load.

## Publish

```bash
pip install -e ".[mqtt]"
python -m gridshift mqtt --host 192.168.1.10 --topic gridshift/plan --solar-kwp 4
```

Topics:

- `gridshift/plan` — the full plan as JSON.
- `gridshift/plan/<load>/start` — ISO 8601 start time.
- `gridshift/plan/<load>/carbon_kg` — carbon for that run.

## Sensors

Add these blocks to `configuration.yaml`. Replace the broker and topic values.

```yaml
mqtt:
  sensor:
    - name: "gridshift dishwasher start"
      state_topic: "gridshift/plan/dishwasher/start"
      device_class: timestamp
      unique_id: gridshift_dishwasher_start

    - name: "gridshift EV start"
      state_topic: "gridshift/plan/ev_charger/start"
      device_class: timestamp
      unique_id: gridshift_ev_start

    - name: "gridshift dishwasher carbon"
      state_topic: "gridshift/plan/dishwasher/carbon_kg"
      unit_of_measurement: "kg"
      unique_id: gridshift_dishwasher_carbon
```

## Automation

Start the dishwasher at the planned time:

```yaml
automation:
  - alias: "Run dishwasher at the cleanest slot"
    trigger:
      - platform: time
        at: sensor.gridshift_dishwasher_start
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.dishwasher
```

The plan is advice. Keep a manual override.

## Refresh

Run the publisher from a scheduled task. Use the same interval as your tariff or carbon forecast. A 30-minute refresh matches the slot size.

```bash
# cron, every 30 minutes
*/30 * * * * /home/pi/gridshift/.venv/bin/python -m gridshift mqtt --host 192.168.1.10
```