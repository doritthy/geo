"""Project documents (ПД / РД / прочее): upload, versions, search, and links
to BIM elements."""

import uuid
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import _require_project_role, get_project_scoped_or_404, project_editor, project_viewer
from app.models import Document, DocumentLink, DocumentVersion, Project, SceneAsset, User
from app.schemas import DocType, DocumentDetail, DocumentLinkCreate, DocumentSummary
from app.schemas import DocumentLink as DocumentLinkSchema
from app.schemas import DocumentVersion as DocumentVersionSchema
from app.queue import enqueue
from app.security import get_current_user
from app.storage import open_stream, upload_fileobj

router = APIRouter(tags=["documents"])


def doc_summary(doc: Document, snippet: str | None = None) -> DocumentSummary:
    latest = doc.versions[-1] if doc.versions else None
    return DocumentSummary(
        id=doc.id, title=doc.title, doc_type=doc.doc_type, code=doc.code, description=doc.description,
        created_at=doc.created_at,
        latest_version=DocumentVersionSchema.model_validate(latest) if latest else None,
        snippet=snippet,
    )


def _fts(q: str):
    return func.to_tsvector("russian", func.coalesce(DocumentVersion.text_content, "")).op("@@")(
        func.websearch_to_tsquery("russian", q)
    )


def doc_detail(doc: Document) -> DocumentDetail:
    base = doc_summary(doc)
    return DocumentDetail(
        **base.model_dump(),
        versions=[DocumentVersionSchema.model_validate(v) for v in doc.versions],
        links=[DocumentLinkSchema.model_validate(link) for link in doc.links],
    )


def _store_version(db: Session, doc: Document, upload: UploadFile, user: User, comment: str | None) -> DocumentVersion:
    next_version = (
        db.query(func.coalesce(func.max(DocumentVersion.version), 0)).filter(DocumentVersion.document_id == doc.id).scalar()
        + 1
    )
    filename = upload.filename or "document"
    key = f"projects/{doc.project_id}/documents/{doc.id}/v{next_version}/{filename}"
    upload.file.seek(0, 2)
    size = upload.file.tell()
    upload.file.seek(0)
    upload_fileobj(key, upload.file, upload.content_type or "application/octet-stream")
    version = DocumentVersion(
        document_id=doc.id, version=next_version, filename=filename, storage_key=key, size_bytes=size,
        comment=comment, uploaded_by=user.id,
    )
    db.add(version)
    return version


@router.get("/api/projects/{project_id}/documents", response_model=list[DocumentSummary])
def list_documents(
    q: str | None = None,
    doc_type: DocType | None = None,
    asset_id: uuid.UUID | None = None,
    global_id: str | None = None,
    project: Project = Depends(project_viewer),
    db: Session = Depends(get_db),
):
    query = db.query(Document).filter(Document.project_id == project.id)
    if doc_type:
        query = query.filter(Document.doc_type == doc_type)
    if q:
        like = f"%{q}%"
        file_match = (
            db.query(DocumentVersion.document_id)
            .filter(or_(DocumentVersion.filename.ilike(like), _fts(q)))
            .scalar_subquery()
        )
        query = query.filter(
            or_(
                Document.title.ilike(like), Document.code.ilike(like), Document.description.ilike(like),
                Document.id.in_(file_match),
            )
        )
    if asset_id or global_id:
        link_q = db.query(DocumentLink.document_id)
        if asset_id:
            link_q = link_q.filter(DocumentLink.asset_id == asset_id)
        if global_id:
            link_q = link_q.filter(DocumentLink.element_global_id == global_id)
        query = query.filter(Document.id.in_(link_q.scalar_subquery()))
    docs = query.order_by(Document.created_at.desc()).all()
    snippets: dict[uuid.UUID, str] = {}
    if q and docs:
        # Newest matching version per document; ts_headline only on matches.
        rows = (
            db.query(
                DocumentVersion.document_id,
                func.ts_headline(
                    "russian", DocumentVersion.text_content, func.websearch_to_tsquery("russian", q),
                    "StartSel=\u0001, StopSel=\u0002, MaxWords=24, MinWords=10, MaxFragments=2, FragmentDelimiter=\" … \"",
                ),
            )
            .filter(DocumentVersion.document_id.in_([d.id for d in docs]), _fts(q))
            .order_by(DocumentVersion.document_id, DocumentVersion.version.desc())
            .distinct(DocumentVersion.document_id)
            .all()
        )
        snippets = {doc_id: text for doc_id, text in rows}
    return [doc_summary(d, snippets.get(d.id)) for d in docs]


