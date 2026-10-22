"""Text extraction from project documents for full-text search.

PDF (text layer via pypdf; scanned drawings without a text layer yield
nothing — OCR is out of scope), DOCX, XLSX and plain text. Output is capped
so a huge specification does not bloat the row.
"""

from __future__ import annotations

import io
import logging
import re
import uuid
import zipfile

from sqlalchemy.orm import Session

from app.models import DocumentVersion
from app.storage import open_stream

logger = logging.getLogger(__name__)

MAX_CHARS = 2_000_000
MAX_PAGES = 3000
MAX_BYTES = 300 * 1024 * 1024


def _pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    parts, total = [], 0
    for page in reader.pages[:MAX_PAGES]:
        try:
            t = page.extract_text() or ""
        except Exception:  # noqa: BLE001 -- one broken page must not lose the rest
            continue
        parts.append(t)
        total += len(t)
        if total > MAX_CHARS:
            break
    return "\n".join(parts)


def _xml_text(xml: bytes) -> str:
    return re.sub(r"<[^>]+>", " ", xml.decode("utf-8", "ignore"))


def _docx(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = [n for n in zf.namelist() if re.match(r"word/(document|header\d*|footer\d*)\.xml$", n)]
        return "\n".join(_xml_text(zf.read(n).replace(b"</w:p>", b"</w:p>\n")) for n in names)


def _xlsx(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return _xml_text(zf.read("xl/sharedStrings.xml")) if "xl/sharedStrings.xml" in zf.namelist() else ""


def extract_text(data: bytes, filename: str) -> str:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext == "pdf" or data[:5] == b"%PDF-":
        text = _pdf(data)
    elif ext == "docx":
        text = _docx(data)
    elif ext == "xlsx":
        text = _xlsx(data)
    elif ext in ("txt", "csv", "md"):
        text = data.decode("utf-8", "ignore")
    else:
        return ""
    text = re.sub(r"[ \t ]+", " ", text.replace("\x00", ""))
    return re.sub(r"\n\s*\n+", "\n", text).strip()[:MAX_CHARS]


def index_version(db: Session, version_id: uuid.UUID) -> None:
    v = db.get(DocumentVersion, version_id)
    if v is None:
        return
    try:
        if v.size_bytes > MAX_BYTES:
            v.text_content, v.text_status = None, "none"
        else:
            body, _ = open_stream(v.storage_key)
            text = extract_text(body.read(), v.filename)
            v.text_content, v.text_status = (text or None), ("ready" if text else "none")
    except Exception:  # noqa: BLE001 -- a malformed file only loses search, not the document
        logger.exception("Text extraction failed for document version %s", version_id)
        v.text_content, v.text_status = None, "error"
    db.commit()
