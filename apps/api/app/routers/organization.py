"""Organisation user management (администратор платформы): list users,
create accounts for colleagues, change org role, project membership list."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import project_owner, project_viewer
from app.models import Project, ProjectMember, User
from app.schemas import UserRole
from app.security import get_current_user, hash_password

router = APIRouter(tags=["organization"])


class OrgUserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str | None = None
    role: UserRole = "viewer"


class OrgUserUpdate(BaseModel):
    full_name: str | None = None
    role: UserRole | None = None
    password: str | None = Field(default=None, min_length=8)


class OrgUserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    role: str


class ProjectMemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str | None
    role: str


def _admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Только для администратора организации")
    return user


@router.get("/api/organization/users", response_model=list[OrgUserOut])
def list_users(db: Session = Depends(get_db), admin: User = Depends(_admin)):
    users = db.query(User).filter(User.organization_id == admin.organization_id).order_by(User.full_name, User.email).all()
    return [OrgUserOut(id=u.id, email=u.email, full_name=u.full_name, role=u.role) for u in users]


@router.post("/api/organization/users", response_model=OrgUserOut, status_code=status.HTTP_201_CREATED)
def create_user(payload: OrgUserCreate, db: Session = Depends(get_db), admin: User = Depends(_admin)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email уже зарегистрирован")
    u = User(organization_id=admin.organization_id, email=payload.email, password_hash=hash_password(payload.password),
             full_name=payload.full_name, role=payload.role)
    db.add(u)
    db.commit()
    db.refresh(u)
    return OrgUserOut(id=u.id, email=u.email, full_name=u.full_name, role=u.role)


@router.patch("/api/organization/users/{user_id}", response_model=OrgUserOut)
def update_user(user_id: uuid.UUID, payload: OrgUserUpdate, db: Session = Depends(get_db), admin: User = Depends(_admin)):
    u = db.get(User, user_id)
    if u is None or u.organization_id != admin.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    data = payload.model_dump(exclude_unset=True)
    if "role" in data and data["role"] and u.id == admin.id and data["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нельзя снять роль администратора с себя")
    if data.get("full_name") is not None:
        u.full_name = data["full_name"]
    if data.get("role"):
        u.role = data["role"]
    if data.get("password"):
        u.password_hash = hash_password(data["password"])
    db.commit()
    return OrgUserOut(id=u.id, email=u.email, full_name=u.full_name, role=u.role)


@router.get("/api/projects/{project_id}/memberships", response_model=list[ProjectMemberOut])
def project_memberships(project: Project = Depends(project_viewer), db: Session = Depends(get_db)):
    rows = (
        db.query(ProjectMember, User).join(User, User.id == ProjectMember.user_id)
        .filter(ProjectMember.project_id == project.id).order_by(User.full_name).all()
    )
    return [ProjectMemberOut(user_id=u.id, email=u.email, full_name=u.full_name, role=m.role) for m, u in rows]


@router.delete("/api/projects/{project_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(user_id: uuid.UUID, project: Project = Depends(project_owner), db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    m = db.get(ProjectMember, {"project_id": project.id, "user_id": user_id})
    if m is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if user_id == user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нельзя удалить себя из проекта")
    db.delete(m)
    db.commit()
