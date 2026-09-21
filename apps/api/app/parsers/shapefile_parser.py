"""Shapefile parsing via `geopandas` (GDAL/OGR under the hood).

We accept a zip containing the full sidecar set (.shp/.shx/.dbf/.prj -- the
robust path, and what we document/recommend) or a single bare .shp. For the
bare-.shp case we set `SHAPE_RESTORE_SHX=YES` so GDAL will reconstruct a
missing .shx, but a missing .dbf still means attribute-less features -- this
is the documented tradeoff mentioned in the parser's module docstring in
the task brief ("document your choice").
"""

import json
import os
import tempfile
import zipfile
from dataclasses import dataclass

import geopandas


@dataclass
class ParsedVectorLayer:
    geojson: dict
    bounds_geojson: dict
    crs_epsg: int


def _is_zip(raw: bytes) -> bool:
    return raw[:4] == b"PK\x03\x04"


def parse_shapefile(raw: bytes, filename: str) -> ParsedVectorLayer:
    os.environ.setdefault("SHAPE_RESTORE_SHX", "YES")

    with tempfile.TemporaryDirectory() as tmpdir:
        if _is_zip(raw) or filename.lower().endswith(".zip"):
            zip_path = os.path.join(tmpdir, "upload.zip")
            with open(zip_path, "wb") as f:
                f.write(raw)
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmpdir)
            shp_files = [f for f in os.listdir(tmpdir) if f.lower().endswith(".shp")]
            if not shp_files:
                raise ValueError("Zip file does not contain a .shp")
            shp_path = os.path.join(tmpdir, shp_files[0])
        else:
            shp_path = os.path.join(tmpdir, "upload.shp")
            with open(shp_path, "wb") as f:
                f.write(raw)

        gdf = geopandas.read_file(shp_path)

    if gdf.crs is not None:
        gdf = gdf.to_crs(epsg=4326)

    geojson = json.loads(gdf.to_json())

    if len(gdf) and not gdf.total_bounds is None and gdf.total_bounds.size == 4 and not any(
        v != v for v in gdf.total_bounds
    ):
        minx, miny, maxx, maxy = gdf.total_bounds
        bounds_geojson = {
            "type": "Polygon",
            "coordinates": [[[minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny]]],
        }
    else:
        bounds_geojson = {"type": "Polygon", "coordinates": [[[0, 0], [0, 0], [0, 0], [0, 0], [0, 0]]]}

    return ParsedVectorLayer(geojson=geojson, bounds_geojson=bounds_geojson, crs_epsg=4326)
