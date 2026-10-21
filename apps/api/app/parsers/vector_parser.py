"""GeoJSON / KML / KMZ / DXF / GeoPackage -> WGS84 GeoJSON map layer, via
GDAL/OGR (geopandas + pyogrio).

DXF carries no CRS, so the CRS chosen at upload (or the project CRS) is
applied; without one, coordinates are accepted only if they already look
like longitude/latitude.
"""

import json
import os
import tempfile
import zipfile

import geopandas
import numpy as np

from app.parsers.shapefile_parser import ParsedVectorLayer
from app.twin.georef import resolve_crs

VECTOR_FORMATS = ("geojson", "kml", "kmz", "dxf", "gpkg")


def _read_all_layers(path: str, fmt: str) -> geopandas.GeoDataFrame:
    import pyogrio

    layers = [name for name, _ in pyogrio.list_layers(path)] if fmt in ("kml", "kmz", "gpkg") else [None]
    frames = []
    for layer in layers:
        gdf = geopandas.read_file(path, layer=layer) if layer else geopandas.read_file(path)
        if len(gdf):
            if layer:
                gdf["layer"] = layer
            frames.append(gdf)
    if not frames:
        raise ValueError("Файл не содержит объектов")
    crs = frames[0].crs
    return geopandas.GeoDataFrame(
        geopandas.pd.concat(frames, ignore_index=True), geometry="geometry", crs=crs
    )


def _dxf_encoding(raw: bytes) -> str | None:
    """AutoCAD R2007+ (AC1021+) DXF is always UTF-8 regardless of $DWGCODEPAGE;
    older files use the code page GDAL derives from the header."""
    head = raw[:8192].decode("latin-1", errors="ignore")
    idx = head.find("$ACADVER")
    if idx < 0:
        return None
    tokens = head[idx:].split()
    version = tokens[2] if len(tokens) > 2 else ""
    return "UTF-8" if version.startswith("AC") and version[2:].isdigit() and int(version[2:]) >= 1021 else None


def parse_vector(raw: bytes, filename: str, fmt: str, crs_hint: str | int | None = None) -> ParsedVectorLayer:
    try:
        return _parse_vector(raw, fmt, crs_hint)
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 -- OGR errors are opaque; name the format
        raise ValueError(f"{fmt.upper()}: не удалось прочитать файл ({exc})") from exc


def _parse_vector(raw: bytes, fmt: str, crs_hint: str | int | None) -> ParsedVectorLayer:
    if fmt == "dxf":
        encoding = _dxf_encoding(raw)
        if encoding:
            os.environ["DXF_ENCODING"] = encoding
        else:
            os.environ.pop("DXF_ENCODING", None)
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, f"upload.{fmt}")
        with open(path, "wb") as fh:
            fh.write(raw)
        if fmt == "kmz":
            with zipfile.ZipFile(path) as zf:
                kml = [n for n in zf.namelist() if n.lower().endswith(".kml")]
                if not kml:
                    raise ValueError("KMZ не содержит KML")
                zf.extract(kml[0], tmpdir)
                path, fmt = os.path.join(tmpdir, kml[0]), "kml"
        gdf = _read_all_layers(path, fmt)

    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
    if len(gdf) == 0:
        raise ValueError("Файл не содержит геометрии")

    hint = resolve_crs(crs_hint) if crs_hint else None
    if gdf.crs is None or (fmt == "dxf" and hint is not None):
        if hint is not None:
            gdf = gdf.set_crs(hint, allow_override=True)
        else:
            minx, miny, maxx, maxy = gdf.total_bounds
            if not (-180 <= minx <= 180 and -180 <= maxx <= 180 and -90 <= miny <= 90 and -90 <= maxy <= 90):
                raise ValueError(
                    "У файла нет системы координат. Укажите СК при загрузке или задайте СК проекта."
                )
            gdf = gdf.set_crs(4326)
    gdf = gdf.to_crs(4326)

    # DXF drops a lot of CAD-only columns; keep attribute tables readable.
    drop = [c for c in ("SubClasses", "Linetype", "EntityHandle") if c in gdf.columns]
    gdf = gdf.drop(columns=drop)
    for col in gdf.columns:
        if col != "geometry" and gdf[col].dtype == object:
            gdf[col] = gdf[col].astype(str).replace({"None": None, "nan": None})

    geojson = json.loads(gdf.to_json(na="null"))
    minx, miny, maxx, maxy = (float(v) for v in gdf.total_bounds)
    if not np.isfinite([minx, miny, maxx, maxy]).all():
        raise ValueError("Не удалось определить границы слоя")
    bounds = {"type": "Polygon", "coordinates": [[[minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny]]]}
    return ParsedVectorLayer(geojson=geojson, bounds_geojson=bounds, crs_epsg=4326)
