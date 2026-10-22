"""GeoTIFF / orthophoto -> Web Mercator XYZ tile pyramid (256 px PNG).

The deepest level matches the source resolution; each tile is warped
straight from the file on disk (GDAL reads only the needed window), so
rasters far larger than memory work. Lower levels are built by
down-sampling four children. Fully transparent tiles are not written.

Colours: 8-bit RGB(A) sources keep their values (orthophotos must not be
re-stretched); other sources get a 2–98 percentile stretch from an overview.
"""

from __future__ import annotations

import io
import math
import os

import numpy as np
import rasterio
from PIL import Image
from rasterio.crs import CRS
from affine import Affine
from rasterio.vrt import WarpedVRT
from rasterio.warp import Resampling, transform_bounds
from rasterio.windows import Window

from app.progress import report

TILE = 256
HALF = 20037508.342789244  # Web Mercator half-extent, m
MAX_ZOOM = 22
WEB_MERCATOR = CRS.from_epsg(3857)


def tile_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    size = 2 * HALF / 2**z
    return -HALF + x * size, HALF - (y + 1) * size, -HALF + (x + 1) * size, HALF - y * size


def _tile_range(bounds_m: tuple[float, float, float, float], z: int) -> tuple[int, int, int, int]:
    size = 2 * HALF / 2**z
    minx, miny, maxx, maxy = bounds_m
    n = 2**z - 1
    x0 = max(0, int(math.floor((minx + HALF) / size)))
    x1 = min(n, int(math.floor((maxx + HALF) / size - 1e-9)))
    y0 = max(0, int(math.floor((HALF - maxy) / size)))
    y1 = min(n, int(math.floor((HALF - miny) / size - 1e-9)))
    return x0, x1, y0, y1


def _stretch(src, bands: list[int]) -> list[tuple[float, float]] | None:
    if src.dtypes[0] == "uint8":
        return None
    scale = max(1, max(src.width, src.height) // 1024)
    out = []
    for b in bands:
        arr = src.read(b, out_shape=(max(1, src.height // scale), max(1, src.width // scale)), masked=True)
        vals = arr.compressed().astype(np.float64)
        vals = vals[np.isfinite(vals)]
        lo, hi = (np.percentile(vals, [2, 98]) if vals.size else (0.0, 1.0))
        out.append((float(lo), float(hi) if hi > lo else float(lo) + 1.0))
    return out


def build_pyramid(path: str, out_dir: str, crs_hint: CRS | None = None, max_tiles: int = 200_000) -> dict:
    """Writes `{z}/{x}/{y}.png` under out_dir and returns tiling metadata."""
    with rasterio.open(path) as src:
        src_crs = src.crs or crs_hint or CRS.from_epsg(4326)
        rgb = src.count >= 3
        bands = [1, 2, 3] if rgb else [1]
        alpha_band = 4 if src.count >= 4 and src.colorinterp[3].name == "alpha" else None
        stretch = _stretch(src, bands)

        bounds_m = transform_bounds(src_crs, WEB_MERCATOR, *src.bounds, densify_pts=21)
        west, south, east, north = transform_bounds(src_crs, CRS.from_epsg(4326), *src.bounds, densify_pts=21)
        # Source pixel size in metres at the raster's latitude -> deepest level.
        px_m = (bounds_m[2] - bounds_m[0]) / src.width * math.cos(math.radians((south + north) / 2))
        max_z = int(min(MAX_ZOOM, max(0, math.ceil(math.log2(2 * HALF / (TILE * max(px_m, 1e-3)))))))
        # Shallowest level: where the raster spans roughly one tile.
        span = max(bounds_m[2] - bounds_m[0], bounds_m[3] - bounds_m[1])
        min_z = int(max(0, min(max_z, math.floor(math.log2(2 * HALF / max(span, 1e-3))))))
        while True:
            x0, x1, y0, y1 = _tile_range(bounds_m, max_z)
            if (x1 - x0 + 1) * (y1 - y0 + 1) <= max_tiles or max_z <= min_z:
                break
            max_z -= 1

        keys: set[tuple[int, int]] = set()
        x0, x1, y0, y1 = _tile_range(bounds_m, max_z)
        nx, ny = x1 - x0 + 1, y1 - y0 + 1
        left, _, _, top = tile_bounds(max_z, x0, y0)
        res = 2 * HALF / 2**max_z / TILE
        # One warped view aligned to the tile grid: every tile is an exact
        # window, and GDAL's block cache serves neighbouring tiles.
        with WarpedVRT(src, crs=WEB_MERCATOR, transform=Affine(res, 0, left, 0, -res, top),
                       width=nx * TILE, height=ny * TILE, resampling=Resampling.bilinear,
                       src_nodata=src.nodata, nodata=src.nodata, add_alpha=alpha_band is None) as vrt:
            alpha_idx = alpha_band if alpha_band else vrt.count
            total, done = nx * ny, 0
            for ty in range(ny):
                for tx in range(nx):
                    done += 1
                    report("Тайлы растра", done / total * 0.8)
                    win = Window(tx * TILE, ty * TILE, TILE, TILE)
                    alpha = vrt.read(alpha_idx, window=win)
                    if not alpha.any():
                        continue
                    data = vrt.read(bands, window=win).astype(np.float32)
                    valid = alpha > 0
                    if src.nodata is not None:
                        valid &= ~(data == src.nodata).all(axis=0)
                    if not valid.any():
                        continue
                    if stretch:
                        for i, (lo, hi) in enumerate(stretch):
                            data[i] = (data[i] - lo) / (hi - lo) * 255.0
                    img8 = np.clip(np.nan_to_num(data), 0, 255).astype(np.uint8)
                    if not rgb:
                        img8 = np.repeat(img8, 3, axis=0)
                    rgba = np.dstack([img8.transpose(1, 2, 0), (valid * 255).astype(np.uint8)])
                    _save(out_dir, max_z, x0 + tx, y0 + ty, Image.fromarray(rgba, "RGBA"))
                    keys.add((x0 + tx, y0 + ty))

    count = len(keys)
    # Overviews: each parent from its (at most four) children already on disk.
    for z in range(max_z - 1, min_z - 1, -1):
        report("Обзорные уровни растра", 0.8 + 0.2 * (max_z - z) / max(max_z - min_z, 1))
        parents: dict[tuple[int, int], list[tuple[int, int]]] = {}
        for x, y in keys:
            parents.setdefault((x // 2, y // 2), []).append((x, y))
        for (px, py), children in parents.items():
            canvas = Image.new("RGBA", (2 * TILE, 2 * TILE), (0, 0, 0, 0))
            for x, y in children:
                with Image.open(os.path.join(out_dir, str(z + 1), str(x), f"{y}.png")) as child:
                    canvas.paste(child, ((x % 2) * TILE, (y % 2) * TILE))
            _save(out_dir, z, px, py, canvas.resize((TILE, TILE), Image.Resampling.LANCZOS))
        keys = set(parents)
        count += len(keys)
    return {
        "format": "png", "tile_size": TILE, "min_zoom": min_z, "max_zoom": max_z, "tile_count": count,
        "bounds": [west, south, east, north],
    }


def _save(out_dir: str, z: int, x: int, y: int, im: Image.Image) -> None:
    d = os.path.join(out_dir, str(z), str(x))
    os.makedirs(d, exist_ok=True)
    im.save(os.path.join(d, f"{y}.png"))


def transparent_tile() -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0)).save(buf, "PNG")
    return buf.getvalue()
