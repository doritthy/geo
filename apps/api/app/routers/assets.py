"""Scene assets (BIM / point clouds / meshes as 3D Tiles), their tiles, BIM
element index and model version comparison."""

import mimetypes
import posixpath
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import _require_project_role, get_project_scoped_or_404, project_viewer
from app.models import Annotation, BimElement, Document, DocumentLink, Project, SceneAsset, User
from app.schemas import Annotation as AnnotationSchema
from app.schemas import BimElementDetail, BimElementSummary, CompareResult, DocumentSummary, ElementPage
from app.schemas import SceneAsset as SceneAssetSchema
from app.schemas import SceneAssetUpdate
from app.security import get_current_user
from app.storage import delete_prefix, open_stream

router = APIRouter(tags=["assets"])

_TILE_TYPES = {
    ".json": "application/json",
    ".b3dm": "application/octet-stream",
    ".pnts": "application/octet-stream",
    ".i3dm": "application/octet-stream",
    ".cmpt": "application/octet-stream",
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".subtree": "application/octet-stream",
}

# Tile requests are numerous (hundreds per view); cache the access decision
# briefly instead of re-checking project membership for every tile.
_ACCESS_TTL = 60.0
_access_cache: dict[tuple[uuid.UUID, uuid.UUID], tuple[float, str]] = {}


def to_schema(asset: SceneAsset) -> SceneAssetSchema:
    entry = asset.stats.get("entry", "tileset.json")
    return SceneAssetSchema(
        id=asset.id, project_id=asset.project_id, source_file_id=asset.source_file_id, name=asset.name,
        kind=asset.kind, georef=asset.georef, stats=asset.stats, version_group=asset.version_group,
        version=asset.version, captured_at=asset.captured_at, created_at=asset.created_at,
        tileset_url=f"/api/assets/{asset.id}/tiles/{entry}",
    )


def _asset_editor(asset: SceneAsset, db: Session, user: User) -> None:
    _require_project_role(asset.project_id, "editor", db, user)


@router.get("/api/projects/{project_id}/assets", response_model=list[SceneAssetSchema])
def list_assets(project: Project = Depends(project_viewer), db: Session = Depends(get_db)):
    assets = (
        db.query(SceneAsset)
        .filter(SceneAsset.project_id == project.id)
        .order_by(SceneAsset.kind, SceneAsset.name, SceneAsset.version)
        .all()
    )
    return [to_schema(a) for a in assets]


