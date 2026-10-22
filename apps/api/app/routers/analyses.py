"""Analyses: deviation maps (scan vs BIM) and ICP alignment of scans."""

import io
import uuid
from urllib.parse import quote

import numpy as np
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import _require_project_role, get_project_scoped_or_404, project_editor, project_viewer
from app.queue import enqueue
from app.models import Analysis, Project, SceneAsset, User
from app.security import get_current_user
from app.storage import delete_prefix, get_bytes

router = APIRouter(tags=["analyses"])


class DeviationRequest(BaseModel):
    cloud_asset_id: uuid.UUID
    bim_asset_id: uuid.UUID
    tolerances: list[float] = Field(default=[0.01, 0.05, 0.10], min_length=3, max_length=3)
    max_distance: float = Field(default=0.3, gt=0, le=5)


class AlignmentRequest(BaseModel):
    cloud_asset_id: uuid.UUID
    bim_asset_id: uuid.UUID
    max_distance: float = Field(default=0.5, gt=0, le=10)
    apply: bool = True


class AnalysisOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    params: dict
    error_message: str | None
    result: dict
    result_asset_id: uuid.UUID | None
    created_at: object
    finished_at: object | None


def _out(a: Analysis, full: bool = True) -> AnalysisOut:
    result = a.result if full else {k: v for k, v in a.result.items() if k != "elements"}
    return AnalysisOut(id=a.id, kind=a.kind, status=a.status, params=a.params, error_message=a.error_message,
                       result=result, result_asset_id=a.result_asset_id, created_at=a.created_at, finished_at=a.finished_at)


def _check_assets(db: Session, project: Project, cloud_id: uuid.UUID, bim_id: uuid.UUID) -> None:
    for aid, kind in ((cloud_id, "point_cloud"), (bim_id, "bim")):
        a = db.get(SceneAsset, aid)
        if a is None or a.project_id != project.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
        if a.kind != kind:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Нужны облако точек и BIM-модель")


def _create(db: Session, project: Project, user: User, kind: str, params: dict, bg: BackgroundTasks) -> Analysis:
    a = Analysis(project_id=project.id, kind=kind, params=params, created_by=user.id)
    db.add(a)
    db.commit()
    db.refresh(a)
    enqueue("analysis", {"analysis_id": str(a.id)}, bg)
    return a


@router.post("/api/projects/{project_id}/analyses/deviation", response_model=AnalysisOut, status_code=status.HTTP_201_CREATED)
def create_deviation(payload: DeviationRequest, background_tasks: BackgroundTasks, project: Project = Depends(project_editor),
                     db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _check_assets(db, project, payload.cloud_asset_id, payload.bim_asset_id)
    tol = sorted(payload.tolerances)
    params = {**payload.model_dump(mode="json"), "tolerances": tol}
    return _out(_create(db, project, user, "deviation", params, background_tasks))


@router.post("/api/projects/{project_id}/analyses/alignment", response_model=AnalysisOut, status_code=status.HTTP_201_CREATED)
def create_alignment(payload: AlignmentRequest, background_tasks: BackgroundTasks, project: Project = Depends(project_editor),
                     db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _check_assets(db, project, payload.cloud_asset_id, payload.bim_asset_id)
    return _out(_create(db, project, user, "alignment", payload.model_dump(mode="json"), background_tasks))


@router.get("/api/projects/{project_id}/analyses", response_model=list[AnalysisOut])
def list_analyses(project: Project = Depends(project_viewer), db: Session = Depends(get_db)):
    rows = db.query(Analysis).filter(Analysis.project_id == project.id).order_by(Analysis.created_at.desc()).all()
    return [_out(a, full=False) for a in rows]


@router.get("/api/analyses/{analysis_id}", response_model=AnalysisOut)
def get_analysis(analysis_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _out(get_project_scoped_or_404(Analysis, analysis_id, db, user))


@router.delete("/api/analyses/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_analysis(analysis_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    a: Analysis = get_project_scoped_or_404(Analysis, analysis_id, db, user)
    _require_project_role(a.project_id, "editor", db, user)
    asset = db.get(SceneAsset, a.result_asset_id) if a.result_asset_id else None
    prefix = asset.storage_prefix if asset else None
    if asset:
        db.delete(asset)
    db.delete(a)
    db.commit()
    if prefix:
        delete_prefix(prefix + "/")


@router.get("/api/analyses/{analysis_id}/report.pdf")
def report(analysis_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.twin.georef import resolve_crs
    from app.twin.report import build_pdf, plan_image

    a: Analysis = get_project_scoped_or_404(Analysis, analysis_id, db, user)
    if a.kind != "deviation" or a.status != "ready":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Отчёт доступен для готового анализа отклонений")
    project = db.get(Project, a.project_id)
    plan_png = None
    asset = db.get(SceneAsset, a.result_asset_id) if a.result_asset_id else None
    if asset is not None:
        try:
            data = np.load(io.BytesIO(get_bytes(f"{asset.storage_prefix}/_analysis/plan.npz")))
            plan_png = plan_image(data["xy"], data["bins"])
        except Exception:  # noqa: BLE001 -- report without the picture rather than fail
            plan_png = None
    forward, label = None, "(WGS 84)"
    try:
        crs = resolve_crs(project.crs) if project.crs else None
        if crs is not None and crs.is_projected:
            from pyproj import Transformer

            tr = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
            forward, label = (lambda lon, lat: tr.transform(lon, lat)), f"({project.crs})"
    except Exception:  # noqa: BLE001
        pass
    pdf = build_pdf(project.name, a.result, plan_png, forward, label)
    name = f"Отклонения_{a.created_at:%Y-%m-%d}.pdf"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})
