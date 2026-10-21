"""Autodesk ACC / BIM 360 import pipeline on top of the APS client.

import_link(link):
  1. resolve the item's tip version (3-legged token of the user who linked it)
  2. native formats (IFC, LAS, ...) -> download the original via signed S3;
     RVT / NWD / DWG -> Model Derivative translation to IFC, then download
  3. register the file like a regular upload (category bim / point_cloud /
     reality_mesh) and run the normal twin conversion; later versions land
     in the same version group, so version comparison works across ACC
     revisions.

Also used for local RVT uploads (2-legged: our transient OSS bucket ->
Model Derivative -> IFC) when APS credentials are configured.
"""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.integrations.aps import NATIVE, TRANSLATE_TO_IFC, APSClient, APSError
from app.integrations.secrets import decrypt, encrypt
from app.models import AutodeskConnection, AutodeskLink, FileRecord, SceneAsset
from app.storage import upload_fileobj

logger = logging.getLogger(__name__)

_CATEGORY_BY_EXT = {
    "ifc": "bim",
    "las": "point_cloud", "laz": "point_cloud", "e57": "point_cloud",
    "obj": "reality_mesh", "glb": "reality_mesh", "gltf": "reality_mesh", "ply": "reality_mesh", "zip": "reality_mesh",
}

# Injected in tests.
client_factory = APSClient


def _ext(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def save_connection(db: Session, user_id: uuid.UUID, token) -> None:
    conn = db.get(AutodeskConnection, user_id) or AutodeskConnection(user_id=user_id)
    conn.access_token = encrypt(token.access_token)
    if token.refresh_token:
        conn.refresh_token = encrypt(token.refresh_token)
    conn.expires_at = datetime.fromtimestamp(token.expires_at, tz=timezone.utc)
    conn.updated_at = datetime.now(timezone.utc)
    db.add(conn)
    db.commit()


def user_token(db: Session, user_id: uuid.UUID, client: APSClient | None = None) -> str:
    """Valid 3-legged access token for the user, refreshed when expiring."""
    conn = db.get(AutodeskConnection, user_id)
    if conn is None:
        raise APSError("Аккаунт Autodesk не подключён", 401)
    expires = conn.expires_at if conn.expires_at.tzinfo else conn.expires_at.replace(tzinfo=timezone.utc)
    if expires - timedelta(seconds=30) > datetime.now(timezone.utc):
        return decrypt(conn.access_token)
    client = client or client_factory()
    token = client.refresh(decrypt(conn.refresh_token))
    save_connection(db, user_id, token)
    return token.access_token


def _version_meta(version: dict) -> tuple[str, str, str | None]:
    """(file name, storage URN, version id) from a Data Management version."""
    attrs = version.get("attributes", {})
    name = attrs.get("name") or attrs.get("displayName") or "model"
    storage = version.get("relationships", {}).get("storage", {}).get("data", {}).get("id")
    if not storage:
        raise APSError("У версии нет файла в хранилище (облачная модель без публикации?)")
    return name, storage, version.get("id")


def _register_file(db: Session, project_id: uuid.UUID, user_id: uuid.UUID | None, path: str, filename: str,
                   category: str, options: dict) -> FileRecord:
    from app.routers.files import infer_source_format

    file_id = uuid.uuid4()
    key = f"projects/{project_id}/files/{file_id}/raw/{filename}"
    with open(path, "rb") as fh:
        upload_fileobj(key, fh)
    record = FileRecord(
        id=file_id, project_id=project_id, filename=filename,
        source_format=infer_source_format(filename, category), category=category, storage_key=key,
        size_bytes=os.path.getsize(path), status="uploaded",
        metadata_={"options": options, "source": "autodesk"}, uploaded_by=user_id,
    )
    db.add(record)
    db.commit()
    return record


def _latest_asset_in_group(db: Session, group: uuid.UUID | None) -> SceneAsset | None:
    if group is None:
        return None
    return (
        db.query(SceneAsset).filter(SceneAsset.version_group == group).order_by(SceneAsset.version.desc()).first()
    )


def import_link(db: Session, link_id: uuid.UUID, version: dict | None = None) -> FileRecord | None:
    """Imports the tip (or given) version of a linked ACC item. Returns the
    FileRecord after the twin conversion ran (status ready/error)."""
    from app.jobs import dispatch_parse

    link = db.get(AutodeskLink, link_id)
    if link is None:
        return None
    client = client_factory()
    try:
        token = user_token(db, link.user_id, client)
        version = version or client.tip_version(token, link.aps_project_id, link.item_id)
        name, storage_urn, version_id = _version_meta(version)
        if version_id and version_id == link.last_version_id:
            link.status = "ready"
            db.commit()
            return None
        ext = _ext(name)
        with tempfile.TemporaryDirectory(prefix="aps-") as work:
            if ext in TRANSLATE_TO_IFC:
                link.status = "translating"
                db.commit()
                b64 = client.translate_to_ifc(token, version_id or storage_urn)
                derivative = client.wait_for_ifc(token, b64)
                filename = os.path.splitext(name)[0] + ".ifc"
                path = os.path.join(work, filename)
                client.download_derivative(token, b64, derivative, path)
                category = "bim"
            elif ext in NATIVE:
                filename = name
                path = os.path.join(work, name)
                client.download_object(token, storage_urn, path)
                category = _CATEGORY_BY_EXT.get(ext, "bim")
            else:
                raise APSError(f"Формат «{ext}» из ACC не поддерживается")

            options = {**(link.options or {}), "name": link.name}
            previous = _latest_asset_in_group(db, link.version_group)
            if previous is not None:
                options["replaces_asset_id"] = str(previous.id)
            record = _register_file(db, link.project_id, link.user_id, path, filename, category, options)

        dispatch_parse(record.id, db)
        db.refresh(record)
        if record.status == "ready":
            asset = db.get(SceneAsset, uuid.UUID(record.metadata_["asset_id"]))
            link.version_group = asset.version_group if asset else link.version_group
            link.last_version_id = version_id
            link.status = "ready"
            link.error_message = None
        else:
            link.status = "error"
            link.error_message = record.error_message
        db.commit()
        return record
    except Exception as exc:  # noqa: BLE001 -- background job: record and move on
        logger.exception("Autodesk import failed for link %s", link_id)
        db.rollback()
        link = db.get(AutodeskLink, link_id)
        if link is not None:
            link.status = "error"
            link.error_message = str(exc)[:2000]
            db.commit()
        return None


def translate_local_file(raw_path: str, filename: str, work_dir: str) -> str:
    """RVT/NWD/DWG uploaded directly: push to our transient OSS bucket and
    convert to IFC with Model Derivative (2-legged). Returns the IFC path."""
    settings = get_settings()
    client = client_factory()
    # Bucket keys are global and limited to [a-z0-9_].
    bucket = "twin_" + "".join(c for c in settings.APS_CLIENT_ID.lower() if c.isalnum())[:40]
    client.ensure_bucket(bucket)
    object_id = client.upload_object(bucket, f"{uuid.uuid4().hex}-{filename}", raw_path)
    token = client.app_token()
    b64 = client.translate_to_ifc(token, object_id, force=True)
    derivative = client.wait_for_ifc(token, b64)
    out = os.path.join(work_dir, os.path.splitext(filename)[0] + ".ifc")
    client.download_derivative(token, b64, derivative, out)
    return out


def links_for_item(db: Session, item_id: str) -> list[AutodeskLink]:
    return db.query(AutodeskLink).filter(AutodeskLink.item_id == item_id).all()

