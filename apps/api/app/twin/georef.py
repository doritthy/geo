"""Georeferencing helpers: source CRS -> ECEF, local anchors, ENU frames.

Two placement modes are used throughout the twin pipeline (see
infra/db/twin.sql, `scene_assets.georef`):

* ``absolute`` -- source coordinates are in a known CRS; every vertex/point is
  transformed exactly to ECEF (EPSG:4978). No flat-earth approximation, so it
  stays correct for long linear infrastructure (roads, pipelines), where a
  tangent-plane frame would sag ~8 cm at 1 km and ~8 m at 10 km.
* ``anchor`` -- local model coordinates (metres, Z-up) with no CRS; the
  client places the tileset with longitude/latitude/height/heading/scale.

Heights: CRS Z values are usually orthometric (Балтийская система высот);
Cesium works with ellipsoidal heights. `height_offset` (m) is added before
the transform; with `vertical_datum` = egm96 / egm2008 the geoid undulation
at the model's location is computed from the PROJ grid and added to it
(one value per model — the undulation changes by millimetres across a site).
"""

from __future__ import annotations

import math
import os
from functools import lru_cache

import numpy as np
from pyproj import CRS, Geod, Transformer

_GEOD = Geod(ellps="WGS84")


class GeorefError(ValueError):
    pass


# Geoid models -> PROJ grid files (cdn.proj.org). The API image ships EGM96;
# EGM2008 (80 MB) is optional (Dockerfile build arg).
GEOID_GRIDS = {"egm96": "us_nga_egm96_15.tif", "egm2008": "us_nga_egm08_25.tif"}
_GEOID_LABELS = {"egm96": "EGM96 (нормальные высоты, ~1 м)", "egm2008": "EGM2008 (нормальные высоты, ~10 см)"}


def _grid_dirs() -> list[str]:
    from pyproj.datadir import get_data_dir

    dirs = [d for d in os.environ.get("PROJ_GRID_DIR", "/opt/proj-grids").split(os.pathsep) if d]
    return dirs + get_data_dir().split(os.pathsep)


def _grid_path(model: str) -> str | None:
    name = GEOID_GRIDS.get(model)
    for d in _grid_dirs() if name else []:
        path = os.path.join(d, name)
        if os.path.exists(path):
            return path
    return None


def available_geoids() -> list[dict]:
    return [{"value": m, "label": _GEOID_LABELS[m]} for m in GEOID_GRIDS if _grid_path(m)]


@lru_cache(maxsize=4)
def _geoid_transformer(path: str) -> Transformer:
    # vgridshift: z_out = z_in + multiplier * N; with z_in = 0 this yields N.
    return Transformer.from_pipeline(f"+proj=vgridshift +grids={path} +multiplier=1")


def geoid_undulation(lon: float, lat: float, model: str) -> float:
    path = _grid_path(model)
    if path is None:
        raise GeorefError(f"Модель геоида {model} не установлена на сервере (файл {GEOID_GRIDS.get(model)})")
    _, _, n = _geoid_transformer(path).transform(math.radians(lon), math.radians(lat), 0.0, radians=True)
    if not math.isfinite(n) or abs(n) > 200:
        raise GeorefError(f"Не удалось вычислить высоту геоида в точке {lat:.4f}, {lon:.4f}")
    return float(n)


def total_height_offset(options: dict, crs: CRS | None = None, xyz=None, lonlat: tuple[float, float] | None = None) -> float:
    """`height_offset` from the upload plus the geoid undulation when the
    source heights are normal (vertical_datum = egm96 / egm2008). The place
    is given as lon/lat or as a point `xyz` in `crs`."""
    base = float(options.get("height_offset") or 0.0)
    model = options.get("vertical_datum")
    if model not in GEOID_GRIDS:
        return base
    if lonlat is None:
        if crs is None or xyz is None:
            return base
        lon, lat = Transformer.from_crs(crs, 4326, always_xy=True).transform(float(xyz[0]), float(xyz[1]))
        lonlat = (lon, lat)
    return base + geoid_undulation(lonlat[0], lonlat[1], model)


