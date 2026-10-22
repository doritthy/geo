"""Vertical section profile along a line A→B: BIM section lines (triangles
cut by the vertical plane) and scan points within a corridor, both as
(distance along the line, height) for a 2D chart."""

from __future__ import annotations

import numpy as np

from app.twin import georef as geo


def frame_at(lon: float, lat: float) -> tuple[np.ndarray, np.ndarray]:
    origin = geo.llh_to_ecef(lon, lat, 0.0)
    return origin, geo.enu_axes(lon, lat)


def section_segments(tris_local: np.ndarray, a: np.ndarray, b: np.ndarray, max_segments: int = 20000) -> list:
    """Intersect triangles (local ENU) with the vertical plane through a, b
    (2D points). Returns [[s0, z0, s1, z1], ...] with s along a→b."""
    d = b - a
    length = float(np.linalg.norm(d))
    if length == 0 or len(tris_local) == 0:
        return []
    u = d / length
    n = np.array([-u[1], u[0]])
    rel = tris_local[:, :, :2] - a  # (m, 3, 2)
    dist = rel @ n  # signed distance to plane, (m, 3)
    along = rel @ u
    crosses = (dist.min(axis=1) < 0) & (dist.max(axis=1) > 0)
    crosses &= (along.max(axis=1) >= 0) & (along.min(axis=1) <= length)
    t, dd, aa = tris_local[crosses], dist[crosses], along[crosses]
    segs = []
    for edge in ((0, 1), (1, 2), (2, 0)):
        i, j = edge
        di, dj = dd[:, i], dd[:, j]
        hit = (di < 0) != (dj < 0)
        f = np.where(hit, di / np.where(hit, di - dj, 1.0), np.nan)
        s = aa[:, i] + f * (aa[:, j] - aa[:, i])
        z = t[:, i, 2] + f * (t[:, j, 2] - t[:, i, 2])
        segs.append((s, z))
    pts = np.stack([np.column_stack(p) for p in segs], axis=1)  # (k, 3, 2) with NaN for non-hit edges
    out = []
    for row in pts:
        valid = row[~np.isnan(row[:, 0])]
        if len(valid) >= 2:
            (s0, z0), (s1, z1) = valid[0], valid[1]
            s0, s1 = np.clip([s0, s1], 0, length)
            out.append([round(float(s0), 3), round(float(z0), 3), round(float(s1), 3), round(float(z1), 3)])
    return out[:max_segments]


def corridor_points(pts_local: np.ndarray, a: np.ndarray, b: np.ndarray, width: float, max_points: int = 8000) -> list:
    d = b - a
    length = float(np.linalg.norm(d))
    if length == 0 or len(pts_local) == 0:
        return []
    u = d / length
    n = np.array([-u[1], u[0]])
    rel = pts_local[:, :2] - a
    s = rel @ u
    off = np.abs(rel @ n)
    sel = (off <= width / 2) & (s >= 0) & (s <= length)
    s, z = s[sel], pts_local[sel, 2]
    if len(s) > max_points:
        idx = np.random.default_rng(0).choice(len(s), max_points, replace=False)
        s, z = s[idx], z[idx]
    return np.round(np.column_stack([s, z]), 3).tolist()
