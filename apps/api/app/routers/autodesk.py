"""Autodesk ACC / BIM 360 integration endpoints: connect an Autodesk account
(3-legged OAuth), browse hubs/projects/folders, one-click import of a model
into a twin project, and webhook-driven re-import of new versions."""

import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal, get_db
from app.deps import project_editor, project_viewer
from app.integrations import autodesk_service as svc
from app.integrations.aps import APSError
from app.models import AutodeskConnection, AutodeskLink, Project, User
from app.security import get_current_user

router = APIRouter(prefix="/api", tags=["autodesk"])
logger = logging.getLogger(__name__)


class ImportRequest(BaseModel):
    hub_id: str | None = None
    aps_project_id: str
    item_id: str
    folder_id: str | None = None
    name: str | None = None
    watch: bool = True
    options: dict = {}


class LinkOut(BaseModel):
    id: uuid.UUID
    name: str
    item_id: str
    status: str
    error_message: str | None
    last_version_id: str | None
    watching: bool
    updated_at: datetime


def _require_configured():
    if not get_settings().aps_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Интеграция Autodesk не настроена: задайте APS_CLIENT_ID и APS_CLIENT_SECRET",
        )


def _aps_error(exc: APSError) -> HTTPException:
    code = status.HTTP_401_UNAUTHORIZED if exc.status == 401 else status.HTTP_502_BAD_GATEWAY
    return HTTPException(status_code=code, detail=str(exc))


def _token(db: Session, user: User) -> str:
    try:
        return svc.user_token(db, user.id)
    except APSError as exc:
        raise _aps_error(exc) from exc


