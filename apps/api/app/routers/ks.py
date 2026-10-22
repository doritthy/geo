"""КС-2 / КС-3 act drafts from the schedule (see app/twin/ks_acts.py)."""

import uuid
from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import _require_project_role, get_project_scoped_or_404, project_editor, project_viewer
from app.models import KsAct, Project, ScheduleTask, User
from app.security import get_current_user
from app.twin import ks_acts as ks

router = APIRouter(tags=["ks acts"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ActIn(BaseModel):
    period_from: date
    period_to: date
    customer: str | None = Field(None, max_length=300)
    contractor: str | None = Field(None, max_length=300)
    contract: str | None = Field(None, max_length=300)
    object: str | None = Field(None, max_length=300)


def _out(a: KsAct) -> dict:
    return {"id": str(a.id), "number": a.number, "period_from": a.period_from.isoformat(), "period_to": a.period_to.isoformat(),
            "header": a.header, "items": a.items, "total": float(a.total), "created_at": a.created_at.isoformat()}


@router.get("/api/projects/{project_id}/ks-acts")
def list_acts(project: Project = Depends(project_viewer), db: Session = Depends(get_db)) -> list[dict]:
    return [_out(a) for a in db.query(KsAct).filter(KsAct.project_id == project.id).order_by(KsAct.number.desc()).all()]


@router.post("/api/projects/{project_id}/ks-acts", status_code=status.HTTP_201_CREATED)
def create_act(body: ActIn, project: Project = Depends(project_editor), db: Session = Depends(get_db),
               user: User = Depends(get_current_user)) -> dict:
    if body.period_to < body.period_from:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Конец периода раньше начала")
    acts = db.query(KsAct).filter(KsAct.project_id == project.id).order_by(KsAct.number).all()
    if acts and body.period_from <= acts[-1].period_to:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Период пересекается с актом № {acts[-1].number} (по {acts[-1].period_to:%d.%m.%Y})")
    previous: dict[str, float] = {}
    for a in acts:
        for it in a.items:
            previous[it["key"]] = it["pct_now"]
    tasks = db.query(ScheduleTask).filter(ScheduleTask.project_id == project.id).all()
    if not any(t.cost for t in tasks if not t.is_summary):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="В графике нет стоимости задач")
    items = ks.build_items(tasks, previous)
    if not items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="С прошлого акта выполнение не изменилось")
    header = {k: v for k, v in body.model_dump(include={"customer", "contractor", "contract", "object"}).items() if v}
    if acts and not header:
        header = acts[-1].header  # carry over the parties
    act = KsAct(project_id=project.id, number=(acts[-1].number + 1) if acts else 1, period_from=body.period_from,
                period_to=body.period_to, header=header, items=items, total=round(sum(i["amount"] for i in items), 2),
                created_by=user.id)
    db.add(act)
    db.commit()
    db.refresh(act)
    return _out(act)


def _act(act_id: uuid.UUID, db: Session, user: User) -> KsAct:
    return get_project_scoped_or_404(KsAct, act_id, db, user)


@router.delete("/api/ks-acts/{act_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_act(act_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    a = _act(act_id, db, user)
    _require_project_role(a.project_id, "editor", db, user)
    last = db.query(func.max(KsAct.number)).filter(KsAct.project_id == a.project_id).scalar()
    if a.number != last:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Удалять можно только последний акт")
    db.delete(a)
    db.commit()


def _file(data: bytes, name: str) -> Response:
    return Response(data, media_type=XLSX, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


@router.get("/api/ks-acts/{act_id}/ks2.xlsx")
def ks2(act_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    a = _act(act_id, db, user)
    return _file(ks.ks2_xlsx(a, db.get(Project, a.project_id).name), f"КС-2_№{a.number}_{a.period_to:%Y-%m}.xlsx")


@router.get("/api/ks-acts/{act_id}/ks3.xlsx")
def ks3(act_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    a = _act(act_id, db, user)
    upto = db.query(KsAct).filter(KsAct.project_id == a.project_id, KsAct.number <= a.number).all()
    since_start = sum(float(x.total) for x in upto)
    since_year = sum(float(x.total) for x in upto if x.period_to >= ks.year_start(a.period_to))
    return _file(ks.ks3_xlsx(a, db.get(Project, a.project_id).name, since_start, since_year), f"КС-3_№{a.number}_{a.period_to:%Y-%m}.xlsx")
