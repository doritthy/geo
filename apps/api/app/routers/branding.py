"""White-label branding per organisation: product name in the header, logo
and accent colour. Everyone in the organisation reads it; admins change it."""

import re
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Organization, User
from app.security import get_current_user
from app.storage import get_bytes, upload_bytes

router = APIRouter(tags=["branding"])

LOGO_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/svg+xml": "svg", "image/webp": "webp"}
MAX_LOGO = 1024 * 1024


class BrandingIn(BaseModel):
    name: str | None = Field(None, max_length=60)
    color: str | None = None


def _org(db: Session, user: User) -> Organization:
    return db.get(Organization, user.organization_id)


def _admin(user: User) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Только администратор организации")


def _out(org: Organization) -> dict:
    return {
        "name": org.brand_name, "color": org.brand_color, "organization": org.name,
        "logo_url": f"/api/branding/logo?v={uuid.uuid5(uuid.NAMESPACE_URL, org.logo_key).hex[:8]}" if org.logo_key else None,
    }


@router.get("/api/branding")
def get_branding(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    return _out(_org(db, user))


@router.put("/api/organization/branding")
def set_branding(body: BrandingIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    _admin(user)
    if body.color and not re.fullmatch(r"#[0-9a-fA-F]{6}", body.color):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Цвет в формате #RRGGBB")
    org = _org(db, user)
    org.brand_name = (body.name or "").strip() or None
    org.brand_color = body.color.upper() if body.color else None
    db.commit()
    return _out(org)


@router.post("/api/organization/branding/logo")
def set_logo(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    _admin(user)
    ctype = (file.content_type or "").split(";")[0]
    if ctype not in LOGO_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Логотип: PNG, JPEG, WebP или SVG")
    data = file.file.read(MAX_LOGO + 1)
    if len(data) > MAX_LOGO:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Логотип больше 1 МБ")
    if ctype == "image/svg+xml" and re.search(rb"<script|on\w+\s*=|javascript:", data, re.I):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="SVG со скриптами не допускается")
    org = _org(db, user)
    key = f"organizations/{org.id}/logo-{uuid.uuid4().hex[:8]}.{LOGO_TYPES[ctype]}"
    upload_bytes(key, data, content_type=ctype)
    org.logo_key, org.logo_type = key, ctype
    db.commit()
    return _out(org)


@router.delete("/api/organization/branding/logo")
def delete_logo(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    _admin(user)
    org = _org(db, user)
    org.logo_key = org.logo_type = None
    db.commit()
    return _out(org)


@router.get("/api/branding/logo")
def get_logo(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    org = _org(db, user)
    if not org.logo_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    # SVG served with a restrictive CSP so it cannot run anything even if opened directly.
    return Response(get_bytes(org.logo_key), media_type=org.logo_type,
                    headers={"Cache-Control": "private, max-age=86400", "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})
