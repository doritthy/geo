"""GeoTIFF parsing via `rasterio`.

Two uses per docs/API_CONTRACT.md:
  - `category=surface`: read band 1 as elevation/structural-surface heights
    (kept in the source CRS -- surfaces carry their own `crs_epsg`).
  - `category=map_raster`: reproject to EPSG:4326 and re-encode as a PNG for
    2D map display (docs/LIMITATIONS.md: single PNG, not an XYZ tile
    pyramid; large rasters are downsampled to `max_dim`).
"""

from dataclasses import dataclass

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.io import MemoryFile
from rasterio.warp import Resampling, calculate_default_transform, reproject, transform_bounds


@dataclass
class ParsedSurfaceRaster:
    cols: int
    rows: int
    origin_x: float
    origin_y: float
    cell_size_x: float
    cell_size_y: float
    nodata: float | None
    heights: np.ndarray  # (rows*cols,) row-major float32, NaN at nodata
    crs_epsg: int
    min_z: float
    max_z: float


def parse_geotiff_surface(raw: bytes, crs_epsg_hint: int | None = None) -> ParsedSurfaceRaster:
    with MemoryFile(raw) as memfile, memfile.open() as ds:
        band = ds.read(1, masked=True).astype("float64")
        transform = ds.transform
        crs_epsg = (ds.crs.to_epsg() if ds.crs else None) or crs_epsg_hint or 4326
        rows, cols = band.shape
        origin_x = transform.c
        origin_y = transform.f
        cell_size_x = transform.a
        cell_size_y = -transform.e
        nodata = ds.nodata

    heights = band.filled(np.nan).astype(np.float32).reshape(-1)
    finite = heights[np.isfinite(heights)]
    min_z = float(finite.min()) if finite.size else 0.0
    max_z = float(finite.max()) if finite.size else 0.0

    return ParsedSurfaceRaster(
        cols=cols, rows=rows,
        origin_x=origin_x, origin_y=origin_y,
        cell_size_x=cell_size_x, cell_size_y=cell_size_y,
        nodata=nodata, heights=heights, crs_epsg=crs_epsg,
        min_z=min_z, max_z=max_z,
    )


@dataclass
class ParsedMapRaster:
    png_bytes: bytes
    bounds_geojson: dict


def parse_geotiff_map_raster(raw: bytes, crs_epsg_hint: int | None = None, max_dim: int = 4000) -> ParsedMapRaster:
    dst_crs = CRS.from_epsg(4326)

    with MemoryFile(raw) as memfile, memfile.open() as src:
        src_crs = src.crs or CRS.from_epsg(crs_epsg_hint or 4326)

        transform, out_w, out_h = calculate_default_transform(src_crs, dst_crs, src.width, src.height, *src.bounds)
        if max(out_w, out_h) > max_dim:
            scale = max_dim / max(out_w, out_h)
            dst_width = max(1, int(out_w * scale))
            dst_height = max(1, int(out_h * scale))
            transform, out_w, out_h = calculate_default_transform(
                src_crs, dst_crs, src.width, src.height, *src.bounds,
                dst_width=dst_width, dst_height=dst_height,
            )

        band_count = 1 if src.count == 1 else min(src.count, 3)
        dst_array = np.zeros((band_count, out_h, out_w), dtype=np.float64)
        src_nodata = src.nodata

        for i in range(1, band_count + 1):
            reproject(
                source=rasterio.band(src, i),
                destination=dst_array[i - 1],
                src_transform=src.transform,
                src_crs=src_crs,
                dst_transform=transform,
                dst_crs=dst_crs,
                src_nodata=src_nodata,
                dst_nodata=np.nan,
                resampling=Resampling.bilinear,
            )

        bounds4326 = transform_bounds(src_crs, dst_crs, *src.bounds)

    uint8_array = np.zeros((band_count, out_h, out_w), dtype=np.uint8)
    for i in range(band_count):
        band = dst_array[i]
        finite = band[np.isfinite(band)]
        if finite.size == 0:
            continue
        lo, hi = float(finite.min()), float(finite.max())
        if hi <= lo:
            hi = lo + 1.0
        scaled = np.nan_to_num((band - lo) / (hi - lo), nan=0.0)
        uint8_array[i] = np.clip(scaled * 255.0, 0, 255).astype(np.uint8)

    profile = {
        "driver": "PNG",
        "width": int(out_w),
        "height": int(out_h),
        "count": band_count,
        "dtype": "uint8",
    }
    with MemoryFile() as out_memfile:
        with out_memfile.open(**profile) as out_ds:
            out_ds.write(uint8_array)
        png_bytes = out_memfile.read()

    minx, miny, maxx, maxy = bounds4326
    bounds_geojson = {
        "type": "Polygon",
        "coordinates": [[[minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny]]],
    }

    return ParsedMapRaster(png_bytes=png_bytes, bounds_geojson=bounds_geojson)
