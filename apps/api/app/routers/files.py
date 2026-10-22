import json
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_project_scoped_or_404, project_editor, project_viewer
from app.queue import enqueue
from app.models import FileRecord as FileModel
from app.models import Project, User
from app.schemas import FileCategory
from app.schemas import FileRecord as FileSchema
from app.security import get_current_user
from app.storage import presigned_url, upload_fileobj

router = APIRouter(tags=["files"])

_EXTENSION_MAP = {
    "las": "las",
    "grdecl": "grdecl",
    "data": "grdecl",
    "inc": "grdecl",
    "tif": "geotiff",
    "tiff": "geotiff",
    "shp": "shp",
    "zip": "shp",
    "csv": "csv_trajectory",
    "txt": "csv_trajectory",
    "obj": "obj",
    "ply": "ply",
    "stl": "stl",
    "xyz": "xyz",
    "grd": "surfer_grd",
    "epc": "resqml",
    "dxf": "dxf",
    "dwg": "dwg",
    # construction digital twin
    "ifc": "ifc",
    "rvt": "rvt",
    "nwd": "nwd",
    "laz": "laz",
    "e57": "e57",
    "pts": "pts",
    "glb": "glb",
    "gltf": "gltf",
    "off": "off",
    "geojson": "geojson",
    "json": "geojson",
    "kml": "kml",
    "kmz": "kmz",
    "gpkg": "gpkg",
}

# Extensions whose meaning depends on the chosen category.
_CATEGORY_FORMAT_OVERRIDES = {
    ("point_cloud", "las"): "las",
    ("point_cloud", "txt"): "xyz",
    ("point_cloud", "csv"): "csv",
    ("point_cloud", "xyz"): "xyz",
    ("reality_mesh", "zip"): "zip",
    ("map_vector", "zip"): "shp",
}


def infer_source_format(filename: str, category: str | None = None) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if category and (category, ext) in _CATEGORY_FORMAT_OVERRIDES:
        return _CATEGORY_FORMAT_OVERRIDES[(category, ext)]
    return _EXTENSION_MAP.get(ext, ext or "unknown")


@router.post(
    "/api/projects/{project_id}/files",
    response_model=FileSchema,
    status_code=status.HTTP_201_CREATED,
)
async def upload_file(
    background_tasks: BackgroundTasks,
    category: FileCategory = Form(...),
    crs_epsg: int | None = Form(None),
    column_mapping: str | None = Form(None),
    options: str | None = Form(None),
    file: UploadFile = File(...),
    project: Project = Depends(project_editor),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileModel:
    mapping: dict | None = None
    if column_mapping:
        try:
            mapping = json.loads(column_mapping)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid column_mapping JSON") from exc
    twin_options: dict | None = None
    if options:
        try:
            twin_options = json.loads(options)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid options JSON") from exc
        if not isinstance(twin_options, dict):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="options must be a JSON object")

    source_format = infer_source_format(file.filename or "", category)
    file_id = uuid.uuid4()
    storage_key = f"projects/{project.id}/files/{file_id}/raw/{file.filename}"

    record = FileModel(
        id=file_id,
        project_id=project.id,
        filename=file.filename or "unnamed",
        source_format=source_format,
        category=category,
        storage_key=storage_key,
        size_bytes=_size_of(file),
        status="uploaded",
        metadata_={
            **({"crs_epsg": crs_epsg} if crs_epsg is not None else {}),
            **({"column_mapping": mapping} if mapping is not None else {}),
            **({"options": twin_options} if twin_options is not None else {}),
        },
        uploaded_by=user.id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    # Stream the (possibly multi-GB) upload from Starlette's spooled temp file
    # straight to the object store instead of reading it into memory.
    file.file.seek(0)
    upload_fileobj(storage_key, file.file)

    enqueue("parse_file", {"file_id": str(file_id)}, background_tasks)

    return record


def _size_of(file: UploadFile) -> int:
    if file.size is not None:
        return int(file.size)
    pos = file.file.tell()
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(pos)
    return size


@router.get("/api/projects/{project_id}/files", response_model=list[FileSchema])
def list_files(project: Project = Depends(project_viewer), db: Session = Depends(get_db)) -> list[FileModel]:
    return (
        db.query(FileModel)
        .filter(FileModel.project_id == project.id)
        .order_by(FileModel.uploaded_at.desc())
        .all()
    )


@router.get("/api/files/{file_id}", response_model=FileSchema)
def get_file(file_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> FileModel:
    return get_project_scoped_or_404(FileModel, file_id, db, user)


@router.get("/api/files/{file_id}/download")
def download_file(file_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    record: FileModel = get_project_scoped_or_404(FileModel, file_id, db, user)
    url = presigned_url(record.storage_key)
    return RedirectResponse(url=url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
