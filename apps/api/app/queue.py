"""Background job dispatch.

JOB_MODE=inline (default; development, tests): run in the API process via
FastAPI BackgroundTasks, after the response is sent.

JOB_MODE=queue (production): insert a row into the `jobs` table; one or
more `python -m app.worker` processes claim rows with
`SELECT ... FOR UPDATE SKIP LOCKED` and run them. Conversions and analyses
of large data then survive API restarts and scale out horizontally, with no
extra infrastructure beyond PostgreSQL.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable

from fastapi import BackgroundTasks
from sqlalchemy import text

from app.config import get_settings
from app.db import SessionLocal, engine

logger = logging.getLogger(__name__)


def _parse_file(payload: dict) -> None:
    from app.jobs import dispatch_parse

    db = SessionLocal()
    try:
        dispatch_parse(uuid.UUID(payload["file_id"]), db)
    finally:
        db.close()


def _analysis(payload: dict) -> None:
    from app.twin.analysis_jobs import run_analysis

    db = SessionLocal()
    try:
        run_analysis(db, uuid.UUID(payload["analysis_id"]))
    finally:
        db.close()


def _autodesk_import(payload: dict) -> None:
    from app.integrations.autodesk_service import import_link

    db = SessionLocal()
    try:
        import_link(db, uuid.UUID(payload["link_id"]))
    finally:
        db.close()


def _document_text(payload: dict) -> None:
    from app.twin.doc_text import index_version

    db = SessionLocal()
    try:
        index_version(db, uuid.UUID(payload["version_id"]))
    finally:
        db.close()


HANDLERS: dict[str, Callable[[dict], None]] = {
    "parse_file": _parse_file,
    "analysis": _analysis,
    "autodesk_import": _autodesk_import,
    "document_text": _document_text,
}


def enqueue(kind: str, payload: dict, background_tasks: BackgroundTasks | None = None) -> None:
    if kind not in HANDLERS:
        raise ValueError(f"Unknown job kind {kind}")
    if get_settings().JOB_MODE == "queue":
        import json

        with engine.begin() as conn:
            conn.execute(text("INSERT INTO jobs (kind, payload) VALUES (:k, CAST(:p AS JSONB))"),
                         {"k": kind, "p": json.dumps(payload)})
        return
    if background_tasks is not None:
        background_tasks.add_task(HANDLERS[kind], payload)
    else:
        HANDLERS[kind](payload)


def claim_and_run_one(stale_minutes: int = 120, max_attempts: int = 3) -> bool:
    """Claims one queued (or stale running) job and runs it. Returns False when
    the queue is empty."""
    with engine.begin() as conn:
        row = conn.execute(text(
            """
            UPDATE jobs SET status = 'running', locked_at = now(), attempts = attempts + 1
            WHERE id = (
              SELECT id FROM jobs
              WHERE (status = 'queued')
                 OR (status = 'running' AND locked_at < now() - make_interval(mins => :stale) AND attempts < :max)
              ORDER BY id
              FOR UPDATE SKIP LOCKED
              LIMIT 1
            )
            RETURNING id, kind, payload
            """
        ), {"stale": stale_minutes, "max": max_attempts}).first()
    if row is None:
        return False
    job_id, kind, payload = row
    try:
        HANDLERS[kind](payload)
        status, error = "done", None
    except Exception as exc:  # noqa: BLE001 -- handlers record domain errors themselves; this is a last resort
        logger.exception("Job %s (%s) failed", job_id, kind)
        status, error = "error", str(exc)[:2000]
    with engine.begin() as conn:
        conn.execute(text("UPDATE jobs SET status = :s, error = :e, finished_at = now() WHERE id = :id"),
                     {"s": status, "e": error, "id": job_id})
    return True
