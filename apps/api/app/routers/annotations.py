"""3D annotations (метки / замечания) pinned to a location and optionally to
a BIM element (GlobalId)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import _require_project_role, get_project_scoped_or_404, project_editor, project_viewer
from app.models import Annotation, Project, SceneAsset, User
from app.schemas import Annotation as AnnotationSchema
from app.schemas import AnnotationCreate, AnnotationUpdate
from app.security import get_current_user

router = APIRouter(tags=["annotations"])


def _with_author(db: Session, notes: list[Annotation]) -> list[AnnotationSchema]:
    ids = {n.created_by for n in notes if n.created_by}
    names = {u.id: (u.full_name or u.email) for u in db.query(User).filter(User.id.in_(ids)).all()} if ids else {}
    out = []
    for n in notes:
        item = AnnotationSchema.model_validate(n)
        item.author_name = names.get(n.created_by)
        out.append(item)
    return out


@router.get("/api/projects/{project_id}/annotations", response_model=list[AnnotationSchema])
def list_annotations(project: Project = Depends(project_viewer), db: Session = Depends(get_db)):
    notes = db.query(Annotation).filter(Annotation.project_id == project.id).order_by(Annotation.created_at.desc()).all()
    return _with_author(db, notes)


@router.post("/api/projects/{project_id}/annotations", response_model=AnnotationSchema, status_code=status.HTTP_201_CREATED)
def create_annotation(
    payload: AnnotationCreate,
    project: Project = Depends(project_editor),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if payload.asset_id is not None:
        asset = db.get(SceneAsset, payload.asset_id)
        if asset is None or asset.project_id != project.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    note = Annotation(project_id=project.id, created_by=user.id, **payload.model_dump())
    db.add(note)
    db.commit()
    db.refresh(note)
    return _with_author(db, [note])[0]


@router.patch("/api/annotations/{annotation_id}", response_model=AnnotationSchema)
def update_annotation(
    annotation_id: uuid.UUID,
    payload: AnnotationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    note: Annotation = get_project_scoped_or_404(Annotation, annotation_id, db, user)
    _require_project_role(note.project_id, "editor", db, user)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(note, key, value)
    db.commit()
    db.refresh(note)
    return _with_author(db, [note])[0]


@router.delete("/api/annotations/{annotation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_annotation(annotation_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    note: Annotation = get_project_scoped_or_404(Annotation, annotation_id, db, user)
    _require_project_role(note.project_id, "editor", db, user)
    db.delete(note)
    db.commit()
