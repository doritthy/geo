"""IoT: sensor registry, HTTP/MQTT ingestion with per-sensor tokens,
threshold states and alerts (with notifications), downsampled readings."""

import json
from datetime import datetime, timedelta, timezone

from tests.test_issues import _admin, _worker


def _sensor(client, h, pid, **kw):
    body = {"code": "T-01", "name": "Плита 3, ось Б", "kind": "temperature", "unit": "°C",
            "warn_min": 5, "warn_max": 60, "alarm_min": 0, "alarm_max": 75, **kw}
    r = client.post(f"/api/projects/{pid}/sensors", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_sensor_ingest_states_alerts(client, monkeypatch):
    from app import push

    box: list = []
    monkeypatch.setattr(push, "outbox", box)
    h = _admin(client)
    pid = client.post("/api/projects", json={"name": "ЖК"}, headers=h).json()["id"]
    worker_id, wh = _worker(client, h, pid)
    client.post("/api/push/subscriptions", headers=wh, json={"endpoint": "https://p/1", "keys": {"p256dh": "k", "auth": "a"}})
    s = _sensor(client, h, pid)
    token = s["ingest_token"]
    assert s["state"] == "none" and len(token) > 20
    assert client.post(f"/api/projects/{pid}/sensors", headers=h, json={"code": "T-01", "name": "dup"}).status_code == 409
    assert client.post(f"/api/projects/{pid}/sensors", headers=h,
                       json={"code": "X", "name": "x", "warn_min": 5, "warn_max": 1}).status_code == 400

    # Bad token -> 401; viewer-level readers never see the token.
    assert client.post("/api/iot/ingest", headers={"X-Sensor-Token": "nope"}, json={"value": 1}).status_code == 401
    now = datetime.now(timezone.utc)
    batch = [{"value": 20 + i * 0.5, "ts": (now - timedelta(minutes=60 - i)).isoformat()} for i in range(60)]
    r = client.post("/api/iot/ingest", headers={"X-Sensor-Token": token}, json={"readings": batch})
    assert r.json() == {"stored": 60, "state": "ok"}
    assert box == []  # ok is not notified

    r = client.post("/api/iot/ingest", headers={"X-Sensor-Token": token}, json={"value": 68.0})
    assert r.json()["state"] == "warn"
    r = client.post("/api/iot/ingest", headers={"X-Sensor-Token": token}, json={"value": 80.0, "ts": now.timestamp() + 5})
    assert r.json()["state"] == "alarm"
    titles = [p["title"] for _, p in box]
    assert titles == ["Предупреждение датчика", "Авария датчика"]  # editor (worker) notified on each escalation
    assert box[-1][1]["url"] == f"/twin/{pid}?sensor={s['id']}"

    alerts = client.get(f"/api/projects/{pid}/sensor-alerts", headers=h).json()
    assert [a["level"] for a in alerts] == ["alarm", "warn"]  # initial none -> ok is not an event
    assert "АВАРИЯ" in alerts[0]["message"] and "Плита 3" in alerts[0]["message"]

    listed = client.get(f"/api/projects/{pid}/sensors", headers=h).json()
    assert listed[0]["state"] == "alarm" and listed[0]["last_value"] == 80.0 and "ingest_token" not in listed[0]

    # Downsampled series keeps spikes via min/max.
    rd = client.get(f"/api/sensors/{s['id']}/readings", headers=h, params={"hours": 2, "points": 12}).json()
    assert rd["bucket_seconds"] == 600 and 6 <= len(rd["points"]) <= 14
    assert max(p["max"] for p in rd["points"]) == 80.0
    assert rd["thresholds"]["alarm_max"] == 75

    # Raising thresholds re-evaluates without a new reading.
    p = client.patch(f"/api/sensors/{s['id']}", headers=h, json={"alarm_max": 90, "warn_max": 85}).json()
    assert p["state"] == "ok"
    # Rotating the token invalidates the old one.
    new = client.post(f"/api/sensors/{s['id']}/rotate-token", headers=h).json()["ingest_token"]
    assert client.post("/api/iot/ingest", headers={"X-Sensor-Token": token}, json={"value": 1}).status_code == 401
    assert client.post("/api/iot/ingest", headers={"X-Sensor-Token": new}, json={"value": 21}).status_code == 200


def test_batch_logs_excursions_but_notifies_only_recent(client, monkeypatch):
    from app import push

    box: list = []
    monkeypatch.setattr(push, "outbox", box)
    h = _admin(client)
    pid = client.post("/api/projects", json={"name": "ЖК"}, headers=h).json()["id"]
    client.post("/api/push/subscriptions", headers=h, json={"endpoint": "https://p/1", "keys": {"p256dh": "k", "auth": "a"}})
    s = _sensor(client, h, pid)
    now = datetime.now(timezone.utc)
    # Offline buffer: a day-old excursion to 65 °C, back to normal since.
    vals = [(48, 20), (30, 65), (29, 66), (28, 40), (0.2, 22)]
    batch = [{"value": v, "ts": (now - timedelta(hours=age)).isoformat()} for age, v in vals]
    r = client.post("/api/iot/ingest", headers={"X-Sensor-Token": s["ingest_token"]}, json={"readings": batch})
    assert r.json()["state"] == "ok"
    alerts = client.get(f"/api/projects/{pid}/sensor-alerts", headers=h).json()
    assert [a["level"] for a in alerts] == ["ok", "warn"] and alerts[1]["value"] == 65
    # The admin is an editor here, but a day-old warning is history, not a page.
    assert box == []
    # Readings older than the latest one never move the state back.
    client.post("/api/iot/ingest", headers={"X-Sensor-Token": s["ingest_token"]},
                json={"value": 99, "ts": (now - timedelta(hours=5)).isoformat()})
    assert client.get(f"/api/sensors/{s['id']}", headers=h).json()["state"] == "ok"


def test_sensor_stale_and_mqtt_bridge(client):
    from app.db import SessionLocal
    from app.iot_mqtt import handle_message
    from app.models import Sensor

    h = _admin(client)
    pid = client.post("/api/projects", json={"name": "ЖК"}, headers=h).json()["id"]
    s = _sensor(client, h, pid, stale_minutes=5)
    topic = f"twin/sensors/{s['id']}"
    old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    assert handle_message(topic, json.dumps({"token": "bad", "value": 1}).encode()) == 0
    assert handle_message(topic, b"not json") == 0
    assert handle_message("twin/sensors/xyz", b"{}") == 0
    assert handle_message(topic, json.dumps({"token": s["ingest_token"], "value": 22.5, "ts": old}).encode()) == 1
    got = client.get(f"/api/sensors/{s['id']}", headers=h).json()
    assert got["state"] == "stale" and got["last_value"] == 22.5  # last reading older than stale_minutes
    n = handle_message(topic, json.dumps({"token": s["ingest_token"], "readings": [{"value": 23}, {"value": "x"}]}).encode())
    assert n == 1
    assert client.get(f"/api/sensors/{s['id']}", headers=h).json()["state"] == "ok"
    db = SessionLocal()
    assert db.get(Sensor, __import__("uuid").UUID(s["id"])).last_value == 23
    db.close()


def test_threshold_hysteresis():
    from app.iot import evaluate
    from app.models import Sensor

    s = Sensor(warn_max=55.0, alarm_max=70.0)
    assert evaluate(s, 55.5) == "warn"
    assert evaluate(s, 54.5, "warn") == "warn"  # within 2 % of 55 -> still warn
    assert evaluate(s, 53.5, "warn") == "ok"
    assert evaluate(s, 69.0, "alarm") == "alarm"
    assert evaluate(s, 60.0, "alarm") == "warn"
    assert evaluate(s, 54.0, "alarm") == "warn"  # held at the warning boundary, not at alarm
    assert evaluate(s, 50.0, "alarm") == "ok"
