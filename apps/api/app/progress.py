"""Lightweight progress reporting for long conversions.

The job sets the current file with `track(file_id)`; converters call
`report(stage, fraction)` from their loops without knowing about files or
sessions. Progress lands in `files.metadata.progress` through its own short
transaction (so the UI sees it while the job's transaction is still open),
throttled to about one write per second.
"""

from __future__ import annotations

import contextvars
import json
import logging
import time
import uuid
from contextlib import contextmanager

from sqlalchemy import text

from app.db import engine

logger = logging.getLogger(__name__)

_current: contextvars.ContextVar[dict | None] = contextvars.ContextVar("progress_file", default=None)


@contextmanager
def track(file_id: uuid.UUID):
    token = _current.set({"id": str(file_id), "stage": None, "t": 0.0})
    try:
        yield
    finally:
        _current.reset(token)


def report(stage: str, fraction: float | None = None) -> None:
    st = _current.get()
    if st is None:
        return
    now = time.monotonic()
    if stage == st["stage"] and now - st["t"] < 1.0:
        return
    st["stage"], st["t"] = stage, now
    value = {"stage": stage, "fraction": None if fraction is None else round(min(max(fraction, 0.0), 1.0), 3)}
    try:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE files SET metadata = jsonb_set(metadata, '{progress}', CAST(:v AS JSONB)) WHERE id = :id"),
                {"v": json.dumps(value, ensure_ascii=False), "id": st["id"]},
            )
    except Exception:  # noqa: BLE001 -- progress is cosmetic; never fail the job over it
        logger.debug("progress update failed", exc_info=True)
