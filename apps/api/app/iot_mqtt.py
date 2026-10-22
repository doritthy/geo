"""MQTT -> IoT bridge (run as `python -m app.iot_mqtt`).

Topic:   twin/sensors/<sensor id>
Payload: JSON {"token": "<ingest token>", "value": 21.5, "ts": "2026-05-20T10:00:00Z"}
         or {"token": ..., "readings": [{"value": .., "ts": ..}, ...]}

The per-sensor token is checked exactly as for HTTP ingestion, so the broker
can stay simple (still restrict it to the internal network or enable
username/password: MQTT_USERNAME / MQTT_PASSWORD).
"""

from __future__ import annotations

import json
import logging
import os
import signal
import uuid

from app.db import SessionLocal
from app.models import Sensor

logger = logging.getLogger(__name__)
TOPIC = "twin/sensors/+"


def handle_message(topic: str, payload: bytes) -> int:
    """Returns the number of readings stored (0 if rejected)."""
    from app import iot
    from app.routers.iot import make_notifier

    try:
        sensor_id = uuid.UUID(topic.rsplit("/", 1)[-1])
        data = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        logger.warning("MQTT: bad topic or payload on %s", topic)
        return 0
    if not isinstance(data, dict):
        return 0
    db = SessionLocal()
    try:
        sensor = db.get(Sensor, sensor_id)
        if sensor is None or not data.get("token") or data.get("token") != sensor.ingest_token:
            logger.warning("MQTT: rejected message for %s (unknown sensor or bad token)", sensor_id)
            return 0
        readings = list(data.get("readings") or [])
        if "value" in data:
            readings.append({"value": data["value"], "ts": data.get("ts")})
        return iot.ingest(db, sensor, readings, notify=make_notifier(None, db))
    finally:
        db.close()


def main() -> None:
    import paho.mqtt.client as mqtt

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    host = os.environ.get("MQTT_HOST", "localhost")
    port = int(os.environ.get("MQTT_PORT", "1883"))
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"twin-bridge-{os.getpid()}")
    if os.environ.get("MQTT_USERNAME"):
        client.username_pw_set(os.environ["MQTT_USERNAME"], os.environ.get("MQTT_PASSWORD"))

    def on_connect(c, _userdata, _flags, reason, _props):
        logger.info("MQTT connected to %s:%s (%s); subscribing %s", host, port, reason, TOPIC)
        c.subscribe(TOPIC, qos=1)

    def on_message(_c, _userdata, msg):
        try:
            handle_message(msg.topic, msg.payload)
        except Exception:  # noqa: BLE001 -- one bad message must not stop the bridge
            logger.exception("MQTT: failed to handle message on %s", msg.topic)

    client.on_connect = on_connect
    client.on_message = on_message
    signal.signal(signal.SIGTERM, lambda *_: client.disconnect())
    client.connect(host, port, keepalive=60)
    client.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    main()
