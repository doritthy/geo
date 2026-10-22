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


class ProfileRequest(BaseModel):
    a: list[float] = Field(min_length=2, max_length=2)  # [lon, lat]
    b: list[float] = Field(min_length=2, max_length=2)
    bim_asset_id: uuid.UUID | None = None
    cloud_asset_id: uuid.UUID | None = None
    width: float = Field(default=0.3, gt=0, le=10)


@router.post("/api/projects/{project_id}/profile")
def profile(payload: ProfileRequest, project: Project = Depends(project_viewer), db: Session = Depends(get_db)) -> dict:
    """Vertical section A→B: BIM cut lines + scan points in a corridor, in
    (distance m, ellipsoidal height m)."""
    from app.twin.analysis_jobs import load_mesh_world, load_points_world
    from app.twin.georef import llh_to_ecef
    from app.twin.profile import corridor_points, frame_at, section_segments

    origin, axes = frame_at(*payload.a)
    b_local = (llh_to_ecef(payload.b[0], payload.b[1], 0.0) - origin) @ axes.T
    a2, b2 = np.zeros(2), b_local[:2]
    out: dict = {"length": float(np.linalg.norm(b2)), "bim": [], "scan": []}

    def asset(aid, kind):
        a = db.get(SceneAsset, aid)
        if a is None or a.project_id != project.id or a.kind != kind:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
        return a

    if payload.bim_asset_id:
        _, tris = load_mesh_world(asset(payload.bim_asset_id, "bim"))
        local = ((tris.reshape(-1, 3) - origin) @ axes.T).reshape(-1, 3, 3)
        # ENU z at the origin is height above the ellipsoid there (curvature < 1 mm over 100 m).
        out["bim"] = section_segments(local, a2, b2)
    if payload.cloud_asset_id:
        pts, _, _ = load_points_world(asset(payload.cloud_asset_id, "point_cloud"), max_points=3_000_000)
        out["scan"] = corridor_points((pts - origin) @ axes.T, a2, b2, payload.width)
    return out


@router.get("/api/analyses/{analysis_id}/as-built.ifc")
def as_built_ifc(analysis_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Source IFC of the analysed model + per-element as-built property set."""
    import os
    import tempfile

    from app.models import FileRecord
    from app.storage import download_to_file
    from app.twin.asbuilt import build_as_built

    a: Analysis = get_project_scoped_or_404(Analysis, analysis_id, db, user)
    if a.kind != "deviation" or a.status != "ready":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нужен готовый анализ отклонений")
    bim = db.get(SceneAsset, uuid.UUID(a.params["bim_asset_id"]))
    src = db.get(FileRecord, bim.source_file_id) if bim and bim.source_file_id else None
    if src is None or not src.filename.lower().endswith(".ifc"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Исходный IFC модели недоступен (например, модель получена из RVT через APS)")
    fd, path = tempfile.mkstemp(suffix=".ifc")
    os.close(fd)
    try:
        download_to_file(src.storage_key, path)
        data, _ = build_as_built(path, a.result, a.created_at.date().isoformat())
    finally:
        os.unlink(path)
    name = f"{os.path.splitext(src.filename)[0]}_as-built_{a.created_at:%Y-%m-%d}.ifc"
    return Response(data, media_type="application/x-step",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


@router.get("/api/analyses/{analysis_id}/executive-scheme.pdf")
def executive_scheme(
    analysis_id: uuid.UUID,
    storey: str | None = None,
    step: float = 3.0,
    tolerance_mm: float = 10.0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Исполнительная схема отметок верха плит: control-point grid (`step`
    metres) on each slab of `storey` (all slabs if omitted), design vs
    as-built elevation from the analysed scan."""
    from pyproj import Transformer

    from app.models import BimElement
    from app.twin import exec_scheme
    from app.twin import georef as geo
    from app.twin.analysis_jobs import load_mesh_world, load_points_world, local_frame, to_local

    a: Analysis = get_project_scoped_or_404(Analysis, analysis_id, db, user)
    if a.kind != "deviation" or a.status != "ready":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нужен готовый анализ отклонений")
    step = min(max(step, 0.5), 20.0)
    tolerance_mm = min(max(tolerance_mm, 1.0), 200.0)
    project = db.get(Project, a.project_id)
    bim = db.get(SceneAsset, uuid.UUID(a.params["bim_asset_id"]))
    cloud = db.get(SceneAsset, uuid.UUID(a.params["cloud_asset_id"]))
    if bim is None or cloud is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Модель или скан удалены")

    storeys = {e.global_id: e.storey for e in db.query(BimElement.global_id, BimElement.storey)
               .filter(BimElement.asset_id == bim.id, BimElement.ifc_type == "IfcSlab").all()}
    mesh, tris_w = load_mesh_world(bim)
    pts_w, _, _ = load_points_world(cloud)
    origin, axes = local_frame(pts_w)
    tris = to_local(tris_w.reshape(-1, 3), origin, axes).reshape(-1, 3, 3)
    pts = to_local(pts_w, origin, axes)
    slabs = [(i, gid, mesh.names[i] or gid, storeys.get(gid)) for i, gid in enumerate(mesh.global_ids)
             if mesh.ifc_types[i] == "IfcSlab" and (storey is None or storeys.get(gid) == storey)]
    schemes = exec_scheme.compute(tris, mesh.feature, slabs, pts, step)
    schemes.sort(key=lambda s: (s.storey or "", s.name))

    height_offset = float(bim.georef.get("height_offset") or 0.0) if bim.georef.get("mode") == "absolute" else 0.0
    to_crs, crs_label = None, "(широта / долгота)"
    try:
        crs = geo.resolve_crs(project.crs) if project.crs else None
        if crs is not None and crs.is_projected:
            to_crs, crs_label = Transformer.from_crs(4326, crs, always_xy=True), f"({project.crs})"
    except geo.GeorefError:
        pass

    def llh(local):
        return geo.ecef_to_llh(origin + np.asarray(local) @ axes)[0]

    def to_coords(local):
        lon, lat, _ = llh(local)
        return to_crs.transform(lon, lat) if to_crs else (lat, lon)

    def to_height(local):
        return float(llh(local)[2]) - height_offset

    r = a.result
    pdf = exec_scheme.build_pdf(project.name, f"{r['bim']['name']} v{r['bim']['version']}",
                                f"{r['cloud']['name']} {r['cloud'].get('captured_at') or ''}".strip(),
                                schemes, tolerance_mm, to_coords, to_height, crs_label)
    name = f"Исполнительная_схема_{storey or 'все_плиты'}_{a.created_at:%Y-%m-%d}.pdf"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})
