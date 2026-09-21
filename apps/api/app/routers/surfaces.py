import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_project_scoped_or_404, project_viewer
from app.models import Project, Surface, User
from app.schemas import SurfaceDetail, SurfaceSummary
from app.security import get_current_user
from app.storage import get_bytes

router = APIRouter(tags=["surfaces"])


@router.get("/api/projects/{project_id}/surfaces", response_model=list[SurfaceSummary])
def list_surfaces(project: Project = Depends(project_viewer), db: Session = Depends(get_db)) -> list[Surface]:
    return db.query(Surface).filter(Surface.project_id == project.id).order_by(Surface.name).all()


@router.get("/api/surfaces/{surface_id}", response_model=SurfaceDetail)
def get_surface(
    surface_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Surface:
    return get_project_scoped_or_404(Surface, surface_id, db, user)


@router.get("/api/surfaces/{surface_id}/heights")
def get_heights(
    surface_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Response:
    surface: Surface = get_project_scoped_or_404(Surface, surface_id, db, user)
    if not surface.heights_storage_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Heights not available")
    data = get_bytes(surface.heights_storage_key)
    return Response(content=data, media_type="application/octet-stream")
