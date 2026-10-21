"""End-to-end tests for the construction digital twin: upload -> background
conversion -> 3D Tiles served through the API, BIM element index, version
comparison, georeferencing, annotations, documents and tenant isolation.
Runs against real Postgres + S3 (see conftest.py) and real IfcOpenShell /
laspy / trimesh conversions."""

import json
import struct

import pytest

from tests.twin_fixtures import make_ifc, make_las, make_obj


def _headers(client, email="bim@example.com", org="Стройка"):
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": "supersecret123", "full_name": "BIM", "organization_name": org},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _project(client, headers, **extra):
    resp = client.post("/api/projects", json={"name": "ЖК Тест", **extra}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _upload(client, headers, project_id, filename, data, category, options=None):
    resp = client.post(
        f"/api/projects/{project_id}/files",
        data={"category": category, **({"options": json.dumps(options)} if options else {})},
        files={"file": (filename, data)},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    file_id = resp.json()["id"]
    record = client.get(f"/api/files/{file_id}", headers=headers).json()
    assert record["status"] == "ready", record.get("error_message")
    return record["metadata"]["asset_id"]


def _tileset(client, headers, asset):
    resp = client.get(asset["tileset_url"], headers=headers)
    assert resp.status_code == 200
    return resp.json()


def _first_content(node):
    if "content" in node:
        return node["content"]["uri"]
    for child in node.get("children", []):
        uri = _first_content(child)
        if uri:
            return uri
    return None


def test_ifc_upload_tiles_elements_and_compare(client):
    h = _headers(client)
    pid = _project(client, h)

    asset_id = _upload(client, h, pid, "model_v1.ifc", make_ifc(), "bim", {"longitude": 71.43, "latitude": 51.13})
    asset = client.get(f"/api/assets/{asset_id}", headers=h).json()
    assert asset["kind"] == "bim"
    assert asset["georef"]["mode"] == "anchor"
    assert asset["georef"]["longitude"] == pytest.approx(71.43)
    assert asset["stats"]["element_count"] == 3
    assert asset["stats"]["ifc_types"] == {"IfcWall": 3}

    tileset = _tileset(client, h, asset)
    assert tileset["asset"]["version"] == "1.0"
    uri = _first_content(tileset["root"])
    tile = client.get(f"/api/assets/{asset_id}/tiles/{uri}", headers=h)
    assert tile.status_code == 200
    magic, version, length, ft_json_len, _, bt_json_len, _ = struct.unpack("<4sIIIIII", tile.content[:28])
    assert magic == b"b3dm" and version == 1 and length == len(tile.content)
    batch_table = json.loads(tile.content[28 + ft_json_len : 28 + ft_json_len + bt_json_len])
    assert len(batch_table["GlobalId"]) == 3
    assert set(batch_table["IfcType"]) == {"IfcWall"}

    # Path traversal is not served
    assert client.get(f"/api/assets/{asset_id}/tiles/%2E%2E%2F%2E%2E%2Fsecret", headers=h).status_code == 404

    page = client.get(f"/api/assets/{asset_id}/elements", params={"q": "Стена"}, headers=h).json()
    assert page["total"] == 3
    gid = page["items"][0]["global_id"]
    detail = client.get(f"/api/assets/{asset_id}/elements/{gid}", headers=h).json()
    assert detail["storey"] == "Этаж 1"
    assert detail["properties"]["psets"]["Pset_WallCommon"]["FireRating"] == "REI60"

    # v2: wall 2 moved, wall 3 removed, wall 4 added
    v2 = make_ifc([("Стена 1", 0.0), ("Стена 2", 7.0), ("Стена 4", 18.0)])
    v2_id = _upload(client, h, pid, "model_v2.ifc", v2, "bim", {"replaces_asset_id": asset_id})
    v2_asset = client.get(f"/api/assets/{v2_id}", headers=h).json()
    assert v2_asset["version"] == 2
    assert v2_asset["version_group"] == asset["version_group"]
    versions = client.get(f"/api/assets/{v2_id}/versions", headers=h).json()
    assert [v["version"] for v in versions] == [1, 2]

    diff = client.get(f"/api/assets/{asset_id}/compare", params={"other": v2_id}, headers=h).json()
    assert diff["counts"] == {
        "added": 1, "removed": 1, "modified_geometry": 1, "modified_properties": 0, "unchanged": 1,
    }
    assert diff["added"][0]["name"] == "Стена 4"
    assert diff["removed"][0]["name"] == "Стена 3"
    assert diff["modified_geometry"][0]["name"] == "Стена 2"


def test_ifc_map_conversion_is_absolute(client):
    h = _headers(client)
    pid = _project(client, h)
    data = make_ifc(map_conversion={"Eastings": 500000.0, "Northings": 5650000.0, "OrthogonalHeight": 350.0})
    asset_id = _upload(client, h, pid, "geo.ifc", data, "bim")
    asset = client.get(f"/api/assets/{asset_id}", headers=h).json()
    assert asset["georef"]["mode"] == "absolute"
    assert asset["georef"]["source"] == "IfcMapConversion"
    center = asset["stats"]["center"]
    # UTM 42N, E=500000 is the central meridian (69°E); N=5650000 is ~51°N.
    assert center["longitude"] == pytest.approx(69.0, abs=0.01)
    assert center["latitude"] == pytest.approx(51.0, abs=0.1)
    assert center["height"] == pytest.approx(351.5, abs=1.0)


def test_ifc_site_reference_is_used_as_anchor(client):
    h = _headers(client)
    pid = _project(client, h)
    asset_id = _upload(client, h, pid, "site.ifc", make_ifc(site_latlon=(51.5, 71.5)), "bim")
    georef = client.get(f"/api/assets/{asset_id}", headers=h).json()["georef"]
    assert georef["mode"] == "anchor" and georef["source"] == "IfcSite"
    assert georef["latitude"] == pytest.approx(51.5, abs=0.01)
    assert georef["longitude"] == pytest.approx(71.5, abs=0.01)


def test_point_cloud_las_absolute_octree(client):
    h = _headers(client)
    pid = _project(client, h)
    asset_id = _upload(client, h, pid, "scan.las", make_las(), "point_cloud", {"captured_at": "2026-05-20"})
    asset = client.get(f"/api/assets/{asset_id}", headers=h).json()
    assert asset["kind"] == "point_cloud"
    assert asset["captured_at"] == "2026-05-20"
    assert asset["georef"]["mode"] == "absolute"  # CRS read from the LAS header
    assert asset["stats"]["point_count"] == 50_000
    assert asset["stats"]["center"]["latitude"] == pytest.approx(51.0, abs=0.1)

    tileset = _tileset(client, h, asset)
    uri = _first_content(tileset["root"])
    tile = client.get(f"/api/assets/{asset_id}/tiles/{uri}", headers=h)
    assert tile.content[:4] == b"pnts"


def test_point_cloud_without_crs_is_anchor(client):
    h = _headers(client)
    pid = _project(client, h)
    asset_id = _upload(client, h, pid, "local.laz", make_las(epsg=None), "point_cloud")
    asset = client.get(f"/api/assets/{asset_id}", headers=h).json()
    assert asset["georef"]["mode"] == "anchor"
    assert asset["georef"]["source"] == "unplaced"


def test_mesh_upload_and_manual_placement(client):
    h = _headers(client)
    pid = _project(client, h)
    asset_id = _upload(client, h, pid, "facade.obj", make_obj(), "reality_mesh")
    asset = client.get(f"/api/assets/{asset_id}", headers=h).json()
    assert asset["kind"] == "mesh"
    assert asset["stats"]["triangle_count"] == 12
    tile_uri = _first_content(_tileset(client, h, asset)["root"])
    assert client.get(f"/api/assets/{asset_id}/tiles/{tile_uri}", headers=h).content[:4] == b"b3dm"

    resp = client.patch(
        f"/api/assets/{asset_id}",
        json={"longitude": 71.4, "latitude": 51.1, "height": 347.0, "heading": 15.0, "name": "Фасад"},
        headers=h,
    )
    assert resp.status_code == 200, resp.text
    g = resp.json()["georef"]
    assert (g["longitude"], g["latitude"], g["heading"], g["source"]) == (71.4, 51.1, 15.0, "manual")
    assert resp.json()["name"] == "Фасад"

    # Absolute (CRS-placed) assets cannot be re-anchored, only offset.
    las_id = _upload(client, h, pid, "scan.las", make_las(), "point_cloud")
    assert client.patch(f"/api/assets/{las_id}", json={"longitude": 1.0}, headers=h).status_code == 400
    resp = client.patch(f"/api/assets/{las_id}", json={"offset_enu": [0.1, -0.2, 0.05]}, headers=h)
    assert resp.json()["georef"]["offset_enu"] == [0.1, -0.2, 0.05]


def test_unsupported_bim_format_reports_error(client):
    h = _headers(client)
    pid = _project(client, h)
    resp = client.post(
        f"/api/projects/{pid}/files", data={"category": "bim"}, files={"file": ("house.rvt", b"RVT")}, headers=h
    )
    record = client.get(f"/api/files/{resp.json()['id']}", headers=h).json()
    assert record["status"] == "error"
    assert "APS" in record["error_message"]


def test_annotations_bound_to_element(client):
    h = _headers(client)
    pid = _project(client, h)
    asset_id = _upload(client, h, pid, "m.ifc", make_ifc(), "bim")
    gid = client.get(f"/api/assets/{asset_id}/elements", headers=h).json()["items"][0]["global_id"]

    resp = client.post(
        f"/api/projects/{pid}/annotations",
        json={"longitude": 71.4, "latitude": 51.1, "height": 350.0, "title": "Трещина", "body": "Проверить",
              "asset_id": asset_id, "element_global_id": gid},
        headers=h,
    )
    assert resp.status_code == 201, resp.text
    note = resp.json()
    assert note["author_name"] == "BIM"

    detail = client.get(f"/api/assets/{asset_id}/elements/{gid}", headers=h).json()
    assert [a["title"] for a in detail["annotations"]] == ["Трещина"]

    resp = client.patch(f"/api/annotations/{note['id']}", json={"title": "Трещина в стене"}, headers=h)
    assert resp.json()["title"] == "Трещина в стене"
    assert len(client.get(f"/api/projects/{pid}/annotations", headers=h).json()) == 1
    assert client.delete(f"/api/annotations/{note['id']}", headers=h).status_code == 204
    assert client.get(f"/api/projects/{pid}/annotations", headers=h).json() == []


def test_documents_versions_links_search(client):
    h = _headers(client)
    pid = _project(client, h)
    asset_id = _upload(client, h, pid, "m.ifc", make_ifc(), "bim")
    gid = client.get(f"/api/assets/{asset_id}/elements", headers=h).json()["items"][0]["global_id"]

    resp = client.post(
        f"/api/projects/{pid}/documents",
        data={"title": "Раздел КЖ", "doc_type": "rd", "code": "КЖ-01", "asset_id": asset_id, "element_global_id": gid},
        files={"file": ("kzh.pdf", b"%PDF-1.4 v1")},
        headers=h,
    )
    assert resp.status_code == 201, resp.text
    doc = resp.json()
    assert doc["latest_version"]["version"] == 1
    assert doc["links"][0]["element_global_id"] == gid

    resp = client.post(
        f"/api/documents/{doc['id']}/versions", data={"comment": "Изм. 1"},
        files={"file": ("kzh_rev1.pdf", b"%PDF-1.4 v2")}, headers=h,
    )
    assert [v["version"] for v in resp.json()["versions"]] == [1, 2]
    v2 = resp.json()["versions"][1]
    dl = client.get(f"/api/document-versions/{v2['id']}/download", headers=h)
    assert dl.status_code == 200 and dl.content == b"%PDF-1.4 v2"
    assert "kzh_rev1.pdf" in dl.headers["content-disposition"]

    assert len(client.get(f"/api/projects/{pid}/documents", params={"q": "кж"}, headers=h).json()) == 1
    assert len(client.get(f"/api/projects/{pid}/documents", params={"q": "rev1"}, headers=h).json()) == 1
    assert client.get(f"/api/projects/{pid}/documents", params={"doc_type": "pd"}, headers=h).json() == []
    by_element = client.get(f"/api/projects/{pid}/documents", params={"global_id": gid}, headers=h).json()
    assert [d["code"] for d in by_element] == ["КЖ-01"]

    detail = client.get(f"/api/assets/{asset_id}/elements/{gid}", headers=h).json()
    assert [d["title"] for d in detail["documents"]] == ["Раздел КЖ"]


def test_twin_tenant_isolation(client):
    owner = _headers(client)
    pid = _project(client, owner)
    asset_id = _upload(client, owner, pid, "m.ifc", make_ifc(), "bim")
    outsider = _headers(client, email="other@example.com", org="Другая компания")
    assert client.get(f"/api/assets/{asset_id}", headers=outsider).status_code == 404
    assert client.get(f"/api/assets/{asset_id}/tiles/tileset.json", headers=outsider).status_code == 404
    assert client.get(f"/api/assets/{asset_id}/elements", headers=outsider).status_code == 404
    assert client.get(f"/api/projects/{pid}/annotations", headers=outsider).status_code == 404
    assert client.get(f"/api/assets/{asset_id}/tiles/tileset.json").status_code == 401


def test_project_crs_and_resolve(client):
    h = _headers(client)
    resp = client.post("/api/projects", json={"name": "Дорога", "crs": "EPSG:28413"}, headers=h)
    assert resp.status_code == 201 and resp.json()["crs"] == "EPSG:28413"
    pid = resp.json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={"crs": "не СК"}, headers=h).status_code == 400
    resp = client.patch(f"/api/projects/{pid}", json={"crs": "+proj=tmerc +lat_0=0 +lon_0=71 +k=1 +x_0=300000 +y_0=-5000000 +ellps=krass +units=m"}, headers=h)
    assert resp.status_code == 200

    info = client.get("/api/crs/resolve", params={"value": "32642"}, headers=h).json()
    assert info["code"] == "EPSG:32642" and info["is_projected"] and "+proj=utm" in info["proj4"]
    presets = client.get("/api/crs/presets", headers=h).json()
    assert any(p["value"] == "EPSG:28413" for p in presets)


def _upload_vector(client, headers, project_id, filename, data, options=None):
    resp = client.post(
        f"/api/projects/{project_id}/files",
        data={"category": "map_vector", **({"options": json.dumps(options)} if options else {})},
        files={"file": (filename, data)},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    record = client.get(f"/api/files/{resp.json()['id']}", headers=headers).json()
    assert record["status"] == "ready", record.get("error_message")
    return client.get(f"/api/map-layers/{record['metadata']['map_layer_id']}", headers=headers).json()


def test_vector_geojson_kml_dxf(client):
    h = _headers(client)
    pid = _project(client, h, crs="EPSG:32642")

    gj = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::32642"}},
        "features": [{"type": "Feature", "properties": {"Кадастр": "01-001"},
                      "geometry": {"type": "Point", "coordinates": [500000, 5650000]}}],
    }
    layer = _upload_vector(client, h, pid, "parcels.geojson", json.dumps(gj).encode())
    lon, lat = layer["geojson"]["features"][0]["geometry"]["coordinates"][:2]
    assert lon == pytest.approx(69.0, abs=1e-6) and lat == pytest.approx(51.0, abs=0.1)
    assert layer["geojson"]["features"][0]["properties"]["Кадастр"] == "01-001"

    kml = """<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>
      <Placemark><name>Ось дороги</name><LineString><coordinates>71.40,51.10,0 71.45,51.12,0</coordinates></LineString></Placemark>
    </Document></kml>""".encode()
    layer = _upload_vector(client, h, pid, "road.kml", kml)
    assert layer["geojson"]["features"][0]["geometry"]["type"] == "LineString"

    import io

    import ezdxf

    doc = ezdxf.new()
    doc.modelspace().add_line((500000, 5650000), (500100, 5650050), dxfattribs={"layer": "Сети"})
    buf = io.StringIO()
    doc.write(buf)
    # DXF has no CRS -> project CRS (UTM 42N) is applied
    layer = _upload_vector(client, h, pid, "networks.dxf", buf.getvalue().encode())
    feature = layer["geojson"]["features"][0]
    assert feature["properties"]["Layer"] == "Сети"
    assert feature["geometry"]["coordinates"][0][0] == pytest.approx(69.0, abs=1e-6)
