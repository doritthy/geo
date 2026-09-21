"""Coverage for GRDECL grid ingestion + binary grid endpoints, GeoTIFF
surface ingestion + binary heights, CSV trajectory ingestion, and
formations CRUD. Same real Postgres+PostGIS / real S3-server backend as
test_smoke.py (see tests/conftest.py).
"""

import numpy as np


def _auth_headers(client, email="grids@example.com", org="Grids Org") -> dict:
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": "supersecret123", "full_name": "T", "organization_name": org},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _upload(client, headers, project_id, category, path, crs_epsg=None):
    data = {"category": category}
    if crs_epsg is not None:
        data["crs_epsg"] = str(crs_epsg)
    resp = client.post(
        f"/api/projects/{project_id}/files",
        headers=headers,
        data=data,
        files={"file": (path.name, path.read_bytes(), "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    file_record = resp.json()
    resp = client.get(f"/api/files/{file_record['id']}", headers=headers)
    assert resp.status_code == 200
    return resp.json()


def test_grdecl_corner_point_grid_end_to_end(client, fixtures_dir):
    headers = _auth_headers(client)
    project = client.post("/api/projects", json={"name": "Grid Field"}, headers=headers).json()

    file_record = _upload(client, headers, project["id"], "grid", fixtures_dir / "sample.grdecl")
    assert file_record["status"] == "ready", file_record.get("error_message")
    grid_id = file_record["metadata"]["grid_id"]

    resp = client.get(f"/api/projects/{project['id']}/grids", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp = client.get(f"/api/grids/{grid_id}", headers=headers)
    assert resp.status_code == 200
    detail = resp.json()
    assert (detail["nx"], detail["ny"], detail["nz"]) == (2, 2, 2)
    assert detail["active_cell_count"] == 8
    assert detail["bounds"] == {"minX": 0.0, "minY": 0.0, "minZ": 0.0, "maxX": 200.0, "maxY": 200.0, "maxZ": 200.0}
    prop_names = {p["name"] for p in detail["properties"]}
    assert prop_names == {"PORO", "PERMX"}

    # Binary /cells layout: centers f32[n*3], sizes f32[n*3], cellId u32[n].
    resp = client.get(f"/api/grids/{grid_id}/cells", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["x-cell-count"] == "8"
    body = resp.content
    n = 8
    assert len(body) == n * 3 * 4 + n * 3 * 4 + n * 4
    centers = np.frombuffer(body, dtype="<f4", count=n * 3, offset=0).reshape(n, 3)
    sizes = np.frombuffer(body, dtype="<f4", count=n * 3, offset=n * 3 * 4).reshape(n, 3)
    cell_ids = np.frombuffer(body, dtype="<u4", count=n, offset=n * 3 * 4 * 2)
    assert np.allclose(sizes, 100.0)
    assert list(cell_ids) == list(range(8))
    # First cell (i=0,j=0,k=0) is centered at (50,50,50).
    assert np.allclose(sorted(centers.tolist())[0], [50.0, 50.0, 50.0])

    # LOD subsampling: lod=1 => stride 4 => 2 cells out of 8.
    resp = client.get(f"/api/grids/{grid_id}/cells", params={"lod": 1}, headers=headers)
    assert resp.status_code == 200
    assert resp.headers["x-cell-count"] == "2"

    resp = client.get(f"/api/grids/{grid_id}/properties/PORO", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/octet-stream"
    values = np.frombuffer(resp.content, dtype="<f4")
    assert len(values) == 8
    assert np.isclose(values.min(), 0.1, atol=1e-3)
    assert np.isclose(values.max(), 0.3, atol=1e-3)

    resp = client.get(f"/api/grids/{grid_id}/properties/DOES_NOT_EXIST", headers=headers)
    assert resp.status_code == 404

    # Trilinear sample at the exact center of cell (0,0,0).
    resp = client.post(
        f"/api/grids/{grid_id}/sample",
        json={"x": 50.0, "y": 50.0, "z": 50.0, "property": "PORO"},
        headers=headers,
    )
    assert resp.status_code == 200
    sample = resp.json()
    assert sample["interpolation"] == "trilinear"
    assert abs(sample["value"] - 0.1) < 1e-3

    # Outside the grid bounds -> nearest.
    resp = client.post(
        f"/api/grids/{grid_id}/sample",
        json={"x": -1000.0, "y": -1000.0, "z": -1000.0, "property": "PORO"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["interpolation"] == "nearest"


def test_geotiff_surface_end_to_end(client, fixtures_dir):
    headers = _auth_headers(client, email="surf@example.com", org="Surf Org")
    project = client.post("/api/projects", json={"name": "Surface Field"}, headers=headers).json()

    file_record = _upload(client, headers, project["id"], "surface", fixtures_dir / "sample.tif", crs_epsg=32639)
    assert file_record["status"] == "ready", file_record.get("error_message")
    surface_id = file_record["metadata"]["surface_id"]

    resp = client.get(f"/api/surfaces/{surface_id}", headers=headers)
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["cols"] == 3 and detail["rows"] == 3
    assert detail["crs_epsg"] == 32639
    assert detail["min_z"] == 10.0 and detail["max_z"] == 90.0

    resp = client.get(f"/api/surfaces/{surface_id}/heights", headers=headers)
    assert resp.status_code == 200
    heights = np.frombuffer(resp.content, dtype="<f4")
    assert len(heights) == 9
    assert list(heights) == [10, 20, 30, 40, 50, 60, 70, 80, 90]


def test_csv_trajectory_minimum_curvature(client, fixtures_dir):
    headers = _auth_headers(client, email="traj@example.com", org="Traj Org")
    project = client.post("/api/projects", json={"name": "Traj Field"}, headers=headers).json()

    file_record = _upload(client, headers, project["id"], "well_trajectory", fixtures_dir / "trajectory.csv")
    assert file_record["status"] == "ready", file_record.get("error_message")
    well_id = file_record["metadata"]["well_id"]
    assert file_record["metadata"]["point_count"] == 5

    resp = client.get(f"/api/wells/{well_id}/trajectory", headers=headers)
    assert resp.status_code == 200
    points = resp.json()
    assert len(points) == 5
    assert points[0]["md"] == 0.0 and points[0]["tvd"] == 0.0
    # Monotonically increasing MD/TVD for this simple deviation survey.
    mds = [p["md"] for p in points]
    tvds = [p["tvd"] for p in points]
    assert mds == sorted(mds)
    assert tvds == sorted(tvds)
    assert points[-1]["tvd"] < points[-1]["md"]  # well has deviated, TVD < MD


def test_unsupported_format_stored_with_error(client):
    headers = _auth_headers(client, email="unsup@example.com", org="Unsup Org")
    project = client.post("/api/projects", json={"name": "Unsup Field"}, headers=headers).json()

    resp = client.post(
        f"/api/projects/{project['id']}/files",
        headers=headers,
        data={"category": "map_vector"},
        files={"file": ("drawing.dxf", b"dummy dxf content", "application/octet-stream")},
    )
    assert resp.status_code == 201
    file_id = resp.json()["id"]

    resp = client.get(f"/api/files/{file_id}", headers=headers)
    body = resp.json()
    assert body["status"] == "error"
    assert "DXF" in body["error_message"]


def test_formations_crud(client):
    headers = _auth_headers(client, email="form@example.com", org="Form Org")
    project = client.post("/api/projects", json={"name": "Formations Field"}, headers=headers).json()

    resp = client.post(
        f"/api/projects/{project['id']}/formations",
        json={"name": "Reservoir A", "color": "#112233"},
        headers=headers,
    )
    assert resp.status_code == 201
    formation = resp.json()
    assert formation["name"] == "Reservoir A"
    assert formation["color"] == "#112233"

    resp = client.get(f"/api/projects/{project['id']}/formations", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1
