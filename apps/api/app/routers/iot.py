"""IoT sensors: registry, readings, alerts, and token-authenticated ingestion
for gateways (HTTP; MQTT goes through app/iot_mqtt.py)."""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import iot
from app.db import get_db
from app.deps import _require_project_role, get_project_scoped_or_404, project_editor, project_viewer
from app.models import Project, SceneAsset, Sensor, SensorAlert, User
from app.notify import send_email
from app.push import send_push
from app.security import get_current_user

router = APIRouter(tags=["iot"])

SensorKind = str


class SensorIn(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    kind: str = "other"
    unit: str = ""
    longitude: float | None = None
    latitude: float | None = None
    height: float | None = None
    asset_id: uuid.UUID | None = None
    element_global_id: str | None = None
    warn_min: float | None = None
    warn_max: float | None = None
    alarm_min: float | None = None
    alarm_max: float | None = None
    stale_minutes: int = Field(60, ge=1, le=60 * 24 * 30)


class SensorPatch(BaseModel):
    name: str | None = None
    kind: str | None = None
    unit: str | None = None
    longitude: float | None = None
    latitude: float | None = None
    height: float | None = None
    element_global_id: str | None = None
    warn_min: float | None = None
    warn_max: float | None = None
    alarm_min: float | None = None
    alarm_max: float | None = None
    stale_minutes: int | None = Field(None, ge=1, le=60 * 24 * 30)


class SensorOut(SensorIn):
    id: uuid.UUID
    project_id: uuid.UUID
    last_value: float | None
    last_at: datetime | None
    state: str  # none | ok | warn | alarm | stale
    created_at: datetime


class SensorWithToken(SensorOut):
    ingest_token: str


class Reading(BaseModel):
    value: float
    ts: datetime | float | None = None


class IngestBody(BaseModel):
    sensor_id: uuid.UUID | None = None
    readings: list[Reading] = Field(default_factory=list, max_length=iot.MAX_BATCH)
    value: float | None = None
    ts: datetime | float | None = None


def _out(s: Sensor, with_token: bool = False) -> SensorOut:
    data = {c: getattr(s, c) for c in SensorOut.model_fields if c != "state"}
    data["state"] = iot.effective_state(s)
    if with_token:
        return SensorWithToken(**data, ingest_token=s.ingest_token)
    return SensorOut(**data)


def _validate(s: SensorIn | SensorPatch) -> None:
    for lo, hi in (("warn_min", "warn_max"), ("alarm_min", "alarm_max")):
        a, b = getattr(s, lo), getattr(s, hi)
        if a is not None and b is not None and a > b:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{lo} больше {hi}")
    if s.kind is not None and s.kind not in iot.KIND_LABELS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неизвестный тип датчика")


def make_notifier(bg: BackgroundTasks | None, db: Session):
    def notify(sensor: Sensor, level: str, value: float, msg: str) -> None:
        ids = iot.project_editor_ids(db, sensor.project_id)
        if not ids:
            return
        path = f"/twin/{sensor.project_id}?sensor={sensor.id}"
        emails = [u.email for u in db.query(User).filter(User.id.in_(ids)).all()]
        title = "Авария датчика" if level == "alarm" else "Предупреждение датчика"
        if bg is not None:
            bg.add_task(send_push, ids, title, msg, path)
            bg.add_task(send_email, emails, f"[{title}] {sensor.name}", f"{msg}\n")
        else:  # MQTT bridge: no request context
            send_push(ids, title, msg, path)
            send_email(emails, f"[{title}] {sensor.name}", f"{msg}\n")
    return notify


@router.get("/api/projects/{project_id}/sensors", response_model=list[SensorOut])
def list_sensors(project: Project = Depends(project_viewer), db: Session = Depends(get_db)):
    rows = db.query(Sensor).filter(Sensor.project_id == project.id).order_by(Sensor.name).all()
    return [_out(s) for s in rows]


@router.post("/api/projects/{project_id}/sensors", response_model=SensorWithToken, status_code=status.HTTP_201_CREATED)
def create_sensor(body: SensorIn, project: Project = Depends(project_editor), db: Session = Depends(get_db)):
    _validate(body)
    if db.query(Sensor).filter(Sensor.project_id == project.id, Sensor.code == body.code).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Датчик с таким кодом уже есть")
    if body.asset_id is not None:
        asset = db.get(SceneAsset, body.asset_id)
        if asset is None or asset.project_id != project.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    s = Sensor(project_id=project.id, ingest_token=iot.new_token(), **body.model_dump())
    db.add(s)
    db.commit()
    db.refresh(s)
    return _out(s, with_token=True)


def _sensor_for(sensor_id: uuid.UUID, db: Session, user: User, editor: bool = False) -> Sensor:
    s: Sensor = get_project_scoped_or_404(Sensor, sensor_id, db, user)
    if editor:
        _require_project_role(s.project_id, "editor", db, user)
    return s


@router.get("/api/sensors/{sensor_id}", response_model=SensorWithToken)
def get_sensor(sensor_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    s = _sensor_for(sensor_id, db, user)
    try:
        _require_project_role(s.project_id, "editor", db, user)
        return _out(s, with_token=True)
    except HTTPException:  # viewers do not see the ingest secret
        return SensorWithToken(**_out(s).model_dump(), ingest_token="")


@router.patch("/api/sensors/{sensor_id}", response_model=SensorOut)
def update_sensor(sensor_id: uuid.UUID, body: SensorPatch, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    s = _sensor_for(sensor_id, db, user, editor=True)
    _validate(body)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    if s.last_value is not None:  # thresholds changed -> re-evaluate silently
        s.state = iot.evaluate(s, s.last_value)
    db.commit()
    db.refresh(s)
    return _out(s)


@router.post("/api/sensors/{sensor_id}/rotate-token", response_model=SensorWithToken)
def rotate_token(sensor_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    s = _sensor_for(sensor_id, db, user, editor=True)
    s.ingest_token = iot.new_token()
    db.commit()
    return _out(s, with_token=True)


@router.delete("/api/sensors/{sensor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sensor(sensor_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    s = _sensor_for(sensor_id, db, user, editor=True)
    db.delete(s)
    db.commit()


@router.get("/api/sensors/{sensor_id}/readings")
def sensor_readings(
    sensor_id: uuid.UUID,
    hours: float = 24,
    points: int = 500,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Readings of the last `hours`, averaged into at most `points` buckets
    (min/max kept so short spikes stay visible)."""
    s = _sensor_for(sensor_id, db, user)
    hours = min(max(hours, 0.1), 24 * 366)
    points = min(max(points, 10), 5000)
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    bucket = max(1, int(hours * 3600 / points))
    rows = db.execute(text(
        """
        SELECT date_bin(make_interval(secs => :b), ts, TIMESTAMPTZ '2000-01-01') AS t,
               avg(value) AS v, min(value) AS lo, max(value) AS hi
        FROM sensor_readings WHERE sensor_id = :id AND ts >= :since
        GROUP BY 1 ORDER BY 1
        """
    ), {"b": bucket, "id": s.id, "since": since}).all()
    return {
        "sensor_id": str(s.id), "unit": s.unit, "bucket_seconds": bucket,
        "thresholds": {k: getattr(s, k) for k in ("warn_min", "warn_max", "alarm_min", "alarm_max")},
        "points": [{"ts": t.isoformat(), "value": v, "min": lo, "max": hi} for t, v, lo, hi in rows],
    }


@router.get("/api/projects/{project_id}/sensor-alerts")
def sensor_alerts(limit: int = 100, project: Project = Depends(project_viewer), db: Session = Depends(get_db)):
    rows = (
        db.query(SensorAlert, Sensor.name)
        .join(Sensor, Sensor.id == SensorAlert.sensor_id)
        .filter(Sensor.project_id == project.id)
        .order_by(SensorAlert.ts.desc(), SensorAlert.id.desc())
        .limit(min(max(limit, 1), 1000))
        .all()
    )
    return [{"id": a.id, "sensor_id": str(a.sensor_id), "sensor_name": name, "ts": a.ts.isoformat(), "level": a.level,
             "value": a.value, "message": a.message} for a, name in rows]


@router.post("/api/iot/ingest")
def ingest(
    body: IngestBody,
    bg: BackgroundTasks,
    x_sensor_token: str = Header(..., alias="X-Sensor-Token"),
    db: Session = Depends(get_db),
):
    """Gateway endpoint (no user session): the per-sensor token identifies the
    sensor; `sensor_id` is optional and only cross-checked. Accepts one
    reading (`value`, `ts`) or a batch (`readings`). `ts`: ISO 8601 or Unix
    epoch (s or ms); omitted = now."""
    s = db.query(Sensor).filter(Sensor.ingest_token == x_sensor_token).first()
    if s is None or (body.sensor_id is not None and body.sensor_id != s.id):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid sensor token")
    readings = [r.model_dump() for r in body.readings]
    if body.value is not None:
        readings.append({"value": body.value, "ts": body.ts})
    if not readings:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No readings")
    stored = iot.ingest(db, s, readings, notify=make_notifier(bg, db))
    return {"stored": stored, "state": iot.effective_state(s)}
