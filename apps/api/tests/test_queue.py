"""JOB_MODE=queue: uploads and analyses are persisted as jobs and executed by
the worker (claim with FOR UPDATE SKIP LOCKED)."""

import json

from tests.twin_fixtures import make_ifc


def test_queue_mode(client, monkeypatch):
    from app.config import get_settings
    from app.queue import claim_and_run_one

    monkeypatch.setattr(get_settings(), "JOB_MODE", "queue")
    r = client.post("/api/auth/register", json={"email": "q@example.com", "password": "supersecret123",
                                                "full_name": "Q", "organization_name": "Q"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    pid = client.post("/api/projects", json={"name": "Q"}, headers=h).json()["id"]
    f = client.post(f"/api/projects/{pid}/files", headers=h, files={"file": ("m.ifc", make_ifc())},
                    data={"category": "bim", "options": json.dumps({})}).json()
    assert client.get(f"/api/files/{f['id']}", headers=h).json()["status"] == "uploaded"  # not run inline

    assert claim_and_run_one() is True
    assert claim_and_run_one() is False  # queue drained
    rec = client.get(f"/api/files/{f['id']}", headers=h).json()
    assert rec["status"] == "ready", rec["error_message"]

    from app.db import engine

    with engine.connect() as conn:
        row = conn.exec_driver_sql("SELECT kind, status, attempts FROM jobs").one()
    assert tuple(row) == ("parse_file", "done", 1)


def test_queue_priorities(client, monkeypatch):
    from app import queue
    from app.config import get_settings
    from app.db import engine

    monkeypatch.setattr(get_settings(), "JOB_MODE", "queue")
    ran = []
    for kind in ("document_text", "parse_file", "analysis"):
        monkeypatch.setitem(queue.HANDLERS, kind, lambda p, k=kind: ran.append(k))
    queue.enqueue("document_text", {})
    queue.enqueue("parse_file", {})
    queue.enqueue("analysis", {})
    while queue.claim_and_run_one():
        pass
    assert ran == ["analysis", "parse_file", "document_text"]
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT count(*) FROM jobs WHERE status = 'done'").scalar() == 3
