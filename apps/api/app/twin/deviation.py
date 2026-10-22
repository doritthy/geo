"""As-built vs design: signed distance from every scan point to the nearest
BIM surface, coloured into a deviation map, aggregated per BIM element.

Algorithm (pure numpy/scipy, no GPU):
1. Work in a local east/north/up frame around the scan (float64, metres).
2. Subdivide BIM triangles until edges are <= `cell` so a KD-tree over
   triangle centroids gives reliable nearest candidates even for large
   faces (a 36 m slab is two triangles in the IFC tessellation).
3. For each point take the k nearest candidate triangles and compute the
   exact point-triangle distance (Ericson, "Real-Time Collision Detection");
   sign = side of the original face normal (+ outside / - inside material).
4. Points farther than `max_distance` from any surface are "not related to
   the model" (terrain, scaffolding, neighbours) and left uncoloured.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

# Diverging bins (metres) -> RGB. Matches the legend in the web client.
DEFAULT_TOLERANCES = (0.01, 0.05, 0.10)
UNRELATED_RGB = (110, 110, 110)


def bin_colors() -> list[tuple[str, tuple[int, int, int]]]:
    return [
        ("< −t3", (30, 64, 175)),
        ("−t3…−t2", (59, 130, 246)),
        ("−t2…−t1", (147, 197, 253)),
        ("±t1", (34, 197, 94)),
        ("t1…t2", (250, 204, 21)),
        ("t2…t3", (249, 115, 22)),
        ("> t3", (220, 38, 38)),
    ]


def classify(d: np.ndarray, tol: tuple[float, float, float]) -> np.ndarray:
    """Bin index 0..6 per distance (NaN -> -1)."""
    t1, t2, t3 = tol
    edges = np.array([-t3, -t2, -t1, t1, t2, t3])
    out = np.searchsorted(edges, d, side="right").astype(np.int64)
    out[np.isnan(d)] = -1
    return out


def colorize(d: np.ndarray, tol: tuple[float, float, float]) -> np.ndarray:
    lut = np.array([c for _, c in bin_colors()], dtype=np.uint8)
    b = classify(d, tol)
    rgb = np.empty((len(d), 3), dtype=np.uint8)
    rgb[:] = UNRELATED_RGB
    ok = b >= 0
    rgb[ok] = lut[b[ok]]
    return rgb


def subdivide(tris: np.ndarray, parent: np.ndarray, max_edge: float, max_tris: int = 6_000_000):
    """Midpoint-subdivide triangles (1 -> 4) until every edge <= max_edge."""
    while True:
        e = np.stack(
            [np.linalg.norm(tris[:, 1] - tris[:, 0], axis=1),
             np.linalg.norm(tris[:, 2] - tris[:, 1], axis=1),
             np.linalg.norm(tris[:, 0] - tris[:, 2], axis=1)],
            axis=1,
        ).max(axis=1)
        big = e > max_edge
        if not big.any() or len(tris) + 3 * big.sum() > max_tris:
            return tris, parent
        t = tris[big]
        a, b, c = t[:, 0], t[:, 1], t[:, 2]
        ab, bc, ca = (a + b) / 2, (b + c) / 2, (c + a) / 2
        new = np.concatenate([
            np.stack([a, ab, ca], 1), np.stack([ab, b, bc], 1),
            np.stack([ca, bc, c], 1), np.stack([ab, bc, ca], 1),
        ])
        p = np.tile(parent[big], 4)
        tris = np.concatenate([tris[~big], new])
        parent = np.concatenate([parent[~big], p])


def closest_on_triangles(p: np.ndarray, a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
    """Vectorised closest point on triangle (a, b, c) to p; all (n, 3)."""
    ab, ac, ap = b - a, c - a, p - a
    d1 = np.einsum("ij,ij->i", ab, ap)
    d2 = np.einsum("ij,ij->i", ac, ap)
    bp = p - b
    d3 = np.einsum("ij,ij->i", ab, bp)
    d4 = np.einsum("ij,ij->i", ac, bp)
    cp = p - c
    d5 = np.einsum("ij,ij->i", ab, cp)
    d6 = np.einsum("ij,ij->i", ac, cp)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2

    res = np.empty_like(p)
    done = np.zeros(len(p), dtype=bool)

    def put(mask, val):
        nonlocal done
        m = mask & ~done
        res[m] = val[m] if val.ndim == 2 else val
        done |= m

    put((d1 <= 0) & (d2 <= 0), a)
    put((d3 >= 0) & (d4 <= d3), b)
    with np.errstate(divide="ignore", invalid="ignore"):
        v = d1 / (d1 - d3)
        put((vc <= 0) & (d1 >= 0) & (d3 <= 0), a + v[:, None] * ab)
        put((d6 >= 0) & (d5 <= d6), c)
        w = d2 / (d2 - d6)
        put((vb <= 0) & (d2 >= 0) & (d6 <= 0), a + w[:, None] * ac)
        w2 = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        put((va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0), b + w2[:, None] * (c - b))
        denom = 1.0 / (va + vb + vc)
        vv = vb * denom
        ww = vc * denom
        inside = a + ab * vv[:, None] + ac * ww[:, None]
    res[~done] = inside[~done]
    return res


@dataclass
class DeviationResult:
    distance: np.ndarray  # (n,) signed metres, NaN = unrelated
    element: np.ndarray  # (n,) feature index of the nearest element, -1 = none


def compute(points: np.ndarray, triangles: np.ndarray, tri_feature: np.ndarray, max_distance: float = 0.3,
            k: int = 12, chunk: int = 200_000) -> DeviationResult:
    """`points` (n,3) and `triangles` (m,3,3) in the same metric frame."""
    n = len(points)
    dist = np.full(n, np.nan)
    elem = np.full(n, -1, dtype=np.int64)
    if n == 0 or len(triangles) == 0:
        return DeviationResult(dist, elem)

    tri0 = triangles.astype(np.float64)
    nrm = np.cross(tri0[:, 1] - tri0[:, 0], tri0[:, 2] - tri0[:, 0])
    ln = np.linalg.norm(nrm, axis=1)
    keep = ln > 1e-12
    tri0, nrm, feat = tri0[keep], nrm[keep] / ln[keep, None], tri_feature[keep]
    parent0 = np.arange(len(tri0))

    # Only geometry near the scan matters.
    lo, hi = points.min(axis=0) - max_distance, points.max(axis=0) + max_distance
    near = ((tri0.max(axis=1) >= lo) & (tri0.min(axis=1) <= hi)).all(axis=1)
    tri0, nrm, feat, parent0 = tri0[near], nrm[near], feat[near], parent0[near]
    if len(tri0) == 0:
        return DeviationResult(dist, elem)

    cell = max(max_distance * 2, 0.25)
    tris, parent = subdivide(tri0, np.arange(len(tri0)), cell)
    tree = cKDTree(tris.mean(axis=1))
    kk = min(k, len(tris))
    reach = max_distance + cell

    for s in range(0, n, chunk):
        p = points[s : s + chunk]
        _, cand = tree.query(p, k=kk, distance_upper_bound=reach)
        cand = cand.reshape(len(p), kk)
        best = np.full(len(p), np.inf)
        best_tri = np.full(len(p), -1, dtype=np.int64)
        best_sign = np.zeros(len(p))
        for j in range(kk):
            cj = cand[:, j]
            valid = cj < len(tris)
            if not valid.any():
                continue
            idx = np.nonzero(valid)[0]
            t = tris[cj[idx]]
            q = closest_on_triangles(p[idx], t[:, 0], t[:, 1], t[:, 2])
            diff = p[idx] - q
            d = np.linalg.norm(diff, axis=1)
            better = d < best[idx]
            ii = idx[better]
            best[ii] = d[better]
            par = parent[cj[ii]]
            best_tri[ii] = par
            best_sign[ii] = np.sign(np.einsum("ij,ij->i", diff[better], nrm[par]))
        ok = best <= max_distance
        sl = slice(s, s + len(p))
        dd = np.where(ok, best * np.where(best_sign == 0, 1.0, best_sign), np.nan)
        dist[sl] = dd
        elem[sl] = np.where(ok, feat[np.clip(best_tri, 0, None)], -1)
    return DeviationResult(dist, elem)


def element_stats(res: DeviationResult, n_elements: int, tol: tuple[float, float, float]) -> list[dict]:
    """Per element: point count, mean/RMS/max |d|, signed mean, share out of tolerance t2."""
    out = []
    ok = res.element >= 0
    if not ok.any():
        return out
    e = res.element[ok]
    d = res.distance[ok]
    order = np.argsort(e, kind="stable")
    e, d = e[order], d[order]
    bounds = np.flatnonzero(np.diff(e)) + 1
    for part in np.split(np.arange(len(e)), bounds):
        dd = d[part]
        a = np.abs(dd)
        out.append({
            "element": int(e[part[0]]),
            "points": int(len(dd)),
            "mean": float(dd.mean()),
            "mean_abs": float(a.mean()),
            "rms": float(np.sqrt((dd ** 2).mean())),
            "max_abs": float(a.max()),
            "p95_abs": float(np.percentile(a, 95)),
            "out_of_tolerance": float((a > tol[1]).mean()),
        })
    out.sort(key=lambda r: -r["p95_abs"])
    return out


def histogram(res: DeviationResult, tol: tuple[float, float, float]) -> dict:
    b = classify(res.distance, tol)
    counts = [int((b == i).sum()) for i in range(7)]
    related = int((b >= 0).sum())
    d = res.distance[~np.isnan(res.distance)]
    return {
        "bins": [{"label": lbl.replace("t1", f"{tol[0]*100:g}").replace("t2", f"{tol[1]*100:g}").replace("t3", f"{tol[2]*100:g}") + " см",
                  "color": "#%02x%02x%02x" % rgb, "count": c}
                 for (lbl, rgb), c in zip(bin_colors(), counts)],
        "related_points": related,
        "unrelated_points": int(len(res.distance) - related),
        "within_tolerance": float(((np.abs(d) <= tol[1]).mean()) if len(d) else 0.0),
        "mean": float(d.mean()) if len(d) else None,
        "rms": float(np.sqrt((d ** 2).mean())) if len(d) else None,
        "p95_abs": float(np.percentile(np.abs(d), 95)) if len(d) else None,
    }
