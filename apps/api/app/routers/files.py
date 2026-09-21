import json
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.deps import get_project_scoped_or_404, project_editor, project_viewer
from app.jobs import dispatch_parse
from app.models import FileRecord as FileModel
from app.models import Project, User
from app.schemas import FileCategory
from app.schemas import FileRecord as FileSchema
from app.security import get_current_user
from app.storage import presigned_url, upload_bytes

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
}


def infer_source_format(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
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

    raw = await file.read()
    source_format = infer_source_format(file.filename or "")
    file_id = uuid.uuid4()
    storage_key = f"projects/{project.id}/files/{file_id}/raw/{file.filename}"

    record = FileModel(
        id=file_id,
        project_id=project.id,
        filename=file.filename or "unnamed",
        source_format=source_format,
        category=category,
        storage_key=storage_key,
        size_bytes=len(raw),
        status="uploaded",
        metadata_={
            **({"crs_epsg": crs_epsg} if crs_epsg is not None else {}),
            **({"column_mapping": mapping} if mapping is not None else {}),
        },
        uploaded_by=user.id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    upload_bytes(storage_key, raw)

    background_tasks.add_task(_run_parse_job, file_id)

    return record


def _run_parse_job(file_id: uuid.UUID) -> None:
    # Runs in the BackgroundTask's own DB session (the request's session is
    # already closed by the time this executes).
    db = SessionLocal()
    try:
        dispatch_parse(file_id, db)
    finally:
        db.close()


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
