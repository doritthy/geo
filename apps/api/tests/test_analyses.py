"""Deviation map and ICP alignment on the demo building + synthetic as-built
scan (scripts/make_demo_data.py): slab 3 sags 4 cm in the scan."""

import json

import pytest

from scripts.make_demo_data import make_building, make_scan


def _headers(client):
    r = client.post("/api/auth/register", json={"email": "an@example.com", "password": "supersecret123",
                                                "full_name": "A", "organization_name": "BI"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _upload(client, h, pid, name, data, category, options=None):
    r = client.post(f"/api/projects/{pid}/files", headers=h, files={"file": (name, data)},
                    data={"category": category, **({"options": json.dumps(options)} if options else {})})
    rec = client.get(f"/api/files/{r.json()['id']}", headers=h).json()
    assert rec["status"] == "ready", rec["error_message"]
    return rec["metadata"]["asset_id"]


@pytest.fixture()
def scene(client):
    h = _headers(client)
    pid = client.post("/api/projects", json={"name": "Demo", "crs": "EPSG:32642"}, headers=h).json()["id"]
    bim = _upload(client, h, pid, "b.ifc", make_building(storeys=3), "bim")
    scan = _upload(client, h, pid, "s.laz", make_scan(spacing=0.25), "point_cloud")
    return h, pid, bim, scan


def test_deviation_map(client, scene):
    h, pid, bim, scan = scene
    r = client.post(f"/api/projects/{pid}/analyses/deviation", headers=h,
                    json={"cloud_asset_id": scan, "bim_asset_id": bim})
    assert r.status_code == 201
    a = client.get(f"/api/analyses/{r.json()['id']}", headers=h).json()
    assert a["status"] == "ready", a["error_message"]
    hist = a["result"]["histogram"]
    assert hist["related_points"] > 0 and hist["unrelated_points"] > 0  # terrain is not part of the model
    assert hist["within_tolerance"] > 0.8
    slab = next(e for e in a["result"]["elements"] if e["name"] == "Плита перекрытия 3")
    assert slab["mean"] < -0.005 and 0.025 < slab["max_abs"] < 0.08  # 4 cm sag (+noise), measured as negative
    wall = next(e for e in a["result"]["elements"] if e["ifc_type"] == "IfcWall")
    assert wall["p95_abs"] < 0.03

    asset = client.get(f"/api/assets/{a['result_asset_id']}", headers=h).json()
    assert asset["kind"] == "point_cloud" and asset["stats"]["analysis_id"] == a["id"]

    pdf = client.get(f"/api/analyses/{a['id']}/report.pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF" and len(pdf.content) > 20_000

    assert len(client.get(f"/api/projects/{pid}/analyses", headers=h).json()) == 1
    assert client.delete(f"/api/analyses/{a['id']}", headers=h).status_code == 204
    assert client.get(f"/api/assets/{a['result_asset_id']}", headers=h).status_code == 404


def test_icp_alignment_recovers_offset(client, scene):
    h, pid, bim, scan = scene
    client.patch(f"/api/assets/{scan}", headers=h, json={"offset_enu": [0.2, -0.12, 0.05]})
    r = client.post(f"/api/projects/{pid}/analyses/alignment", headers=h,
                    json={"cloud_asset_id": scan, "bim_asset_id": bim})
    a = client.get(f"/api/analyses/{r.json()['id']}", headers=h).json()
    assert a["status"] == "ready", a["error_message"]
    t = a["result"]["translation_enu"]
    assert t[0] == pytest.approx(-0.2, abs=0.02) and t[1] == pytest.approx(0.12, abs=0.02) and t[2] == pytest.approx(-0.05, abs=0.02)
    assert a["result"]["rmse_after"] < a["result"]["rmse_before"]
    assert a["result"]["warnings"] == []
    g = client.get(f"/api/assets/{scan}", headers=h).json()["georef"]
    assert len(g["alignment"]) == 16
    g = client.patch(f"/api/assets/{scan}", headers=h, json={"reset_alignment": True}).json()["georef"]
    assert "alignment" not in g


def test_deviation_rejects_wrong_kinds(client, scene):
    h, pid, bim, scan = scene
    r = client.post(f"/api/projects/{pid}/analyses/deviation", headers=h, json={"cloud_asset_id": bim, "bim_asset_id": scan})
    assert r.status_code == 400


def test_profile_section(client, scene):
    h, pid, bim, scan = scene
    c = client.get(f"/api/assets/{bim}", headers=h).json()["stats"]["center"]
    # East-west line through the building centre, ~50 m long.
    a = [c["longitude"] - 0.00036, c["latitude"]]
    b = [c["longitude"] + 0.00036, c["latitude"]]
    r = client.post(f"/api/projects/{pid}/profile", headers=h,
                    json={"a": a, "b": b, "bim_asset_id": bim, "cloud_asset_id": scan, "width": 0.5})
    assert r.status_code == 200, r.text
    p = r.json()
    assert 45 < p["length"] < 55
    assert len(p["bim"]) > 10 and len(p["scan"]) > 50
    zs = [s[1] for s in p["bim"]] + [s[3] for s in p["bim"]]
    assert max(zs) - min(zs) > 8  # three storeys cut


def test_as_built_ifc(client, scene, tmp_path):
    import ifcopenshell
    import ifcopenshell.util.element as eu

    h, pid, bim, scan = scene
    # ±2 cm design tolerance: the 4 cm sag of slab 3 (P95 ≈ 34 mm) exceeds it.
    a = client.post(f"/api/projects/{pid}/analyses/deviation", headers=h,
                    json={"cloud_asset_id": scan, "bim_asset_id": bim, "tolerances": [0.01, 0.02, 0.05]}).json()
    r = client.get(f"/api/analyses/{a['id']}/as-built.ifc", headers=h)
    assert r.status_code == 200 and "as-built" in r.headers["content-disposition"]
    path = tmp_path / "ab.ifc"
    path.write_bytes(r.content)
    model = ifcopenshell.open(str(path))
    psets = {el.Name: eu.get_psets(el).get("Twin_AsBuilt") for el in model.by_type("IfcElement")}
    slab3 = psets["Плита перекрытия 3"]
    assert slab3["Status"] == "Отклонение сверх допуска" and slab3["DeviationMean_mm"] < -5 and slab3["ScanPoints"] >= 20
    assert any(p and p["Status"] == "Соответствует проекту" for p in psets.values())
    # make_scan covers 3 storeys of make_building(3) incl. roof -> top-level elements may be missing; all carry a status.
    assert all(p and p["Status"] for p in psets.values())
    assert slab3["Tolerance_mm"] == 20.0


def test_as_built_ifc2x3():
    """IFC2X3 needs an owner history for new property sets."""
    import os
    import tempfile

    import ifcopenshell
    import ifcopenshell.guid
    import ifcopenshell.util.element as eu

    from app.twin.asbuilt import build_as_built

    m = ifcopenshell.file(schema="IFC2X3")
    oh = m.createIfcOwnerHistory(
        m.createIfcPersonAndOrganization(m.createIfcPerson(), m.createIfcOrganization(Name="X")),
        m.createIfcApplication(m.createIfcOrganization(Name="X"), "1", "x", "x"), None, "ADDED", None, None, None, 0)
    wall = m.createIfcWall(ifcopenshell.guid.new(), oh, "W")
    fd, src = tempfile.mkstemp(suffix=".ifc")
    os.close(fd)
    m.write(src)
    try:
        result = {"tolerances": [0.01, 0.02, 0.05], "cloud": {"name": "scan"},
                  "elements": [{"global_id": wall.GlobalId, "points": 100, "mean": 0.001, "p95_abs": 0.004, "max_abs": 0.006,
                                "out_of_tolerance": 0.0}]}
        data, counts = build_as_built(src, result, "2026-05-20")
    finally:
        os.unlink(src)
    fd, out = tempfile.mkstemp(suffix=".ifc")
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    f = ifcopenshell.open(out)  # keep the file alive while its instances are used
    w = f.by_type("IfcWall")[0]
    assert eu.get_psets(w)["Twin_AsBuilt"]["Status"] == "Соответствует проекту" and counts == {"Соответствует проекту": 1}
    os.unlink(out)


def test_executive_scheme(client, scene):
    import numpy as np

    from app.twin import exec_scheme

    h, pid, bim, scan = scene
    a = client.post(f"/api/projects/{pid}/analyses/deviation", headers=h,
                    json={"cloud_asset_id": scan, "bim_asset_id": bim}).json()
    r = client.get(f"/api/analyses/{a['id']}/executive-scheme.pdf", headers=h, params={"step": 3, "tolerance_mm": 10})
    assert r.status_code == 200 and r.content[:4] == b"%PDF" and len(r.content) > 5000

    # Core check on the same data: slab 3 sags 4 cm in the middle, slab 1 is flat.
    from app.models import BimElement
    from app.db import SessionLocal
    from app.models import SceneAsset
    from app.twin.analysis_jobs import load_mesh_world, load_points_world, local_frame, to_local
    import uuid

    db = SessionLocal()
    b, c = db.get(SceneAsset, uuid.UUID(bim)), db.get(SceneAsset, uuid.UUID(scan))
    mesh, tris_w = load_mesh_world(b)
    pts_w, _, _ = load_points_world(c)
    db.close()
    origin, axes = local_frame(pts_w)
    tris = to_local(tris_w.reshape(-1, 3), origin, axes).reshape(-1, 3, 3)
    pts = to_local(pts_w, origin, axes)
    els = [(i, g, mesh.names[i], None) for i, g in enumerate(mesh.global_ids) if mesh.names[i] in ("Плита перекрытия 1", "Плита перекрытия 3")]
    out = {s.name: s for s in exec_scheme.compute(tris, mesh.feature, els, pts, 3.0)}
    d1 = [(p.actual_z - p.design_z) * 1000 for p in out["Плита перекрытия 1"].points if p.actual_z is not None]
    d3 = [(p.actual_z - p.design_z) * 1000 for p in out["Плита перекрытия 3"].points if p.actual_z is not None]
    assert len(d1) >= 10 and len(d3) >= 10
    assert np.percentile(np.abs(d1), 90) < 10
    assert min(d3) < -25  # the sag
    assert len(out["Плита перекрытия 3"].outline) >= 4
