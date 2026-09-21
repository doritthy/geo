"""Surfer ASCII .grd format parser.

Format:
  DSAA
  nx ny
  xlo xhi
  ylo yhi
  zlo zhi
  <nx*ny space-separated z values, row-major, row0 = ylo..yhi bottom row first>

Produces the same `ParsedSurfaceRaster` shape as geotiff_parser so jobs.py
can treat both identically when writing a `surfaces` row.
"""

import numpy as np

from app.parsers.geotiff_parser import ParsedSurfaceRaster

_NODATA_SENTINEL = 1.70141e38


def parse_surfer_grd(raw: bytes, crs_epsg_hint: int | None = None) -> ParsedSurfaceRaster:
    text = raw.decode("utf-8", errors="replace")
    tokens = text.split()
    if not tokens or tokens[0].upper() not in ("DSAA", "DSBB"):
        raise ValueError("Not a Surfer ASCII grid (missing DSAA header)")
    if tokens[0].upper() == "DSBB":
        raise ValueError("Surfer binary grid (DSBB) is not supported, only ASCII DSAA")

    idx = 1
    nx, ny = int(float(tokens[idx])), int(float(tokens[idx + 1]))
    idx += 2
    xlo, xhi = float(tokens[idx]), float(tokens[idx + 1])
    idx += 2
    ylo, yhi = float(tokens[idx]), float(tokens[idx + 1])
    idx += 2
    _zlo, _zhi = float(tokens[idx]), float(tokens[idx + 1])
    idx += 2

    expected = nx * ny
    raw_values = tokens[idx : idx + expected]
    if len(raw_values) != expected:
        raise ValueError(f"Surfer grid expected {expected} values, found {len(raw_values)}")
    values = np.array([float(v) for v in raw_values], dtype=np.float32)
    values = np.where(values >= _NODATA_SENTINEL * 0.99, np.nan, values)

    cell_size_x = (xhi - xlo) / (nx - 1) if nx > 1 else 0.0
    cell_size_y = (yhi - ylo) / (ny - 1) if ny > 1 else 0.0

    finite = values[np.isfinite(values)]
    min_z = float(finite.min()) if finite.size else float(_zlo)
    max_z = float(finite.max()) if finite.size else float(_zhi)

    return ParsedSurfaceRaster(
        cols=nx, rows=ny,
        origin_x=xlo, origin_y=ylo,
        cell_size_x=cell_size_x, cell_size_y=cell_size_y,
        nodata=_NODATA_SENTINEL, heights=values,
        crs_epsg=crs_epsg_hint or 4326,
        min_z=min_z, max_z=max_z,
    )
