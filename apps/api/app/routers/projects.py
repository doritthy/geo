import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import project_editor, project_owner, project_viewer
from app.models import Project, ProjectMember, User
from app.schemas import AddMemberRequest
from app.schemas import Project as ProjectSchema
from app.schemas import ProjectCreate, ProjectUpdate
from app.twin.georef import GeorefError, resolve_crs
from app.security import get_current_user

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[ProjectSchema])
def list_projects(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[Project]:
    query = db.query(Project).filter(Project.organization_id == user.organization_id)
    if user.role == "admin":
        # Admins can act on any project in their org; still only their org.
        return query.order_by(Project.created_at.desc()).all()
    member_project_ids = (
        db.query(ProjectMember.project_id).filter(ProjectMember.user_id == user.id).subquery()
    )
    return query.filter(Project.id.in_(member_project_ids)).order_by(Project.created_at.desc()).all()


@router.post("", response_model=ProjectSchema, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Project:
    project = Project(
        organization_id=user.organization_id,
        name=payload.name,
        description=payload.description,
        default_crs_epsg=payload.default_crs_epsg,
        crs=_validated_crs(payload.crs),
        created_by=user.id,
    )
    db.add(project)
    db.flush()
    # Creator is automatically the project owner.
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role="owner"))
    db.commit()
    db.refresh(project)
    return project


def _validated_crs(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    try:
        resolve_crs(value)
    except GeorefError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return value.strip()


@router.patch("/{project_id}", response_model=ProjectSchema)
def update_project(
    payload: ProjectUpdate, project: Project = Depends(project_editor), db: Session = Depends(get_db)
) -> Project:
    data = payload.model_dump(exclude_unset=True)
    if data.get("name"):
        project.name = data["name"]
    if "description" in data:
        project.description = data["description"]
    if "crs" in data:
        project.crs = _validated_crs(data["crs"])
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectSchema)
def get_project(project: Project = Depends(project_viewer)) -> Project:
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project: Project = Depends(project_owner), db: Session = Depends(get_db)) -> None:
    db.delete(project)
    db.commit()
    return None


@router.post("/{project_id}/members", status_code=status.HTTP_201_CREATED)
def add_member(
    payload: AddMemberRequest,
    project: Project = Depends(project_owner),
    db: Session = Depends(get_db),
) -> dict:
    target = db.query(User).filter(User.email == payload.email).first()
    if target is None or target.organization_id != project.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found in organization")

    membership = db.get(ProjectMember, {"project_id": project.id, "user_id": target.id})
    if membership is None:
        membership = ProjectMember(project_id=project.id, user_id=target.id, role=payload.role)
        db.add(membership)
    else:
        membership.role = payload.role
    db.commit()
    return {"project_id": str(project.id), "user_id": str(target.id), "role": membership.role}
