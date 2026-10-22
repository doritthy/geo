"""Demo IoT sensors: creates sensors around the demo building, backfills a
week of history and optionally keeps streaming live readings.

    python scripts/iot_simulator.py --api http://localhost:8000 --project <id> \\
        --email demo@example.com --password demo12345 [--live] [--mqtt localhost]

Signals: concrete curing temperature in the 3rd-floor slab (hydration peak,
then cooling; one sensor drifts into the warning band), strain gauges on
columns (daily thermal cycle), a tilt meter on the crane and a humidity probe.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import time
from datetime import datetime, timedelta, timezone

import httpx

SENSORS = [
    # code, name, kind, unit, (dx m, dy m, dz m from building center), thresholds
    ("T-301", "Плита 3 эт., ось Б-2", "temperature", "°C", (-6, 0, 3.3), dict(warn_min=5, warn_max=55, alarm_min=0, alarm_max=70)),
    ("T-302", "Плита 3 эт., ось Д-5", "temperature", "°C", (8, 4, 3.3), dict(warn_min=5, warn_max=55, alarm_min=0, alarm_max=70)),
    ("T-303", "Плита 3 эт., ось Г-3", "temperature", "°C", (2, -4, 3.3), dict(warn_min=5, warn_max=55, alarm_min=0, alarm_max=70)),
    ("S-101", "Колонна К-12, 1 эт.", "strain", "мкм/м", (-15, -9, -6), dict(warn_min=-400, warn_max=400, alarm_min=-600, alarm_max=600)),
    ("S-102", "Колонна К-18, 1 эт.", "strain", "мкм/м", (15, 9, -6), dict(warn_min=-400, warn_max=400, alarm_min=-600, alarm_max=600)),
    ("TL-1", "Башенный кран, крен", "tilt", "мм/м", (24, -14, 20), dict(warn_max=2.0, alarm_max=4.0)),
    ("H-1", "Подвал, влажность", "humidity", "%", (0, 0, -8), dict(warn_max=80, alarm_max=90)),
]


def signal(code: str, t: datetime, start: datetime, rng: random.Random) -> float:
    h = (t - start).total_seconds() / 3600
    day = math.sin((t.hour + t.minute / 60 - 9) / 24 * 2 * math.pi)
    if code.startswith("T-"):
        peak = {"T-301": 48, "T-302": 58, "T-303": 44}[code]  # T-302: too hot -> warning
        ambient = 12 + 6 * day
        hydration = peak * (h / 18) * math.exp(1 - h / 18) if h > 0 else 0
        return round(max(ambient, ambient + hydration - 12 * (1 - math.exp(-h / 40))) + rng.gauss(0, 0.3), 2)
    if code.startswith("S-"):
        base = -120 if code == "S-101" else -90
        return round(base - 0.4 * h + 35 * day + rng.gauss(0, 4), 1)
    if code == "TL-1":
        return round(abs(0.6 + 0.5 * day + rng.gauss(0, 0.15)), 2)
    # Basement humidity creeps up over the last day (drainage issue) -> warning.
    total_h = (datetime.now(timezone.utc) - start).total_seconds() / 3600
    leak = max(0.0, h - (total_h - 30)) * 0.8
    return round(62 + 8 * math.sin(h / 30) + leak + rng.gauss(0, 1), 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--project", required=True)
    ap.add_argument("--email", default="demo@example.com")
    ap.add_argument("--password", default="demo12345")
    ap.add_argument("--days", type=float, default=7)
    ap.add_argument("--step-min", type=float, default=10)
    ap.add_argument("--live", action="store_true", help="keep sending one reading per sensor per --live-sec")
    ap.add_argument("--live-sec", type=float, default=30)
    ap.add_argument("--mqtt", default=None, help="MQTT host for live readings (default: HTTP)")
    args = ap.parse_args()

    c = httpx.Client(base_url=args.api, timeout=120)
    tok = c.post("/api/auth/login", json={"email": args.email, "password": args.password}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    assets = c.get(f"/api/projects/{args.project}/assets", headers=h).json()
    center = next((a["stats"]["center"] for a in assets if a["kind"] == "bim" and a["stats"].get("center")), None)
    if center is None:
        raise SystemExit("В проекте нет геопривязанной BIM-модели — не к чему привязать датчики")
    lat0, lon0, h0 = center["latitude"], center["longitude"], center["height"]
    m_lat = 111_320.0
    m_lon = 111_320.0 * math.cos(math.radians(lat0))

    existing = {s["code"]: s for s in c.get(f"/api/projects/{args.project}/sensors", headers=h).json()}
    sensors = []
    for code, name, kind, unit, (dx, dy, dz), thr in SENSORS:
        if code in existing:
            s = c.get(f"/api/sensors/{existing[code]['id']}", headers=h).json()
        else:
            s = c.post(f"/api/projects/{args.project}/sensors", headers=h, json={
                "code": code, "name": name, "kind": kind, "unit": unit, "stale_minutes": 120,
                "longitude": lon0 + dx / m_lon, "latitude": lat0 + dy / m_lat, "height": h0 + dz, **thr,
            }).json()
        sensors.append(s)

    rng = random.Random(1)
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = now - timedelta(days=args.days)
    for s in sensors:
        t, batch = start, []
        while t <= now:
            batch.append({"value": signal(s["code"], t, start, rng), "ts": t.isoformat()})
            t += timedelta(minutes=args.step_min)
        r = c.post("/api/iot/ingest", headers={"X-Sensor-Token": s["ingest_token"]}, json={"readings": batch})
        print(f"{s['code']}: {r.json()}")

    if not args.live:
        return
    mq = None
    if args.mqtt:
        import paho.mqtt.client as mqtt

        mq = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        mq.connect(args.mqtt, 1883)
        mq.loop_start()
    print("live: Ctrl+C to stop")
    while True:
        t = datetime.now(timezone.utc)
        for s in sensors:
            v = signal(s["code"], t, start, rng)
            if mq:
                mq.publish(f"twin/sensors/{s['id']}", json.dumps({"token": s["ingest_token"], "value": v}), qos=1)
            else:
                c.post("/api/iot/ingest", headers={"X-Sensor-Token": s["ingest_token"]}, json={"value": v})
        time.sleep(args.live_sec)


if __name__ == "__main__":
    main()
