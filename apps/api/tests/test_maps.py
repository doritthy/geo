"""Map layer coverage: shapefile -> vector map_layer, GeoTIFF -> raster
map_layer. Skips gracefully (rather than failing the whole suite) if the
optional GDAL-backed geospatial deps (rasterio/geopandas) aren't usable in
this environment -- see docs/LIMITATIONS.md and the task brief.
"""

import pytest

geopandas = pytest.importorskip("geopandas", reason="geopandas (GDAL) not available in this environment")
rasterio = pytest.importorskip("rasterio", reason="rasterio (GDAL) not available in this environment")


def _auth_headers(client, email="maps@example.com", org="Maps Org") -> dict:
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": "supersecret123", "full_name": "T", "organization_name": org},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_shapefile_vector_layer_end_to_end(client, fixtures_dir):
    headers = _auth_headers(client)
    project = client.post("/api/projects", json={"name": "Map Field"}, headers=headers).json()

    zip_bytes = (fixtures_dir / "sample_shp.zip").read_bytes()
    resp = client.post(
        f"/api/projects/{project['id']}/files",
        headers=headers,
        data={"category": "map_vector"},
        files={"file": ("sample_shp.zip", zip_bytes, "application/zip")},
    )
    assert resp.status_code == 201, resp.text
    file_id = resp.json()["id"]

    resp = client.get(f"/api/files/{file_id}", headers=headers)
    file_record = resp.json()
    assert file_record["status"] == "ready", file_record.get("error_message")
    layer_id = file_record["metadata"]["map_layer_id"]

    resp = client.get(f"/api/projects/{project['id']}/map-layers", headers=headers)
    assert resp.status_code == 200
    summaries = resp.json()
    assert len(summaries) == 1
    assert summaries[0]["layer_kind"] == "vector"

    resp = client.get(f"/api/map-layers/{layer_id}", headers=headers)
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["geojson"]["type"] == "FeatureCollection"
    assert len(detail["geojson"]["features"]) == 2
    # Reprojected to WGS84 -- longitude/latitude-range coordinates, not UTM meters.
    lon, lat = detail["geojson"]["features"][0]["geometry"]["coordinates"]
    assert -180 <= lon <= 180
    assert -90 <= lat <= 90


def test_geotiff_map_raster_end_to_end(client, fixtures_dir):
    headers = _auth_headers(client, email="raster@example.com", org="Raster Org")
    project = client.post("/api/projects", json={"name": "Raster Field"}, headers=headers).json()

    tif_bytes = (fixtures_dir / "sample.tif").read_bytes()
    resp = client.post(
        f"/api/projects/{project['id']}/files",
        headers=headers,
        data={"category": "map_raster", "crs_epsg": "32639"},
        files={"file": ("sample.tif", tif_bytes, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    file_id = resp.json()["id"]

    resp = client.get(f"/api/files/{file_id}", headers=headers)
    file_record = resp.json()
    assert file_record["status"] == "ready", file_record.get("error_message")
    layer_id = file_record["metadata"]["map_layer_id"]

    resp = client.get(f"/api/map-layers/{layer_id}", headers=headers)
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["layer_kind"] == "raster"
    assert detail["image_url"].startswith("http")
    assert detail["bounds_geojson"]["type"] == "Polygon"
