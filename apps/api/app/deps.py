import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Project, ProjectMember, User
from app.security import get_current_user

_ROLE_RANK = {"viewer": 0, "editor": 1, "owner": 2}

CurrentUser = User


def _not_found() -> HTTPException:
    # Per API_CONTRACT.md: any project/file/well/grid/surface the caller can't
    # see (wrong org, not a member, or insufficient role) is a 404, never a
    # 403 -- this avoids leaking whether the resource exists at all.
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _require_project_role(project_id: uuid.UUID, min_role: str, db: Session, user: User) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.organization_id != user.organization_id:
        raise _not_found()

    if user.role == "admin":
        return project

    membership = db.get(ProjectMember, {"project_id": project_id, "user_id": user.id})
    if membership is None:
        raise _not_found()

    if _ROLE_RANK[membership.role] < _ROLE_RANK[min_role]:
        raise _not_found()

    return project


def project_viewer(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Project:
    """FastAPI dependency: resolves the path's `project_id` if the caller can
    at least view it (org admin, or any project_members role), else 404."""
    return _require_project_role(project_id, "viewer", db, user)


def project_editor(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Project:
    """Like `project_viewer` but requires editor or owner (or org admin)."""
    return _require_project_role(project_id, "editor", db, user)


def project_owner(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Project:
    """Like `project_viewer` but requires owner (or org admin)."""
    return _require_project_role(project_id, "owner", db, user)


def get_effective_role(project_id: uuid.UUID, db: Session, user: User) -> str | None:
    if user.role == "admin":
        return "owner"
    membership = db.get(ProjectMember, {"project_id": project_id, "user_id": user.id})
    return membership.role if membership else None


def get_project_scoped_or_404(model, obj_id: uuid.UUID, db: Session, user: User):
    """For resources that hang off a project (files, wells, grids, surfaces,
    map layers, formations, well logs/markers via their well): fetch by id,
    then verify the caller can view the owning project. Raises 404 if the
    row doesn't exist or access is denied."""
    obj = db.get(model, obj_id)
    if obj is None:
        raise _not_found()
    project_id = getattr(obj, "project_id", None)
    if project_id is None:
        raise _not_found()
    _require_project_role(project_id, "viewer", db, user)
    return obj
