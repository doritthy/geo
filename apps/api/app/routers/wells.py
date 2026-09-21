import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_project_scoped_or_404, project_viewer
from app.models import Project, User, Well, WellLog, WellMarker, WellTrajectoryPoint
from app.schemas import LogCurveSummary, TrajectoryPoint
from app.schemas import WellDetail, WellMarker as WellMarkerSchema, WellSummary
from app.security import get_current_user
from app.storage import get_bytes

router = APIRouter(tags=["wells"])


@router.get("/api/projects/{project_id}/wells", response_model=list[WellSummary])
def list_wells(project: Project = Depends(project_viewer), db: Session = Depends(get_db)) -> list[Well]:
    return db.query(Well).filter(Well.project_id == project.id).order_by(Well.name).all()


@router.get("/api/wells/{well_id}", response_model=WellDetail)
def get_well(well_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Well:
    return get_project_scoped_or_404(Well, well_id, db, user)


@router.get("/api/wells/{well_id}/trajectory", response_model=list[TrajectoryPoint])
def get_trajectory(
    well_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[WellTrajectoryPoint]:
    get_project_scoped_or_404(Well, well_id, db, user)
    return (
        db.query(WellTrajectoryPoint)
        .filter(WellTrajectoryPoint.well_id == well_id)
        .order_by(WellTrajectoryPoint.seq)
        .all()
    )


@router.get("/api/wells/{well_id}/markers", response_model=list[WellMarkerSchema])
def get_markers(
    well_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[WellMarker]:
    get_project_scoped_or_404(Well, well_id, db, user)
    return db.query(WellMarker).filter(WellMarker.well_id == well_id).order_by(WellMarker.md).all()


@router.get("/api/wells/{well_id}/logs", response_model=list[LogCurveSummary])
def get_logs(
    well_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[WellLog]:
    get_project_scoped_or_404(Well, well_id, db, user)
    return db.query(WellLog).filter(WellLog.well_id == well_id).order_by(WellLog.curve_name).all()


@router.get("/api/wells/{well_id}/logs/{log_id}/data")
def get_log_data(
    well_id: uuid.UUID,
    log_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    get_project_scoped_or_404(Well, well_id, db, user)
    log = db.get(WellLog, log_id)
    if log is None or log.well_id != well_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    data = get_bytes(log.storage_key)
    return Response(content=data, media_type="application/octet-stream")
