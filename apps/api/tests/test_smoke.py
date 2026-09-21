"""Smoke tests: app import + /docs, full auth flow, project creation, and an
end-to-end LAS upload -> parse -> well_log row -> binary data round trip.
Runs against a real (ephemeral) Postgres+PostGIS database and a real
S3-compatible HTTP server -- see tests/conftest.py.
"""

import struct

import numpy as np


def test_app_imports_and_docs_loads(client):
    resp = client.get("/docs")
    assert resp.status_code == 200

    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    assert "paths" in resp.json()


def _register(client, email="alice@example.com", org="Acme Geo"):
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": "supersecret123", "full_name": "Alice", "organization_name": org},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_register_and_login_flow(client):
    data = _register(client)
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "alice@example.com"
    assert data["user"]["role"] == "admin"

    resp = client.post(
        "/api/auth/login", json={"email": "alice@example.com", "password": "supersecret123"}
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]

    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "alice@example.com"

    # Wrong password
    resp = client.post("/api/auth/login", json={"email": "alice@example.com", "password": "wrong"})
    assert resp.status_code == 401

    # No auth
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def _auth_headers(client, email="alice@example.com", org="Acme Geo") -> dict:
    data = _register(client, email=email, org=org)
    return {"Authorization": f"Bearer {data['access_token']}"}


