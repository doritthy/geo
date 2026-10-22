"""IoT core: ingest readings, evaluate thresholds, raise alerts.

Gateways send readings over HTTP (`POST /api/iot/ingest`) or MQTT (topic
`twin/sensors/<sensor id>`, see app/iot_mqtt.py); both end up in `ingest()`.
State per sensor: none -> ok | warn | alarm from the latest reading and the
thresholds; "stale" is derived on read when no reading arrived for
`stale_minutes`. A change of state is logged in `sensor_alerts`, and going to
warn/alarm notifies the project's editors (push + email).
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Project, ProjectMember, Sensor, SensorAlert, SensorReading, User

logger = logging.getLogger(__name__)

KIND_LABELS = {
    "temperature": "Температура бетона", "strain": "Деформация", "tilt": "Крен", "displacement": "Смещение",
    "humidity": "Влажность", "other": "Датчик",
}
LEVEL_LABELS = {"ok": "в норме", "warn": "предупреждение", "alarm": "АВАРИЯ"}
MAX_BATCH = 10_000
NOTIFY_WINDOW = timedelta(hours=1)


def new_token() -> str:
    return secrets.token_urlsafe(24)


_RANK = {"none": 0, "ok": 1, "warn": 2, "alarm": 3}
HYSTERESIS = 0.02  # leaving a state needs a 2 % margin inside the threshold


def _level(sensor: Sensor, value: float, margin: float = 0.0) -> str:
    def out(lo, hi):
        return (lo is not None and value < lo + margin * max(abs(lo), 1.0)) or \
               (hi is not None and value > hi - margin * max(abs(hi), 1.0))
    if out(sensor.alarm_min, sensor.alarm_max):
        return "alarm"
    if out(sensor.warn_min, sensor.warn_max):
        return "warn"
    return "ok"


def evaluate(sensor: Sensor, value: float, current: str | None = None) -> str:
    """Threshold level; with `current`, de-escalation uses hysteresis so a
    noisy signal hovering at a threshold does not flap."""
    level = _level(sensor, value)
    if current and _RANK.get(current, 0) > _RANK[level]:
        held = _level(sensor, value, HYSTERESIS)
        if _RANK[held] > _RANK[level]:
            return held if _RANK[held] <= _RANK[current] else current
    return level


def effective_state(sensor: Sensor, now: datetime | None = None) -> str:
    if sensor.last_at is None:
        return "none"
    now = now or datetime.now(timezone.utc)
    if now - sensor.last_at > timedelta(minutes=sensor.stale_minutes):
        return "stale"
    return sensor.state


def _parse_ts(ts) -> datetime:
    if ts is None:
        return datetime.now(timezone.utc)
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts / 1000 if ts > 1e11 else ts, tz=timezone.utc)  # ms or s epoch
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def ingest(db: Session, sensor: Sensor, readings: list[dict], notify=None) -> int:
    """Stores readings ({value, ts?}), updates the sensor's latest value and
    state, logs state changes. `notify(sensor, level, value)` is called for
    transitions into warn/alarm. Returns the number of readings stored."""
    rows = []
    for r in readings[:MAX_BATCH]:
        try:
            value = float(r["value"])
        except (KeyError, TypeError, ValueError):
            continue
        if value != value or value in (float("inf"), float("-inf")):
            continue
        rows.append({"sensor_id": sensor.id, "ts": _parse_ts(r.get("ts")), "value": value})
    if not rows:
        return 0
    # Same timestamp twice (gateway retry) -> keep the latest value.
    db.execute(insert(SensorReading).values(rows).on_conflict_do_update(
        index_elements=["sensor_id", "ts"], set_={"value": insert(SensorReading).excluded.value}))
    # Walk new readings in time order so excursions inside a batch (a gateway
    # flushing its offline buffer) are logged, not just the final value.
    # Only recent transitions notify people; old ones are history.
    recent = datetime.now(timezone.utc) - NOTIFY_WINDOW
    state = sensor.state
    last = None
    for r in sorted(rows, key=lambda r: r["ts"]):
        if sensor.last_at is not None and r["ts"] < sensor.last_at:
            continue
        level = evaluate(sensor, r["value"], state)
        if level != state and not (state == "none" and level == "ok"):
            name = KIND_LABELS.get(sensor.kind, "Датчик")
            msg = f"{name} «{sensor.name}»: {r['value']:g} {sensor.unit} — {LEVEL_LABELS[level]}".replace("  ", " ")
            db.add(SensorAlert(sensor_id=sensor.id, ts=r["ts"], level=level, value=r["value"], message=msg))
            if level in ("warn", "alarm") and notify is not None and r["ts"] >= recent:
                notify(sensor, level, r["value"], msg)
        state, last = level, r
    if last is not None:
        sensor.state = state
        sensor.last_value = last["value"]
        sensor.last_at = last["ts"]
    db.commit()
    return len(rows)


def project_editor_ids(db: Session, project_id) -> list:
    project = db.get(Project, project_id)
    if project is None:
        return []
    ids = {m.user_id for m in db.query(ProjectMember).filter(ProjectMember.project_id == project_id,
                                                             ProjectMember.role.in_(("owner", "editor"))).all()}
    admins = {u.id for u in db.query(User).filter(User.organization_id == project.organization_id, User.role == "admin").all()}
    return list(ids | admins)