@router.post("/api/projects/{project_id}/documents", response_model=DocumentDetail, status_code=status.HTTP_201_CREATED)
def create_document(
    background_tasks: BackgroundTasks,
    title: str = Form(...),
    doc_type: DocType = Form("other"),
    code: str | None = Form(None),
    description: str | None = Form(None),
    asset_id: uuid.UUID | None = Form(None),
    element_global_id: str | None = Form(None),
    file: UploadFile = File(...),
    project: Project = Depends(project_editor),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    doc = Document(project_id=project.id, title=title, doc_type=doc_type, code=code, description=description, created_by=user.id)
    db.add(doc)
    db.flush()
    version = _store_version(db, doc, file, user, None)
    if asset_id:
        asset = db.get(SceneAsset, asset_id)
        if asset is None or asset.project_id != project.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
        db.add(DocumentLink(document_id=doc.id, asset_id=asset_id, element_global_id=element_global_id))
    db.commit()
    enqueue("document_text", {"version_id": str(version.id)}, background_tasks)
    db.refresh(doc)
    return doc_detail(doc)


def _doc_for(document_id: uuid.UUID, db: Session, user: User, editor: bool = False) -> Document:
    doc: Document = get_project_scoped_or_404(Document, document_id, db, user)
    if editor:
        _require_project_role(doc.project_id, "editor", db, user)
    return doc


@router.get("/api/documents/{document_id}", response_model=DocumentDetail)
def get_document(document_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return doc_detail(_doc_for(document_id, db, user))


@router.delete("/api/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = _doc_for(document_id, db, user, editor=True)
    db.delete(doc)
    db.commit()


@router.post("/api/documents/{document_id}/versions", response_model=DocumentDetail, status_code=status.HTTP_201_CREATED)
def add_version(
    background_tasks: BackgroundTasks,
    document_id: uuid.UUID,
    file: UploadFile = File(...),
    comment: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    doc = _doc_for(document_id, db, user, editor=True)
    version = _store_version(db, doc, file, user, comment)
    db.commit()
    enqueue("document_text", {"version_id": str(version.id)}, background_tasks)
    db.refresh(doc)
    return doc_detail(doc)


@router.get("/api/document-versions/{version_id}/download")
def download_version(version_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    version = db.get(DocumentVersion, version_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    _doc_for(version.document_id, db, user)
    body, length = open_stream(version.storage_key)
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(version.filename)}"}
    if length is not None:
        headers["Content-Length"] = str(length)
    return StreamingResponse(body.iter_chunks(chunk_size=256 * 1024), media_type="application/octet-stream", headers=headers)


@router.post("/api/documents/{document_id}/links", response_model=DocumentLinkSchema, status_code=status.HTTP_201_CREATED)
def add_link(
    document_id: uuid.UUID,
    payload: DocumentLinkCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    doc = _doc_for(document_id, db, user, editor=True)
    asset = db.get(SceneAsset, payload.asset_id)
    if asset is None or asset.project_id != doc.project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    existing = (
        db.query(DocumentLink)
        .filter(
            DocumentLink.document_id == doc.id,
            DocumentLink.asset_id == payload.asset_id,
            DocumentLink.element_global_id.is_(None)
            if payload.element_global_id is None
            else DocumentLink.element_global_id == payload.element_global_id,
        )
        .first()
    )
    if existing:
        return existing
    link = DocumentLink(document_id=doc.id, asset_id=payload.asset_id, element_global_id=payload.element_global_id)
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


@router.delete("/api/document-links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_link(link_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    link = db.get(DocumentLink, link_id)
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    _doc_for(link.document_id, db, user, editor=True)
    db.delete(link)
    db.commit()
