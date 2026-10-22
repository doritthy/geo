"""Project dashboard (дашборд прогресса для заказчика): schedule progress
and SPI, issues by status / overdue / assignee, latest deviation analysis,
scans timeline, model versions."""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import project_viewer
from app.models import Analysis, Document, Issue, Project, ScheduleTask, SceneAsset, User
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

    return {
        "project": {"id": str(project.id), "name": project.name, "description": project.description},
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
