"""Two-way sync of the platform's issue register with ACC Issues.

push: issues never sent -> created in ACC (published, default subtype,
      GPS from our location); issues changed since the last sync -> PATCH
      (title, description, status, due date).
pull: ACC issues updated since the last pull -> update linked issues when
      ACC is newer (status/title/description/due date); unknown ACC issues
      are imported as remarks.

Conflicts resolve by last update time. ACC limits: title 100 and description
1000 characters; pushpins / assignees are not mapped (the API does not allow
creating pushpins and offers no user lookup).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.integrations import autodesk_service as svc
from app.models import AutodeskIssueSync, Issue, IssueEvent, Project

# Writing acc_synced_at itself bumps updated_at (DB clock); ignore that echo.
SYNC_SLACK = timedelta(seconds=10)

TO_ACC = {"open": "open", "in_progress": "in_progress", "review": "in_review", "closed": "closed"}
FROM_ACC = {
    "draft": "open", "open": "open", "pending": "open", "in_progress": "in_progress",
    "completed": "review", "in_review": "review", "not_approved": "in_progress", "in_dispute": "in_progress",
    "closed": "closed",
}


def _ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _aware(d: datetime | None) -> datetime | None:
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def _acc_body(issue: Issue, subtype_id: str | None) -> dict:
    body = {
        "title": f"№{issue.number} {issue.title}"[:100],
        "description": (issue.description or "")[:1000],
        "status": TO_ACC[issue.status],
        "dueDate": issue.due_date.isoformat() if issue.due_date else None,
    }
    if subtype_id:
        body["issueSubtypeId"] = subtype_id
        body["published"] = True
        if issue.latitude is not None and issue.longitude is not None:
            body["gpsCoordinates"] = {"latitude": issue.latitude, "longitude": issue.longitude}
    return body


def run_sync(db: Session, project: Project) -> dict:
    cfg = db.get(AutodeskIssueSync, project.id)
    if cfg is None:
        raise ValueError("Синхронизация с ACC не настроена для проекта")
    client = svc.client_factory()
    token = svc.user_token(db, cfg.user_id, client)
    now = datetime.now(timezone.utc)
    stats = {"pushed_new": 0, "pushed_updates": 0, "pulled_updates": 0, "imported": 0}

    # ---- pull first, so fresher ACC edits are not overwritten by the push
    since = cfg.last_pulled_at.isoformat().replace("+00:00", "Z") if cfg.last_pulled_at else None
    remote = client.list_issues(token, cfg.aps_project_id, since)
    by_acc = {i.acc_issue_id: i for i in db.query(Issue).filter(Issue.project_id == project.id, Issue.acc_issue_id.isnot(None)).all()}
    for r in remote:
        if r.get("deleted"):
            continue
        updated = _ts(r.get("updatedAt"))
        status = FROM_ACC.get(r.get("status", "open"), "open")
        due = date.fromisoformat(r["dueDate"][:10]) if r.get("dueDate") else None
        local = by_acc.get(r["id"])
        if local is None:
            number = (db.query(func.max(Issue.number)).filter(Issue.project_id == project.id).scalar() or 0) + 1
            gps = r.get("gpsCoordinates") or {}
            local = Issue(project_id=project.id, number=number, kind="remark", title=(r.get("title") or "ACC")[:300],
                          description=r.get("description"), status=status, due_date=due, acc_issue_id=r["id"],
                          acc_synced_at=now, latitude=gps.get("latitude"), longitude=gps.get("longitude"),
                          closed_at=now if status == "closed" else None)
            db.add(local)
            db.flush()
            db.add(IssueEvent(issue_id=local.id, kind="created", data={"source": "ACC", "displayId": r.get("displayId")}))
            stats["imported"] += 1
            continue
        local_changed = _aware(local.updated_at) or datetime.min.replace(tzinfo=timezone.utc)
        if updated and updated > max(local_changed, _aware(local.acc_synced_at) or datetime.min.replace(tzinfo=timezone.utc)):
            changes = {}
            if local.status != status:
                changes["status"] = {"from": local.status, "to": status}
                local.status = status
                local.closed_at = now if status == "closed" else None
            if local.due_date != due:
                local.due_date = due
            if changes:
                db.add(IssueEvent(issue_id=local.id, kind="status", data={**changes["status"], "source": "ACC"}))
            local.acc_synced_at = now
            stats["pulled_updates"] += 1

    # ---- push
    for issue in db.query(Issue).filter(Issue.project_id == project.id).all():
        if issue.acc_issue_id is None:
            created = client.create_issue(token, cfg.aps_project_id, _acc_body(issue, cfg.subtype_id))
            issue.acc_issue_id = created["id"]
            issue.acc_synced_at = now
            stats["pushed_new"] += 1
        elif _aware(issue.updated_at) and _aware(issue.acc_synced_at) and \
                _aware(issue.updated_at) > _aware(issue.acc_synced_at) + SYNC_SLACK:
            client.update_issue(token, cfg.aps_project_id, issue.acc_issue_id, _acc_body(issue, None))
            issue.acc_synced_at = now
            stats["pushed_updates"] += 1

    cfg.last_pulled_at = now
    cfg.last_result = {**stats, "at": now.isoformat()}
    db.commit()
    return stats
