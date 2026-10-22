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
