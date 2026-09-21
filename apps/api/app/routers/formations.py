from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import project_editor, project_viewer
from app.models import Formation as FormationModel
from app.models import Project
from app.schemas import Formation, FormationCreate

router = APIRouter(tags=["formations"])


@router.get("/api/projects/{project_id}/formations", response_model=list[Formation])
def list_formations(
    project: Project = Depends(project_viewer), db: Session = Depends(get_db)
) -> list[FormationModel]:
    return db.query(FormationModel).filter(FormationModel.project_id == project.id).order_by(FormationModel.name).all()


@router.post(
    "/api/projects/{project_id}/formations", response_model=Formation, status_code=status.HTTP_201_CREATED
)
def create_formation(
    payload: FormationCreate,
    project: Project = Depends(project_editor),
    db: Session = Depends(get_db),
) -> FormationModel:
    formation = FormationModel(
        project_id=project.id,
        name=payload.name,
        description=payload.description,
        color=payload.color,
        top_surface_id=payload.top_surface_id,
        base_surface_id=payload.base_surface_id,
    )
    db.add(formation)
    db.commit()
    db.refresh(formation)
    return formation
