"""Fine alignment of a scan to the BIM model (ICP, point-to-plane).

Construction scans are already levelled (registered to gravity by the
scanner / survey control), so only 4 degrees of freedom are estimated:
rotation about the vertical axis + 3D translation. This is far more robust
than 6-DOF ICP on partially built structures. The result is stored as
`georef.alignment` (ECEF 4x4, column-major) on the scan asset and applied
by the viewer and by later analyses.
"""

from __future__ import annotations

import math
import uuid

import numpy as np
from scipy.spatial import cKDTree
from sqlalchemy.orm import Session

from app.models import Analysis, SceneAsset
from app.twin import georef as geo


def sample_surface(tris: np.ndarray, n: int, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Area-weighted random points on triangles + their unit normals."""
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    cross = np.cross(b - a, c - a)
    area = np.linalg.norm(cross, axis=1) / 2
    keep = area > 1e-9
    a, b, c, cross, area = a[keep], b[keep], c[keep], cross[keep], area[keep]
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(area), size=n, p=area / area.sum())
    u, v = rng.random(n), rng.random(n)
    flip = u + v > 1
    u[flip], v[flip] = 1 - u[flip], 1 - v[flip]
    pts = a[idx] + u[:, None] * (b[idx] - a[idx]) + v[:, None] * (c[idx] - a[idx])
    nrm = cross[idx] / np.linalg.norm(cross[idx], axis=1)[:, None]
    return pts, nrm


def icp_4dof(src: np.ndarray, tgt: np.ndarray, tgt_n: np.ndarray, max_dist: float = 0.5,
             iterations: int = 40) -> dict:
    """Returns {matrix (4x4 local), rmse_before, rmse_after, yaw_deg, translation, inliers, iterations}."""
    tree = cKDTree(tgt)
    total = np.eye(4)
    cur = src.copy()
    thr = max_dist
    rmse_before = None
    it = 0
    for it in range(1, iterations + 1):
        d, j = tree.query(cur, distance_upper_bound=thr)
        ok = np.isfinite(d)
        if ok.sum() < 50:
            break
        p, q, n = cur[ok], tgt[j[ok]], tgt_n[j[ok]]
        r = np.einsum("ij,ij->i", n, p - q)
        if rmse_before is None:
            rmse_before = float(np.sqrt((r ** 2).mean()))
        jac = np.column_stack([n[:, 0] * -p[:, 1] + n[:, 1] * p[:, 0], n[:, 0], n[:, 1], n[:, 2]])
        # Robust (Huber-like) weights
        s = max(np.median(np.abs(r)) * 1.4826, 1e-4)
        w = 1.0 / np.maximum(1.0, np.abs(r) / (2 * s))
        x, *_ = np.linalg.lstsq(jac * w[:, None], -r * w, rcond=None)
        th, tx, ty, tz = x
        step = np.eye(4)
        step[:2, :2] = [[math.cos(th), -math.sin(th)], [math.sin(th), math.cos(th)]]
        step[:3, 3] = [tx, ty, tz]
        cur = cur @ step[:3, :3].T + step[:3, 3]
        total = step @ total
        thr = max(min(thr, 3.0 * float(np.percentile(np.abs(r), 90))), 0.02)
        if abs(th) < 1e-6 and np.linalg.norm(x[1:]) < 1e-4:
            break
    d, j = tree.query(cur, distance_upper_bound=thr)
    ok = np.isfinite(d)
    r = np.einsum("ij,ij->i", tgt_n[j[ok]], cur[ok] - tgt[j[ok]]) if ok.any() else np.zeros(1)
    return {
        "matrix": total,
        "rmse_before": rmse_before,
        "rmse_after": float(np.sqrt((r ** 2).mean())),
        "yaw_deg": math.degrees(math.atan2(total[1, 0], total[0, 0])),
        "translation": total[:3, 3].tolist(),
        "inliers": int(ok.sum()),
        "iterations": it,
    }


def _score(src: np.ndarray, tree: cKDTree, tol: float = 0.03) -> float:
    d, _ = tree.query(src, distance_upper_bound=tol)
    return float(np.isfinite(d).mean())


def icp_multistart(src: np.ndarray, tgt: np.ndarray, tgt_n: np.ndarray, max_dist: float = 0.5,
                   search: float = 0.4) -> dict:
    """Thin elements (walls, slabs) make plain ICP converge onto the wrong
    face when the initial error is comparable to their thickness (a scan sees
    the outer face, nearest-neighbour picks the inner one). Try a grid of
    initial offsets on a subsample, keep the start whose result matches the
    most points within 3 cm, then refine on all points from there."""
    rng = np.random.default_rng(0)
    sub = src[rng.choice(len(src), min(len(src), 20_000), replace=False)]
    tree = cKDTree(tgt)
    steps = np.linspace(-search, search, 5)
    best: tuple | None = None
    for dx in steps:
        for dy in steps:
            for dz in (-search / 2, 0.0, search / 2):
                start = np.eye(4)
                start[:3, 3] = [dx, dy, dz]
                moved = sub + start[:3, 3]
                r = icp_4dof(moved, tgt, tgt_n, max_dist=max_dist, iterations=15)
                m = r["matrix"] @ start
                score = _score(sub @ m[:3, :3].T + m[:3, 3], tree)
                # Ties are common (a z shift by slab thickness matches the slab's
                # other face equally well): prefer the smallest correction, since
                # the georeference is assumed to be roughly right.
                size = float(np.linalg.norm(m[:3, 3]))
                tie = 0.03 * max(score, best[0]) if best else 0.0
                if best is None or score > best[0] + tie or (abs(score - best[0]) <= tie and size < best[2]):
                    best = (score, m, size)
    start = best[1]
    r = icp_4dof(src @ start[:3, :3].T + start[:3, 3], tgt, tgt_n, max_dist=max_dist)
    total = r["matrix"] @ start
    r0 = icp_4dof(src, tgt, tgt_n, max_dist=max_dist, iterations=1)  # residual before any correction
    r.update({
        "matrix": total,
        "yaw_deg": math.degrees(math.atan2(total[1, 0], total[0, 0])),
        "translation": total[:3, 3].tolist(),
        "rmse_before": r0["rmse_before"],
        "match_ratio": _score(src @ total[:3, :3].T + total[:3, 3], tree),
    })
    return r


def run_alignment(db: Session, analysis: Analysis) -> None:
    from app.twin.analysis_jobs import load_mesh_world, load_points_world, local_frame, to_local

    p = analysis.params
    cloud = db.get(SceneAsset, uuid.UUID(p["cloud_asset_id"]))
    bim = db.get(SceneAsset, uuid.UUID(p["bim_asset_id"]))
    if cloud is None or bim is None or cloud.kind != "point_cloud" or bim.kind != "bim":
        raise ValueError("Нужны облако точек и BIM-модель")

    pts_w, _, _ = load_points_world(cloud, max_points=200_000)
    _, tris_w = load_mesh_world(bim)
    origin, axes = local_frame(pts_w)
    src = to_local(pts_w, origin, axes)
    tris = to_local(tris_w.reshape(-1, 3), origin, axes).reshape(-1, 3, 3)
    tgt, tgt_n = sample_surface(tris, 300_000)
    res = icp_multistart(src, tgt, tgt_n, max_dist=float(p.get("max_distance", 0.5)))

    # Local delta -> ECEF delta:  D = L^-1 · G · L,  L(x) = axes · (x - origin)
    L = np.eye(4)
    L[:3, :3] = axes
    L[:3, 3] = -axes @ origin
    Linv = np.eye(4)
    Linv[:3, :3] = axes.T
    Linv[:3, 3] = origin
    delta = Linv @ res["matrix"] @ L

    applied = bool(p.get("apply", True))
    if applied:
        old = np.asarray(cloud.georef.get("alignment") or np.eye(4).T.reshape(-1).tolist(), dtype=np.float64).reshape(4, 4).T
        new = delta @ old
        cloud.georef = {**cloud.georef, "alignment": new.T.reshape(-1).tolist(), "alignment_source": "icp"}
    analysis.result = {
        "rmse_before": res["rmse_before"], "rmse_after": res["rmse_after"],
        "yaw_deg": res["yaw_deg"], "translation_enu": res["translation"],
        "inliers": res["inliers"], "iterations": res["iterations"], "applied": applied,
        "match_ratio": res["match_ratio"],
        "cloud": {"id": str(cloud.id), "name": cloud.name}, "bim": {"id": str(bim.id), "name": bim.name, "version": bim.version},
    }