@router.get("/api/assets/{asset_id}", response_model=SceneAssetSchema)
def get_asset(asset_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return to_schema(get_project_scoped_or_404(SceneAsset, asset_id, db, user))


@router.patch("/api/assets/{asset_id}", response_model=SceneAssetSchema)
def update_asset(
    asset_id: uuid.UUID,
    payload: SceneAssetUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    asset: SceneAsset = get_project_scoped_or_404(SceneAsset, asset_id, db, user)
    _asset_editor(asset, db, user)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"]:
        asset.name = data["name"]
    if "captured_at" in data:
        asset.captured_at = data["captured_at"]

    placement = {k: data[k] for k in ("longitude", "latitude", "height", "heading", "scale") if k in data}
    georef = dict(asset.georef)
    if placement:
        if georef.get("mode") != "anchor":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Модель привязана по системе координат; используйте offset_enu для точной подгонки",
            )
        georef.update({k: float(v) for k, v in placement.items() if v is not None})
        georef["source"] = "manual"
    if "offset_enu" in data:
        georef["offset_enu"] = [float(v) for v in data["offset_enu"]] if data["offset_enu"] else None
    asset.georef = georef
    db.commit()
    db.refresh(asset)
    return to_schema(asset)


@router.delete("/api/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset(asset_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    asset: SceneAsset = get_project_scoped_or_404(SceneAsset, asset_id, db, user)
    _asset_editor(asset, db, user)
    prefix = asset.storage_prefix
    db.delete(asset)
    db.commit()
    delete_prefix(prefix + "/")
    _access_cache.clear()


@router.get("/api/assets/{asset_id}/versions", response_model=list[SceneAssetSchema])
def list_versions(asset_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    asset: SceneAsset = get_project_scoped_or_404(SceneAsset, asset_id, db, user)
    rows = (
        db.query(SceneAsset)
        .filter(SceneAsset.version_group == asset.version_group, SceneAsset.project_id == asset.project_id)
        .order_by(SceneAsset.version)
        .all()
    )
    return [to_schema(a) for a in rows]


@router.get("/api/assets/{asset_id}/tiles/{path:path}")
def get_tile(
    asset_id: uuid.UUID, path: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    now = time.monotonic()
    cached = _access_cache.get((user.id, asset_id))
    if cached and now - cached[0] < _ACCESS_TTL:
        prefix = cached[1]
    else:
        asset: SceneAsset = get_project_scoped_or_404(SceneAsset, asset_id, db, user)
        prefix = asset.storage_prefix
        _access_cache[(user.id, asset_id)] = (now, prefix)
        if len(_access_cache) > 10_000:
            _access_cache.clear()

    clean = posixpath.normpath("/" + path).lstrip("/")
    if not clean or clean.startswith(".."):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    try:
        body, length = open_stream(f"{prefix}/{clean}")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc

    ext = posixpath.splitext(clean)[1].lower()
    media = _TILE_TYPES.get(ext) or mimetypes.guess_type(clean)[0] or "application/octet-stream"
    headers = {"Cache-Control": "private, max-age=3600"}
    if length is not None:
        headers["Content-Length"] = str(length)
    return StreamingResponse(body.iter_chunks(chunk_size=256 * 1024), media_type=media, headers=headers)


# ---------- BIM elements ----------


@router.get("/api/assets/{asset_id}/elements", response_model=ElementPage)
def list_elements(
    asset_id: uuid.UUID,
    q: str | None = None,
    ifc_type: str | None = None,
    storey: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    get_project_scoped_or_404(SceneAsset, asset_id, db, user)
    query = db.query(BimElement).filter(BimElement.asset_id == asset_id)
    if ifc_type:
        query = query.filter(BimElement.ifc_type == ifc_type)
    if storey:
        query = query.filter(BimElement.storey == storey)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(BimElement.name.ilike(like), BimElement.global_id.ilike(like), BimElement.ifc_type.ilike(like)))
    total = query.count()
    items = query.order_by(BimElement.ifc_type, BimElement.name).offset(offset).limit(limit).all()
    return ElementPage(total=total, items=[BimElementSummary.model_validate(i) for i in items])


@router.get("/api/assets/{asset_id}/elements/{global_id}", response_model=BimElementDetail)
def get_element(
    asset_id: uuid.UUID, global_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    asset: SceneAsset = get_project_scoped_or_404(SceneAsset, asset_id, db, user)
    element = (
        db.query(BimElement).filter(BimElement.asset_id == asset_id, BimElement.global_id == global_id).first()
    )
    if element is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    # Documents/annotations bound to this GlobalId on any version of the model.
    group_ids = [
        a for (a,) in db.query(SceneAsset.id).filter(SceneAsset.version_group == asset.version_group).all()
    ]
    docs = (
        db.query(Document)
        .join(DocumentLink, DocumentLink.document_id == Document.id)
        .filter(
            DocumentLink.asset_id.in_(group_ids),
            or_(DocumentLink.element_global_id == global_id, DocumentLink.element_global_id.is_(None)),
        )
        .distinct()
        .all()
    )
    notes = (
        db.query(Annotation)
        .filter(Annotation.project_id == asset.project_id, Annotation.element_global_id == global_id)
        .order_by(Annotation.created_at.desc())
        .all()
    )
    from app.routers.documents import doc_summary

    return BimElementDetail(
        global_id=element.global_id, ifc_type=element.ifc_type, name=element.name, storey=element.storey,
        properties=element.properties, bbox=element.bbox,
        documents=[doc_summary(d) for d in docs],
        annotations=[AnnotationSchema.model_validate(n) for n in notes],
    )


@router.get("/api/assets/{asset_id}/compare", response_model=CompareResult)
def compare_versions(
    asset_id: uuid.UUID,
    other: uuid.UUID,
    limit: int = Query(5000, ge=1, le=50000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Element-level diff between two BIM assets by IFC GlobalId:
    added / removed / geometry changed / properties changed (base -> other)."""
    base: SceneAsset = get_project_scoped_or_404(SceneAsset, asset_id, db, user)
    target: SceneAsset = get_project_scoped_or_404(SceneAsset, other, db, user)
    if base.kind != "bim" or target.kind != "bim":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Сравнение доступно только для BIM-моделей")

    cols = (BimElement.global_id, BimElement.ifc_type, BimElement.name, BimElement.storey,
            BimElement.geometry_hash, BimElement.properties_hash)
    a = {r[0]: r for r in db.query(*cols).filter(BimElement.asset_id == base.id).all()}
    b = {r[0]: r for r in db.query(*cols).filter(BimElement.asset_id == target.id).all()}

    def summ(r):
        return BimElementSummary(global_id=r[0], ifc_type=r[1], name=r[2], storey=r[3])

    added = [summ(b[g]) for g in b.keys() - a.keys()]
    removed = [summ(a[g]) for g in a.keys() - b.keys()]
    common = a.keys() & b.keys()
    geom = [summ(b[g]) for g in common if a[g][4] != b[g][4]]
    props = [summ(b[g]) for g in common if a[g][4] == b[g][4] and a[g][5] != b[g][5]]
    counts = {
        "added": len(added), "removed": len(removed), "modified_geometry": len(geom),
        "modified_properties": len(props), "unchanged": len(common) - len(geom) - len(props),
    }
    truncated = any(len(x) > limit for x in (added, removed, geom, props))
    return CompareResult(
        base_asset_id=base.id, other_asset_id=target.id, counts=counts,
        added=added[:limit], removed=removed[:limit], modified_geometry=geom[:limit],
        modified_properties=props[:limit], truncated=truncated,
    )


@router.get("/api/assets/{asset_id}/documents", response_model=list[DocumentSummary])
def asset_documents(asset_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    get_project_scoped_or_404(SceneAsset, asset_id, db, user)
    from app.routers.documents import doc_summary

    docs = (
        db.query(Document)
        .join(DocumentLink, DocumentLink.document_id == Document.id)
        .filter(DocumentLink.asset_id == asset_id)
        .distinct()
        .all()
    )
    return [doc_summary(d) for d in docs]
