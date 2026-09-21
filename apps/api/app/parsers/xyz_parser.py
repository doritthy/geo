"""Simple XYZ point-file parser -> gridded onto a regular raster via
`scipy.interpolate.griddata` (linear, with a nearest-neighbor second pass to
fill points outside the convex hull) so it can be stored as an ordinary
`surfaces` row like a GeoTIFF/Surfer grid. Whitespace- or comma-delimited,
optional header row.
"""

import numpy as np
from scipy.interpolate import griddata

from app.parsers.geotiff_parser import ParsedSurfaceRaster


def _parse_points(raw: bytes) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    text = raw.decode("utf-8", errors="replace")
    xs, ys, zs = [], [], []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.replace(",", " ").split()
        if len(parts) < 3:
            continue
        try:
            x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
        except ValueError:
            continue  # header row or malformed line
        xs.append(x)
        ys.append(y)
        zs.append(z)
    if len(xs) < 3:
        raise ValueError("XYZ file needs at least 3 valid point rows")
    return np.array(xs), np.array(ys), np.array(zs)


def parse_xyz(raw: bytes, crs_epsg_hint: int | None = None, target_dim: int = 200) -> ParsedSurfaceRaster:
    x, y, z = _parse_points(raw)
    n = len(x)

    xmin, xmax = float(x.min()), float(x.max())
    ymin, ymax = float(y.min()), float(y.max())

    dim = min(target_dim, max(2, int(np.ceil(np.sqrt(n)))))
    cols, rows = dim, dim

    if xmax == xmin:
        xmax = xmin + 1.0
    if ymax == ymin:
        ymax = ymin + 1.0

    gx = np.linspace(xmin, xmax, cols)
    gy = np.linspace(ymin, ymax, rows)
    grid_x, grid_y = np.meshgrid(gx, gy)  # shape (rows, cols)

    grid_z = griddata((x, y), z, (grid_x, grid_y), method="linear")
    nan_mask = np.isnan(grid_z)
    if nan_mask.any():
        filled = griddata((x, y), z, (grid_x, grid_y), method="nearest")
        grid_z[nan_mask] = filled[nan_mask]

    heights = grid_z.astype(np.float32).reshape(-1)
    cell_size_x = (xmax - xmin) / (cols - 1) if cols > 1 else 0.0
    cell_size_y = (ymax - ymin) / (rows - 1) if rows > 1 else 0.0

    finite = heights[np.isfinite(heights)]
    min_z = float(finite.min()) if finite.size else 0.0
    max_z = float(finite.max()) if finite.size else 0.0

    return ParsedSurfaceRaster(
        cols=cols, rows=rows,
        origin_x=xmin, origin_y=ymin,
        cell_size_x=cell_size_x, cell_size_y=cell_size_y,
        nodata=None, heights=heights,
        crs_epsg=crs_epsg_hint or 4326,
        min_z=min_z, max_z=max_z,
    )
