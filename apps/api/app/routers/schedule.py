"""4D план-факт: schedule import, task ↔ BIM element links, progress, SPI,
element status for 3D colouring, progress from a deviation analysis."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import _require_project_role, get_project_scoped_or_404, project_editor, project_viewer
from app.models import Analysis, BimElement, Project, ScheduleTask, ScheduleTaskElement, SceneAsset, User
from app.security import get_current_user
from app.twin.schedule import metrics, parse_schedule, planned_percent, task_status

router = APIRouter(tags=["schedule"])


class TaskOut(BaseModel):
    id: uuid.UUID
    external_id: str | None
    wbs: str | None
    name: str
    parent_id: uuid.UUID | None
    is_summary: bool
    start_date: date
    finish_date: date
    percent_complete: float
    planned_percent: float
    cost: float | None
    status: str
    element_count: int


class ScheduleOut(BaseModel):
    tasks: list[TaskOut]
    metrics: dict


class TaskUpdate(BaseModel):
    name: str | None = None
    start_date: date | None = None
    finish_date: date | None = None
    percent_complete: float | None = Field(default=None, ge=0, le=100)
    cost: float | None = None


class LinkRequest(BaseModel):
    asset_id: uuid.UUID
    global_ids: list[str] | None = None
    ifc_type: str | None = None
    storey: str | None = None
    q: str | None = None


class ProgressFromAnalysis(BaseModel):
    analysis_id: uuid.UUID
    min_points: int = Field(default=20, ge=1)


def _tasks(db: Session, project_id: uuid.UUID) -> list[ScheduleTask]:
    return db.query(ScheduleTask).filter(ScheduleTask.project_id == project_id).order_by(ScheduleTask.sort_order).all()


def _rollup(tasks: list[ScheduleTask]) -> None:
    """Summary task % = duration-weighted mean of its children (in memory)."""
    children: dict = {}
    for t in tasks:
        if t.parent_id:
            children.setdefault(t.parent_id, []).append(t)
    by_id = {t.id: t for t in tasks}

    def visit(t: ScheduleTask) -> tuple[float, float]:
        kids = children.get(t.id)
        dur = float((t.finish_date - t.start_date).days + 1)
        if not kids:
            return dur, dur * t.percent_complete
        tw = tp = 0.0
        for k in kids:
            w, p = visit(k)
            tw += w
            tp += p
        t.percent_complete = tp / tw if tw else 0.0
        return tw, tp

    for t in tasks:
        if t.parent_id is None or t.parent_id not in by_id:
            visit(t)


@router.post("/api/projects/{project_id}/schedule/import", response_model=ScheduleOut)
def import_schedule(file: UploadFile = File(...), replace: bool = Form(True), project: Project = Depends(project_editor),
                    db: Session = Depends(get_db)):
    try:
        parsed = parse_schedule(file.filename or "", file.file.read())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 -- malformed XML / spreadsheet
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Не удалось прочитать график: {exc}") from exc

    # Keep element links of tasks that survive a re-import (matched by external id / name).
    old_links: dict[str, list[tuple]] = {}
    if replace:
        for t in _tasks(db, project.id):
            key = t.external_id or t.name
            old_links[key] = [(l.version_group, l.global_id) for l in
                              db.query(ScheduleTaskElement).filter(ScheduleTaskElement.task_id == t.id).all()]
        db.query(ScheduleTask).filter(ScheduleTask.project_id == project.id).delete()
        db.flush()
    stack: list[tuple[int, uuid.UUID]] = []
    base = 0 if replace else (db.query(func.max(ScheduleTask.sort_order)).filter(ScheduleTask.project_id == project.id).scalar() or 0)
    for i, p in enumerate(parsed):
        while stack and stack[-1][0] >= p.outline_level:
            stack.pop()
        t = ScheduleTask(project_id=project.id, external_id=p.external_id, wbs=p.wbs, name=p.name,
                         parent_id=stack[-1][1] if stack else None, is_summary=p.is_summary,
                         start_date=p.start, finish_date=max(p.finish, p.start),
                         percent_complete=min(max(p.percent, 0.0), 100.0), cost=p.cost, sort_order=base + i + 1)
        db.add(t)
        db.flush()
        stack.append((p.outline_level, t.id))
        for vg, gid in old_links.get(p.external_id or p.name, []):
            db.add(ScheduleTaskElement(task_id=t.id, version_group=vg, global_id=gid))
    db.commit()
    return get_schedule(None, project, db)


@router.get("/api/projects/{project_id}/schedule", response_model=ScheduleOut)
def get_schedule(on: date | None = None, project: Project = Depends(project_viewer), db: Session = Depends(get_db)):
    on = on or date.today()
    tasks = _tasks(db, project.id)
    _rollup(tasks)
    counts = dict(
        db.query(ScheduleTaskElement.task_id, func.count())
        .join(ScheduleTask, ScheduleTask.id == ScheduleTaskElement.task_id)
        .filter(ScheduleTask.project_id == project.id)
        .group_by(ScheduleTaskElement.task_id).all()
    )
    out = [
        TaskOut(id=t.id, external_id=t.external_id, wbs=t.wbs, name=t.name, parent_id=t.parent_id, is_summary=t.is_summary,
                start_date=t.start_date, finish_date=t.finish_date, percent_complete=round(t.percent_complete, 2),
                planned_percent=round(planned_percent(t.start_date, t.finish_date, on), 2), cost=t.cost,
                status=task_status(t.start_date, t.finish_date, t.percent_complete, on), element_count=counts.get(t.id, 0))
        for t in tasks
    ]
    m = metrics(tasks, on)
    db.rollback()  # discard in-memory roll-up of summary rows
    return ScheduleOut(tasks=out, metrics=m)


def _task(task_id: uuid.UUID, db: Session, user: User, editor: bool = True) -> ScheduleTask:
    t: ScheduleTask = get_project_scoped_or_404(ScheduleTask, task_id, db, user)
    if editor:
        _require_project_role(t.project_id, "editor", db, user)
    return t


@router.patch("/api/schedule/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: uuid.UUID, payload: TaskUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    t = _task(task_id, db, user)
    if t.is_summary and payload.percent_complete is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Процент суммарной задачи считается по вложенным")
    for k, v in payload.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(t, k, v)
    if t.finish_date < t.start_date:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Окончание раньше начала")
    db.commit()
    n = db.query(func.count()).select_from(ScheduleTaskElement).filter(ScheduleTaskElement.task_id == t.id).scalar()
    today = date.today()
    return TaskOut(id=t.id, external_id=t.external_id, wbs=t.wbs, name=t.name, parent_id=t.parent_id, is_summary=t.is_summary,
                   start_date=t.start_date, finish_date=t.finish_date, percent_complete=t.percent_complete,
                   planned_percent=planned_percent(t.start_date, t.finish_date, today), cost=t.cost,
                   status=task_status(t.start_date, t.finish_date, t.percent_complete, today), element_count=n)


def _resolve_elements(db: Session, payload: LinkRequest) -> list[str]:
    q = db.query(BimElement.global_id).filter(BimElement.asset_id == payload.asset_id)
    if payload.global_ids is not None:
        q = q.filter(BimElement.global_id.in_(payload.global_ids))
    if payload.ifc_type:
        q = q.filter(BimElement.ifc_type == payload.ifc_type)
    if payload.storey:
        q = q.filter(BimElement.storey == payload.storey)
    if payload.q:
        like = f"%{payload.q}%"
        q = q.filter(or_(BimElement.name.ilike(like), BimElement.ifc_type.ilike(like)))
    return [g for (g,) in q.all()]


@router.post("/api/schedule/tasks/{task_id}/elements")
def link_elements(task_id: uuid.UUID, payload: LinkRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    t = _task(task_id, db, user)
    asset = db.get(SceneAsset, payload.asset_id)
    if asset is None or asset.project_id != t.project_id or asset.kind != "bim":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BIM asset not found")
    gids = _resolve_elements(db, payload)
    existing = {g for (g,) in db.query(ScheduleTaskElement.global_id).filter(
        ScheduleTaskElement.task_id == t.id, ScheduleTaskElement.version_group == asset.version_group).all()}
    new = [g for g in gids if g not in existing]
    for g in new:
        db.add(ScheduleTaskElement(task_id=t.id, version_group=asset.version_group, global_id=g))
    db.commit()
    return {"linked": len(new), "total": len(existing) + len(new)}


@router.delete("/api/schedule/tasks/{task_id}/elements")
def unlink_elements(task_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    t = _task(task_id, db, user)
    n = db.query(ScheduleTaskElement).filter(ScheduleTaskElement.task_id == t.id).delete()
    db.commit()
    return {"removed": n}


@router.get("/api/schedule/tasks/{task_id}/elements")
def task_elements(task_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    t = _task(task_id, db, user, editor=False)
    return [{"version_group": str(l.version_group), "global_id": l.global_id}
            for l in db.query(ScheduleTaskElement).filter(ScheduleTaskElement.task_id == t.id).all()]


@router.get("/api/projects/{project_id}/schedule/element-status")
def element_status(asset_id: uuid.UUID, on: date | None = None, project: Project = Depends(project_viewer),
                   db: Session = Depends(get_db)) -> dict:
    """{global_id: status} for colouring a BIM asset at a date (4D)."""
    asset = db.get(SceneAsset, asset_id)
    if asset is None or asset.project_id != project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    on = on or date.today()
    rank = {"late": 4, "in_progress": 3, "not_started": 2, "future": 1, "done": 0}
    out: dict[str, str] = {}
    rows = (
        db.query(ScheduleTaskElement.global_id, ScheduleTask)
        .join(ScheduleTask, ScheduleTask.id == ScheduleTaskElement.task_id)
        .filter(ScheduleTask.project_id == project.id, ScheduleTaskElement.version_group == asset.version_group)
        .all()
    )
    for gid, t in rows:
        st = task_status(t.start_date, t.finish_date, t.percent_complete, on)
        if gid not in out or rank[st] > rank[out[gid]]:
            out[gid] = st
    return {"on": on.isoformat(), "statuses": out}


@router.post("/api/projects/{project_id}/schedule/progress-from-analysis", response_model=ScheduleOut)
def progress_from_analysis(payload: ProgressFromAnalysis, project: Project = Depends(project_editor), db: Session = Depends(get_db)):
    """Actual % of each linked task = share of its elements confirmed by the
    scan (≥ min_points scan points on the element within the outer tolerance)."""
    a = db.get(Analysis, payload.analysis_id)
    if a is None or a.project_id != project.id or a.kind != "deviation" or a.status != "ready":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нужен готовый анализ отклонений")
    bim = db.get(SceneAsset, uuid.UUID(a.params["bim_asset_id"]))
    t3 = a.result.get("tolerances", [0.01, 0.05, 0.10])[2]
    built = {e["global_id"] for e in a.result.get("elements", [])
             if e["points"] >= payload.min_points and e["p95_abs"] <= t3 * 1.5}
    updated = 0
    for t in _tasks(db, project.id):
        gids = [g for (g,) in db.query(ScheduleTaskElement.global_id).filter(
            ScheduleTaskElement.task_id == t.id, ScheduleTaskElement.version_group == bim.version_group).all()]
        if not gids or t.is_summary:
            continue
        t.percent_complete = round(100.0 * sum(1 for g in gids if g in built) / len(gids), 1)
        updated += 1
    db.commit()
    return get_schedule(None, project, db)