def _state_for(user: User, return_to: str | None) -> str:
    settings = get_settings()
    payload = {
        "sub": str(user.id), "purpose": "aps-oauth", "ret": return_to or "/projects",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


@router.get("/integrations/autodesk/status")
def status_(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    settings = get_settings()
    conn = db.get(AutodeskConnection, user.id) if settings.aps_configured else None
    return {
        "configured": settings.aps_configured,
        "connected": conn is not None,
        "webhooks": bool(settings.APS_WEBHOOK_URL),
    }


@router.get("/integrations/autodesk/login")
def login(return_to: str | None = None, user: User = Depends(get_current_user)) -> dict:
    _require_configured()
    if return_to and not return_to.startswith("/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="return_to must be a relative path")
    return {"url": svc.client_factory().authorize_url(_state_for(user, return_to))}


@router.get("/integrations/autodesk/callback")
def callback(code: str | None = None, state: str | None = None, error: str | None = None, db: Session = Depends(get_db)):
    settings = get_settings()
    web = settings.PUBLIC_WEB_URL.rstrip("/")
    try:
        claims = jwt.decode(state or "", settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        if claims.get("purpose") != "aps-oauth":
            raise JWTError("wrong purpose")
    except JWTError:
        return RedirectResponse(f"{web}/projects?autodesk=invalid_state")
    ret = claims.get("ret", "/projects")
    sep = "&" if "?" in ret else "?"
    if error or not code:
        return RedirectResponse(f"{web}{ret}{sep}autodesk=denied")
    user_id = uuid.UUID(claims["sub"])
    if db.get(User, user_id) is None:
        return RedirectResponse(f"{web}/projects?autodesk=invalid_state")
    try:
        token = svc.client_factory().exchange_code(code)
    except APSError:
        logger.exception("APS code exchange failed")
        return RedirectResponse(f"{web}{ret}{sep}autodesk=error")
    svc.save_connection(db, user_id, token)
    return RedirectResponse(f"{web}{ret}{sep}autodesk=connected")


@router.delete("/integrations/autodesk/connection", status_code=status.HTTP_204_NO_CONTENT)
def disconnect(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    conn = db.get(AutodeskConnection, user.id)
    if conn:
        db.delete(conn)
        db.commit()


# ---------- browsing ----------


def _simplify(items: list[dict]) -> list[dict]:
    out = []
    for it in items:
        attrs = it.get("attributes", {})
        out.append({
            "id": it.get("id"),
            "type": it.get("type"),  # hubs | projects | folders | items
            "name": attrs.get("displayName") or attrs.get("name"),
            "extension": (attrs.get("extension") or {}).get("type"),
            "modified": attrs.get("lastModifiedTime"),
            "region": attrs.get("region"),
        })
    return out


@router.get("/integrations/autodesk/hubs")
def hubs(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    _require_configured()
    try:
        return _simplify(svc.client_factory().hubs(_token(db, user)))
    except APSError as exc:
        raise _aps_error(exc) from exc


@router.get("/integrations/autodesk/hubs/{hub_id}/projects")
def projects(hub_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    _require_configured()
    try:
        return _simplify(svc.client_factory().projects(_token(db, user), hub_id))
    except APSError as exc:
        raise _aps_error(exc) from exc


@router.get("/integrations/autodesk/hubs/{hub_id}/projects/{project_id}/folders")
def top_folders(hub_id: str, project_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_configured()
    try:
        return _simplify(svc.client_factory().top_folders(_token(db, user), hub_id, project_id))
    except APSError as exc:
        raise _aps_error(exc) from exc


@router.get("/integrations/autodesk/projects/{project_id}/folders/{folder_id}/contents")
def folder_contents(project_id: str, folder_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_configured()
    try:
        return _simplify(svc.client_factory().folder_contents(_token(db, user), project_id, folder_id))
    except APSError as exc:
        raise _aps_error(exc) from exc


# ---------- import / links ----------


def _link_out(link: AutodeskLink) -> LinkOut:
    return LinkOut(
        id=link.id, name=link.name, item_id=link.item_id, status=link.status, error_message=link.error_message,
        last_version_id=link.last_version_id, watching=bool(link.hook_id), updated_at=link.updated_at or link.created_at,
    )


def _run_import(link_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        svc.import_link(db, link_id)
    finally:
        db.close()


@router.post("/projects/{project_id}/autodesk/imports", response_model=LinkOut, status_code=status.HTTP_201_CREATED)
def create_import(
    payload: ImportRequest,
    background_tasks: BackgroundTasks,
    project: Project = Depends(project_editor),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_configured()
    token = _token(db, user)
    link = (
        db.query(AutodeskLink)
        .filter(AutodeskLink.project_id == project.id, AutodeskLink.item_id == payload.item_id)
        .first()
    )
    if link is None:
        link = AutodeskLink(
            project_id=project.id, user_id=user.id, hub_id=payload.hub_id, aps_project_id=payload.aps_project_id,
            item_id=payload.item_id, folder_id=payload.folder_id, name=payload.name or "Модель ACC",
            options=payload.options,
        )
        db.add(link)
    link.status = "pending"
    link.user_id = user.id
    db.commit()

    settings = get_settings()
    if payload.watch and payload.folder_id and settings.APS_WEBHOOK_URL and not link.hook_id:
        try:
            link.hook_id = svc.client_factory().create_version_hook(
                token, payload.folder_id, settings.APS_WEBHOOK_URL, {"link": str(link.id)}
            ) or "existing"
            db.commit()
        except APSError:
            logger.exception("Could not register ACC webhook; import continues without auto-update")

    background_tasks.add_task(_run_import, link.id)
    return _link_out(link)


@router.get("/projects/{project_id}/autodesk/imports", response_model=list[LinkOut])
def list_imports(project: Project = Depends(project_viewer), db: Session = Depends(get_db)):
    links = db.query(AutodeskLink).filter(AutodeskLink.project_id == project.id).order_by(AutodeskLink.created_at).all()
    return [_link_out(link) for link in links]


@router.post("/projects/{project_id}/autodesk/imports/{link_id}/sync", response_model=LinkOut)
def sync_import(
    link_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    project: Project = Depends(project_editor),
    db: Session = Depends(get_db),
):
    link = db.get(AutodeskLink, link_id)
    if link is None or link.project_id != project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    link.status = "pending"
    db.commit()
    background_tasks.add_task(_run_import, link.id)
    return _link_out(link)


# ---------- webhook ----------


def verify_signature(body: bytes, header: str | None) -> bool:
    """APS signs callbacks with HMAC-SHA1 of the raw body using the webhook
    secret token (x-adsk-signature: 'sha1hash=<hex>'). When no secret is
    configured the check is skipped (development)."""
    secret = get_settings().APS_WEBHOOK_SECRET
    if not secret:
        return True
    if not header:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha1).hexdigest()
    received = header.split("=", 1)[-1].strip()
    return hmac.compare_digest(expected, received)


@router.post("/integrations/autodesk/webhook", status_code=status.HTTP_200_OK)
async def webhook(request: Request, background_tasks: BackgroundTasks) -> dict:
    body = await request.body()
    if not verify_signature(body, request.headers.get("x-adsk-signature")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bad signature")
    try:
        event = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON") from exc

    payload = event.get("payload", {})
    item_id = payload.get("lineageUrn") or payload.get("source")
    link_hint = (event.get("hook", {}).get("hookAttribute") or {}).get("link")
    db = SessionLocal()
    try:
        links = svc.links_for_item(db, item_id) if item_id else []
        if not links and link_hint:
            link = db.get(AutodeskLink, uuid.UUID(link_hint))
            links = [link] if link and link.item_id == item_id else []
        for link in links:
            link.status = "pending"
            background_tasks.add_task(_run_import, link.id)
        db.commit()
        return {"queued": len(links)}
    finally:
        db.close()