def resolve_crs(value: str | int | None) -> CRS | None:
    """Accept 'EPSG:32642', '32642', 32642, a PROJ string (+proj=tmerc ...)
    or WKT -- local/МСК systems usually arrive as PROJ strings."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        text = f"EPSG:{text}"
    try:
        return CRS.from_user_input(text)
    except Exception as exc:  # noqa: BLE001
        raise GeorefError(f"Не удалось распознать систему координат: {value!r} ({exc})") from exc


@lru_cache(maxsize=32)
def _to_ecef(crs_wkt: str) -> Transformer:
    crs = CRS.from_wkt(crs_wkt)
    if not crs.is_geocentric and len(crs.axis_info) < 3:
        crs = crs.to_3d()
    return Transformer.from_crs(crs, CRS.from_epsg(4978), always_xy=True)


@lru_cache(maxsize=32)
def _to_lonlat(crs_wkt: str) -> Transformer:
    return Transformer.from_crs(CRS.from_wkt(crs_wkt), CRS.from_epsg(4326), always_xy=True)


_ECEF_TO_LLH = Transformer.from_crs(CRS.from_epsg(4978), CRS.from_epsg(4979), always_xy=True)
_LLH_TO_ECEF = Transformer.from_crs(CRS.from_epsg(4979), CRS.from_epsg(4978), always_xy=True)


def crs_to_ecef(points: np.ndarray, crs: CRS, height_offset: float = 0.0) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float64)
    x, y, z = _to_ecef(crs.to_wkt()).transform(pts[:, 0], pts[:, 1], pts[:, 2] + height_offset)
    out = np.column_stack([x, y, z])
    if not np.isfinite(out).all():
        raise GeorefError(
            "Координаты не преобразуются в выбранную СК (вне области действия?). Проверьте систему координат."
        )
    return out


def crs_to_lonlat(x: float, y: float, crs: CRS) -> tuple[float, float]:
    lon, lat = _to_lonlat(crs.to_wkt()).transform(x, y)
    return float(lon), float(lat)


def ecef_to_llh(points: np.ndarray) -> np.ndarray:
    pts = np.atleast_2d(np.asarray(points, dtype=np.float64))
    lon, lat, h = _ECEF_TO_LLH.transform(pts[:, 0], pts[:, 1], pts[:, 2])
    return np.column_stack([lon, lat, h])


def llh_to_ecef(lon: float, lat: float, h: float) -> np.ndarray:
    x, y, z = _LLH_TO_ECEF.transform(lon, lat, h)
    return np.array([x, y, z])


def enu_axes(lon_deg: float, lat_deg: float) -> np.ndarray:
    """Rows: east, north, up unit vectors in ECEF at the given location."""
    lon, lat = math.radians(lon_deg), math.radians(lat_deg)
    east = np.array([-math.sin(lon), math.cos(lon), 0.0])
    north = np.array([-math.sin(lat) * math.cos(lon), -math.sin(lat) * math.sin(lon), math.cos(lat)])
    up = np.array([math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)])
    return np.vstack([east, north, up])


def anchor_from_crs_point(crs: CRS, x: float, y: float, z: float, height_offset: float = 0.0) -> dict:
    """Anchor (lon/lat/height + heading + scale) equivalent to a local frame
    whose origin is (x, y, z) in `crs` and whose +Y is grid north.

    heading = geodesic azimuth of grid north (clockwise from true north, i.e.
    minus the meridian convergence); scale = ground/grid distance ratio. Used
    when a model is small enough that a tangent plane is exact to < 1 cm."""
    lon0, lat0 = crs_to_lonlat(x, y, crs)
    lon1, lat1 = crs_to_lonlat(x, y + 100.0, crs)
    az, _, dist = _GEOD.inv(lon0, lat0, lon1, lat1)
    return {
        "longitude": lon0,
        "latitude": lat0,
        "height": float(z + height_offset),
        "heading": float(az),
        "scale": float(dist / 100.0) if dist > 0 else 1.0,
    }


def llh_summary(ecef_center: np.ndarray) -> dict:
    lon, lat, h = ecef_to_llh(ecef_center)[0]
    return {"longitude": float(lon), "latitude": float(lat), "height": float(h)}


def dms_to_degrees(dms) -> float | None:
    """IFC compound plane angle (deg, min, sec[, millionths]) -> decimal degrees."""
    if not dms:
        return None
    parts = list(dms) + [0, 0, 0, 0]
    deg, minutes, sec, micro = (float(p) for p in parts[:4])
    sign = -1.0 if (deg < 0 or minutes < 0 or sec < 0 or micro < 0) else 1.0
    return sign * (abs(deg) + abs(minutes) / 60.0 + (abs(sec) + abs(micro) / 1e6) / 3600.0)


def anchor_matrix(g: dict) -> np.ndarray:
    """4x4 local model frame -> ECEF for an anchor placement (mirrors the
    client: ENU(lon, lat, h) · Rz(-heading) · scale)."""
    origin = llh_to_ecef(g.get("longitude", 0.0), g.get("latitude", 0.0), g.get("height", 0.0))
    enu = enu_axes(g.get("longitude", 0.0), g.get("latitude", 0.0))  # rows e, n, u
    m = np.eye(4)
    m[:3, :3] = enu.T
    m[:3, 3] = origin
    a = -math.radians(g.get("heading", 0.0) or 0.0)
    rot = np.eye(4)
    rot[:2, :2] = [[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]]
    scale = np.diag([g.get("scale", 1.0) or 1.0] * 3 + [1.0])
    return m @ rot @ scale


def asset_world_matrix(georef: dict, center_llh: dict | None = None) -> np.ndarray:
    """Tileset frame -> ECEF, exactly as the viewer places the tileset:
    alignment (ICP) · (anchor placement | ENU fine offset)."""
    if georef.get("mode") == "anchor":
        base = anchor_matrix(georef)
    else:
        base = np.eye(4)
        off = georef.get("offset_enu")
        if off and center_llh:
            base[:3, 3] = enu_axes(center_llh["longitude"], center_llh["latitude"]).T @ np.asarray(off, dtype=np.float64)
    align = georef.get("alignment")
    if align:
        base = np.asarray(align, dtype=np.float64).reshape(4, 4).T @ base
    return base


def apply_matrix(m: np.ndarray, pts: np.ndarray) -> np.ndarray:
    return pts @ m[:3, :3].T + m[:3, 3]
