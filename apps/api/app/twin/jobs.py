"""Background conversion of uploaded twin sources into scene assets.

Called from `app.jobs.dispatch_parse` for the twin file categories. Downloads
the raw upload to a temp dir (never fully into memory), runs the matching
converter, uploads the produced tileset under
``projects/{project}/assets/{asset}/`` and records the SceneAsset (+ BIM
element index).
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from datetime import date

from sqlalchemy import func, insert
from sqlalchemy.orm import Session

from app.models import BimElement, FileRecord, Project, SceneAsset
from app.storage import download_to_file, upload_directory

TWIN_CATEGORIES = ("bim", "point_cloud", "reality_mesh")

POINT_CLOUD_FORMATS = ("las", "laz", "e57", "xyz", "pts", "txt", "csv")
MESH_FORMATS = ("obj", "ply", "stl", "glb", "gltf", "off", "zip")


def asset_prefix(project_id: uuid.UUID, asset_id: uuid.UUID) -> str:
    return f"projects/{project_id}/assets/{asset_id}"


def _version_slot(db: Session, file: FileRecord, options: dict) -> tuple[uuid.UUID, int]:
    replaces = options.get("replaces_asset_id")
    if replaces:
        prev = db.get(SceneAsset, uuid.UUID(str(replaces)))
        if prev is not None and prev.project_id == file.project_id:
            latest = (
                db.query(func.max(SceneAsset.version)).filter(SceneAsset.version_group == prev.version_group).scalar()
            )
            return prev.version_group, int(latest or 0) + 1
    return uuid.uuid4(), 1


def _parse_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def process_twin_file(db: Session, file: FileRecord) -> None:
    options = dict(file.metadata_.get("options") or {})
    if not options.get("crs") and options.get("georef_mode") != "anchor":
        project = db.get(Project, file.project_id)
        if project is not None and project.crs:
            options["crs"] = project.crs

    asset_id = uuid.uuid4()
    work = tempfile.mkdtemp(prefix="twin-")
    try:
        ext = os.path.splitext(file.filename)[1].lower() or ".bin"
        raw_path = os.path.join(work, f"source{ext}")
        download_to_file(file.storage_key, raw_path)
        out_dir = os.path.join(work, "out")
        os.makedirs(out_dir, exist_ok=True)

        elements: list[dict] = []
        fmt = file.source_format
        if file.category == "bim":
            if fmt != "ifc":
                raise ValueError(
                    "BIM: поддерживается IFC (2x3/4/4.3). RVT/NWD конвертируются через Autodesk APS "
                    "(раздел «Интеграции») либо экспортируются в IFC из Revit/Navisworks."
                )
            from app.twin.ifc_convert import convert_ifc

            result = convert_ifc(raw_path, out_dir, options)
            elements = result.elements
            kind = "bim"
        elif file.category == "point_cloud":
            if fmt not in POINT_CLOUD_FORMATS:
                raise ValueError(f"Облако точек: формат '{fmt}' не поддерживается (LAS, LAZ, E57, XYZ/PTS)")
            from app.twin.pointcloud_convert import convert_point_cloud

            result = convert_point_cloud(raw_path, fmt, out_dir, options)
            kind = "point_cloud"
        else:
            if fmt not in MESH_FORMATS:
                raise ValueError(
                    f"Mesh: формат '{fmt}' не поддерживается. Используйте OBJ (ZIP с MTL и текстурами), "
                    "PLY, GLB/glTF или ZIP с готовым 3D Tiles. FBX экспортируйте в glTF/OBJ."
                )
            from app.twin import mesh_convert

            if fmt == "zip" and mesh_convert.zip_kind(raw_path) == "tileset":
                result = mesh_convert.import_tileset_zip(raw_path, out_dir)
            else:
                result = mesh_convert.convert_mesh(raw_path, out_dir, options)
            kind = "mesh"

        prefix = asset_prefix(file.project_id, asset_id)
        uploaded = upload_directory(prefix, out_dir)
        stats = {**result.stats, "file_count": uploaded}
        stats.setdefault("entry", "tileset.json")

        group, version = _version_slot(db, file, options)
        name = options.get("name") or os.path.splitext(file.filename)[0] or kind
        asset = SceneAsset(
            id=asset_id,
            project_id=file.project_id,
            source_file_id=file.id,
            name=name,
            kind=kind,
            storage_prefix=prefix,
            georef=result.georef,
            stats=stats,
            version_group=group,
            version=version,
            captured_at=_parse_date(options.get("captured_at")),
        )
        db.add(asset)
        db.flush()

        if elements:
            rows = [
                {
                    "asset_id": asset_id,
                    "global_id": e["global_id"],
                    "ifc_type": e["ifc_type"],
                    "name": e["name"],
                    "storey": e["storey"],
                    "properties": e["properties"],
                    "geometry_hash": e["geometry_hash"],
                    "properties_hash": e["properties_hash"],
                }
                for e in elements
            ]
            seen: set[str] = set()
            unique_rows = []
            for r in rows:  # GlobalIds should be unique, but real files are not always valid
                if r["global_id"] not in seen:
                    seen.add(r["global_id"])
                    unique_rows.append(r)
            for i in range(0, len(unique_rows), 2000):
                db.execute(insert(BimElement), unique_rows[i : i + 2000])

        file.metadata_ = {**file.metadata_, "asset_id": str(asset_id)}
    finally:
        shutil.rmtree(work, ignore_errors=True)