def test_create_project(client):
    headers = _auth_headers(client)

    resp = client.post("/api/projects", json={"name": "Field A", "description": "test field"}, headers=headers)
    assert resp.status_code == 201, resp.text
    project = resp.json()
    assert project["name"] == "Field A"
    assert project["default_crs_epsg"] == 4326

    resp = client.get("/api/projects", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp = client.get(f"/api/projects/{project['id']}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == project["id"]


def test_project_isolation_returns_404_not_403(client):
    headers_a = _auth_headers(client, email="a@corp1.com", org="Corp 1")
    headers_b = _auth_headers(client, email="b@corp2.com", org="Corp 2")

    resp = client.post("/api/projects", json={"name": "Corp1 Field"}, headers=headers_a)
    project_id = resp.json()["id"]

    # Different org, same-ish request -> 404, never 403 (no existence leak).
    resp = client.get(f"/api/projects/{project_id}", headers=headers_b)
    assert resp.status_code == 404

    resp = client.get(f"/api/projects/{project_id}")
    assert resp.status_code == 401

    resp = client.get("/api/projects/00000000-0000-0000-0000-000000000000", headers=headers_a)
    assert resp.status_code == 404


def test_las_upload_end_to_end(client, fixtures_dir):
    headers = _auth_headers(client)
    project = client.post("/api/projects", json={"name": "LAS Field"}, headers=headers).json()

    las_bytes = (fixtures_dir / "sample.las").read_bytes()
    resp = client.post(
        f"/api/projects/{project['id']}/files",
        headers=headers,
        data={"category": "well_log"},
        files={"file": ("sample.las", las_bytes, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    file_record = resp.json()
    assert file_record["source_format"] == "las"
    assert file_record["category"] == "well_log"

    # By the time TestClient returns, BackgroundTasks (parse job) has run.
    resp = client.get(f"/api/files/{file_record['id']}", headers=headers)
    assert resp.status_code == 200
    file_record = resp.json()
    assert file_record["status"] == "ready", file_record.get("error_message")
    assert "well_id" in file_record["metadata"]

    # A well was created from the LAS header.
    resp = client.get(f"/api/projects/{project['id']}/wells", headers=headers)
    assert resp.status_code == 200
    wells = resp.json()
    assert len(wells) == 1
    assert wells[0]["name"] == "TEST-1"
    assert wells[0]["surface_x"] == 500000.0
    well_id = wells[0]["id"]

    resp = client.get(f"/api/wells/{well_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["kb_elevation"] == 100.0

    # Two curves (GR, RHOB) became well_logs rows.
    resp = client.get(f"/api/wells/{well_id}/logs", headers=headers)
    assert resp.status_code == 200
    logs = resp.json()
    assert {log["curve_name"] for log in logs} == {"GR", "RHOB"}
    gr_log = next(log for log in logs if log["curve_name"] == "GR")
    assert gr_log["sample_count"] == 11
    assert gr_log["min_value"] == 48.0
    assert gr_log["max_value"] == 60.0

    # Binary log data: interleaved float32 [depth, value, depth, value, ...].
    resp = client.get(f"/api/wells/{well_id}/logs/{gr_log['id']}/data", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/octet-stream"
    body = resp.content
    assert len(body) == gr_log["sample_count"] * 2 * 4

    values = np.frombuffer(body, dtype="<f4")
    depths = values[0::2]
    grs = values[1::2]
    assert depths[0] == 1000.0
    assert depths[-1] == 1010.0
    assert grs[0] == 50.0
    assert grs[4] == 60.0


def test_add_project_member(client):
    owner_headers = _auth_headers(client, email="owner2@corp.com", org="Corp2")
    project = client.post("/api/projects", json={"name": "Shared Field"}, headers=owner_headers).json()

    # A second user, same org: register creates a *new* org, so instead we
    # simulate "an existing user of the same org" the way the contract
    # implies -- via the DB directly is out of scope for an HTTP-level test,
    # so here we confirm the negative case: a user from a different org
    # cannot be added (not found in organization) and a non-owner cannot add
    # members at all.
    outsider_headers = _auth_headers(client, email="outsider@other.com", org="OtherOrg")

    resp = client.post(
        f"/api/projects/{project['id']}/members",
        json={"email": "outsider@other.com", "role": "viewer"},
        headers=owner_headers,
    )
    assert resp.status_code == 404  # not in the same organization

    resp = client.post(
        f"/api/projects/{project['id']}/members",
        json={"email": "owner2@corp.com", "role": "viewer"},
        headers=outsider_headers,
    )
    assert resp.status_code == 404  # outsider has no access to this project at all


def test_add_project_member_grants_access(client, db_session):
    from app.security import hash_password

    owner_headers = _auth_headers(client, email="owner3@corp.com", org="Corp3")
    me = client.get("/api/auth/me", headers=owner_headers).json()
    project = client.post("/api/projects", json={"name": "Shared Field 2"}, headers=owner_headers).json()

    # Create a second user directly in the same organization (register()
    # always creates a brand-new org, so this is the same-org case the
    # contract's members endpoint is for).
    from app.models import User

    teammate = User(
        organization_id=me["organization_id"],
        email="teammate@corp3.com",
        password_hash=hash_password("teammate123"),
        full_name="Teammate",
        role="geologist",
    )
    db_session.add(teammate)
    db_session.commit()

    resp = client.post(
        "/api/auth/login", json={"email": "teammate@corp3.com", "password": "teammate123"}
    )
    teammate_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    # Before being added: no access.
    resp = client.get(f"/api/projects/{project['id']}", headers=teammate_headers)
    assert resp.status_code == 404

    resp = client.post(
        f"/api/projects/{project['id']}/members",
        json={"email": "teammate@corp3.com", "role": "viewer"},
        headers=owner_headers,
    )
    assert resp.status_code == 201

    # Now a viewer: can read, cannot upload files.
    resp = client.get(f"/api/projects/{project['id']}", headers=teammate_headers)
    assert resp.status_code == 200

    resp = client.post(
        f"/api/projects/{project['id']}/files",
        headers=teammate_headers,
        data={"category": "well_log"},
        files={"file": ("x.las", b"~VERSION\n~WELL\n~CURVE\n~ASCII\n", "application/octet-stream")},
    )
    assert resp.status_code == 404  # viewer role is read-only


def test_file_upload_requires_editor_role(client, fixtures_dir):
    owner_headers = _auth_headers(client, email="owner@corp.com", org="Corp")
    project = client.post("/api/projects", json={"name": "Field"}, headers=owner_headers).json()

    # A second user in a different org has no access at all (404).
    other_headers = _auth_headers(client, email="viewer@other.com", org="Other Corp")
    las_bytes = (fixtures_dir / "sample.las").read_bytes()
    resp = client.post(
        f"/api/projects/{project['id']}/files",
        headers=other_headers,
        data={"category": "well_log"},
        files={"file": ("sample.las", las_bytes, "application/octet-stream")},
    )
    assert resp.status_code == 404
