"""Project dashboard (дашборд прогресса для заказчика): schedule progress
and SPI, issues by status / overdue / assignee, latest deviation analysis,
scans timeline, model versions, IoT sensor states."""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import project_viewer
from app import iot
from app.models import Analysis, Document, Issue, Project, ScheduleTask, SceneAsset, Sensor, User
from app.security import get_current_user
from app.twin.schedule import metrics

router = APIRouter(tags=["dashboard"])


@router.get("/api/projects/{project_id}/dashboard")
def dashboard(project: Project = Depends(project_viewer), db: Session = Depends(get_db)) -> dict:
    today = date.today()
    tasks = db.query(ScheduleTask).filter(ScheduleTask.project_id == project.id).all()

    issues = db.query(Issue).filter(Issue.project_id == project.id).all()
    by_status: dict[str, int] = {}
    for i in issues:
        by_status[i.status] = by_status.get(i.status, 0) + 1
    open_issues = [i for i in issues if i.status != "closed"]
    overdue = [i for i in open_issues if i.due_date and i.due_date < today]
    per_assignee: dict = {}
    for i in open_issues:
        per_assignee[i.assignee_id] = per_assignee.get(i.assignee_id, 0) + 1
    names = {u.id: (u.full_name or u.email) for u in db.query(User).filter(User.id.in_([k for k in per_assignee if k])).all()}

    last_dev = (
        db.query(Analysis)
        .filter(Analysis.project_id == project.id, Analysis.kind == "deviation", Analysis.status == "ready")
        .order_by(Analysis.created_at.desc()).first()
    )
    assets = db.query(SceneAsset).filter(SceneAsset.project_id == project.id).all()
    scans = sorted(
        ({"name": a.name, "captured_at": a.captured_at.isoformat(), "kind": a.kind}
         for a in assets if a.kind != "bim" and a.captured_at and not a.stats.get("analysis_id")),
        key=lambda s: s["captured_at"],
    )
    groups: dict = {}
    for a in assets:
        if a.kind == "bim":
            g = groups.setdefault(str(a.version_group), {"name": a.name, "versions": 0, "elements": 0})
            g["versions"] += 1
            g["elements"] = max(g["elements"], a.stats.get("element_count", 0))

    created_30 = sum(1 for i in issues if (today - i.created_at.date()).days <= 30)
    closed_30 = sum(1 for i in issues if i.closed_at and (today - i.closed_at.date()).days <= 30)

    sensors = db.query(Sensor).filter(Sensor.project_id == project.id).all()
    sensor_states: dict[str, int] = {}
    for sn in sensors:
        st = iot.effective_state(sn)
        sensor_states[st] = sensor_states.get(st, 0) + 1

    return {
        "project": {"id": str(project.id), "name": project.name, "description": project.description},
        "sensors": {
            "total": len(sensors), "by_state": sensor_states,
            "attention": [{"id": str(sn.id), "name": sn.name, "state": iot.effective_state(sn), "value": sn.last_value, "unit": sn.unit}
                          for sn in sensors if iot.effective_state(sn) in ("alarm", "warn", "stale")][:10],
        },
        "schedule": metrics(tasks, today) if tasks else None,
        "issues": {
            "total": len(issues), "open": len(open_issues), "overdue": len(overdue), "by_status": by_status,
            "by_assignee": sorted(
                ({"name": names.get(k, "не назначен") if k else "не назначен", "count": v} for k, v in per_assignee.items()),
                key=lambda r: -r["count"],
            ),
            "created_30d": created_30, "closed_30d": closed_30,
            "overdue_list": [{"id": str(i.id), "number": i.number, "title": i.title, "due_date": i.due_date.isoformat()}
                             for i in sorted(overdue, key=lambda i: i.due_date)[:10]],
        },
        "quality": (
            {"analysis_id": str(last_dev.id), "date": last_dev.created_at.date().isoformat(),
             "within_tolerance": last_dev.result["histogram"]["within_tolerance"],
             "tolerance_cm": last_dev.result["tolerances"][1] * 100,
             "p95_mm": (last_dev.result["histogram"]["p95_abs"] or 0) * 1000,
             "worst": [{"name": e["name"], "p95_mm": e["p95_abs"] * 1000, "mean_mm": e["mean"] * 1000}
                       for e in last_dev.result.get("elements", []) if e["points"] >= 20][:5]}
            if last_dev else None
        ),
        "models": list(groups.values()),
        "scans": scans,
        "documents": db.query(func.count(Document.id)).filter(Document.project_id == project.id).scalar(),
    }


@router.get("/api/portfolio")
def portfolio(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Portfolio analytics: the same key figures for every project the user
    can see, side by side (schedule, issues, quality, sensors, models)."""
    from app.routers.projects import list_projects

    today = date.today()
    rows = []
    for p in list_projects(db, user):
        tasks = db.query(ScheduleTask).filter(ScheduleTask.project_id == p.id).all()
        m = metrics(tasks, today) if tasks else None
        open_q = db.query(Issue).filter(Issue.project_id == p.id, Issue.status != "closed")
        dev = (
            db.query(Analysis)
            .filter(Analysis.project_id == p.id, Analysis.kind == "deviation", Analysis.status == "ready")
            .order_by(Analysis.created_at.desc()).first()
        )
        states: dict[str, int] = {}
        for sn in db.query(Sensor).filter(Sensor.project_id == p.id).all():
            st = iot.effective_state(sn)
            states[st] = states.get(st, 0) + 1
        last_scan = (
            db.query(func.max(SceneAsset.captured_at))
            .filter(SceneAsset.project_id == p.id, SceneAsset.kind != "bim").scalar()
        )
        rows.append({
            "id": str(p.id), "name": p.name,
            "schedule": None if m is None else {
                "planned_percent": m.get("planned_percent"), "actual_percent": m.get("actual_percent"), "spi": m.get("spi"),
                "finish": m.get("finish"), "forecast_finish": m.get("forecast_finish"), "delay_days": m.get("delay_days"),
                "late_tasks": m.get("late_tasks"), "tasks": m.get("tasks"),
            },
            "issues": {
                "open": open_q.count(),
                "overdue": open_q.filter(Issue.due_date.isnot(None), Issue.due_date < today).count(),
            },
            "quality": None if dev is None else {
                "within_tolerance": dev.result["histogram"]["within_tolerance"],
                "tolerance_cm": dev.result["tolerances"][1] * 100,
                "date": dev.created_at.date().isoformat(),
            },
            "sensors": states,
            "models": db.query(SceneAsset).filter(SceneAsset.project_id == p.id, SceneAsset.kind == "bim").count(),
            "last_scan": last_scan.isoformat() if last_scan else None,
        })
    return {"date": today.isoformat(), "projects": rows}
