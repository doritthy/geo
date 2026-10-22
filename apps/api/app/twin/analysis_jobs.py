"""Background analyses on scene assets.

deviation: scan (point cloud asset) vs design (BIM asset) -> coloured
deviation-map tileset (new point_cloud asset), histogram and per-element
statistics stored on the Analysis row.

alignment: ICP of a scan to a BIM model -> `georef.alignment` matrix on the
scan asset (see app/twin/icp.py).
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import uuid
from datetime import datetime, timezone

import numpy as np
from sqlalchemy.orm import Session

from app.models import Analysis, SceneAsset
from app.storage import upload_bytes, upload_directory
from app.twin import deviation as dev
from app.twin import georef as geo
from app.twin.jobs import asset_prefix
from app.twin.pointcloud_convert import array_source, convert_point_cloud
from app.twin.tile_reader import read_b3dm_mesh, read_pnts

logger = logging.getLogger(__name__)

MAX_ANALYSIS_POINTS = 4_000_000
MAX_ELEMENTS_STORED = 5000


def _entry(asset: SceneAsset) -> str:
    return asset.stats.get("entry", "tileset.json")


def load_points_world(asset: SceneAsset, max_points: int = MAX_ANALYSIS_POINTS) -> tuple[np.ndarray, np.ndarray, int]:
    xyz, rgb = read_pnts(asset.storage_prefix, _entry(asset))
    total = len(xyz)
    if max_points and total > max_points:
        sel = np.random.default_rng(0).choice(total, max_points, replace=False)
        xyz, rgb = xyz[sel], rgb[sel]
    m = geo.asset_world_matrix(asset.georef, asset.stats.get("center"))
    return geo.apply_matrix(m, xyz), rgb, total


def load_mesh_world(asset: SceneAsset):
    mesh = read_b3dm_mesh(asset.storage_prefix, _entry(asset))
    m = geo.asset_world_matrix(asset.georef, asset.stats.get("center"))
    tris = geo.apply_matrix(m, mesh.triangles.reshape(-1, 3)).reshape(-1, 3, 3)
    return mesh, tris


def local_frame(points_world: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(origin ECEF, rotation rows e/n/u) of a tangent frame at the data centre."""
    origin = points_world.mean(axis=0)
    llh = geo.ecef_to_llh(origin)[0]
    return origin, geo.enu_axes(llh[0], llh[1])


def to_local(pts: np.ndarray, origin: np.ndarray, axes: np.ndarray) -> np.ndarray:
    return (pts - origin) @ axes.T


def _finish(db: Session, analysis: Analysis, status: str, error: str | None = None) -> None:
    analysis.status = status
    analysis.error_message = error
    analysis.finished_at = datetime.now(timezone.utc)
    db.commit()


def run_deviation(db: Session, analysis: Analysis) -> None:
    p = analysis.params
    cloud = db.get(SceneAsset, uuid.UUID(p["cloud_asset_id"]))
    bim = db.get(SceneAsset, uuid.UUID(p["bim_asset_id"]))
    if cloud is None or bim is None or cloud.kind != "point_cloud" or bim.kind != "bim":
        raise ValueError("Нужны облако точек и BIM-модель")
    tol = tuple(float(t) for t in p.get("tolerances", dev.DEFAULT_TOLERANCES))
    max_distance = float(p.get("max_distance", 0.3))

    pts_w, _rgb, total = load_points_world(cloud)
    mesh, tris_w = load_mesh_world(bim)
    if len(pts_w) == 0 or len(tris_w) == 0:
        raise ValueError("Пустое облако или модель")
    origin, axes = local_frame(pts_w)
    res = dev.compute(
        to_local(pts_w, origin, axes),
        to_local(tris_w.reshape(-1, 3), origin, axes).reshape(-1, 3, 3),
        mesh.feature, max_distance=max_distance,
    )

    stats = dev.element_stats(res, len(mesh.global_ids), tol)
    for row in stats:
        i = row.pop("element")
        row["global_id"] = mesh.global_ids[i]
        row["ifc_type"] = mesh.ifc_types[i]
        row["name"] = mesh.names[i]
        sel = res.element == i
        llh = geo.ecef_to_llh(pts_w[sel].mean(axis=0))[0]
        row["longitude"], row["latitude"], row["height"] = (float(v) for v in llh)
    hist = dev.histogram(res, tol)

    # Coloured deviation map as its own streamed tileset.
    work = tempfile.mkdtemp(prefix="dev-")
    try:
        out = f"{work}/out"
        conv = convert_point_cloud(None, "", out, {}, source=array_source(pts_w, dev.colorize(res.distance, tol)))
        asset_id = uuid.uuid4()
        prefix = asset_prefix(analysis.project_id, asset_id)
        files = upload_directory(prefix, out)
        # Plan-view sample for the PDF report (local metres + bin index).
        loc = to_local(pts_w, origin, axes)
        sample = np.random.default_rng(1).choice(len(loc), min(len(loc), 300_000), replace=False)
        np.savez_compressed(f"{work}/plan.npz", xy=loc[sample, :2].astype(np.float32),
                            bins=dev.classify(res.distance[sample], tol).astype(np.int8))
        with open(f"{work}/plan.npz", "rb") as fh:
            upload_bytes(f"{prefix}/_analysis/plan.npz", fh.read())
    finally:
        shutil.rmtree(work, ignore_errors=True)

    result_asset = SceneAsset(
        id=asset_id, project_id=analysis.project_id, name=f"Отклонения: {cloud.name} ↔ {bim.name} v{bim.version}",
        kind="point_cloud", storage_prefix=prefix, georef=conv.georef,
        stats={**conv.stats, "file_count": files, "entry": "tileset.json", "analysis_id": str(analysis.id),
               "deviation": {"tolerances": tol, "within_tolerance": hist["within_tolerance"]}},
        captured_at=cloud.captured_at,
    )
    db.add(result_asset)
    db.flush()
    analysis.result_asset_id = asset_id
    analysis.result = {
        "tolerances": list(tol), "max_distance": max_distance, "histogram": hist,
        "points_used": int(len(pts_w)), "points_total": int(total),
        "elements": stats[:MAX_ELEMENTS_STORED], "elements_total": len(stats),
        "cloud": {"id": str(cloud.id), "name": cloud.name, "captured_at": str(cloud.captured_at or "")},
        "bim": {"id": str(bim.id), "name": bim.name, "version": bim.version},
        "frame_origin": origin.tolist(),
    }


def run_analysis(db: Session, analysis_id: uuid.UUID) -> None:
    analysis = db.get(Analysis, analysis_id)
    if analysis is None:
        return
    analysis.status = "running"
    db.commit()
    try:
        if analysis.kind == "deviation":
            run_deviation(db, analysis)
        elif analysis.kind == "alignment":
            from app.twin.icp import run_alignment

            run_alignment(db, analysis)
        else:
            raise ValueError(f"Неизвестный тип анализа {analysis.kind}")
        _finish(db, analysis, "ready")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Analysis %s failed", analysis_id)
        db.rollback()
        analysis = db.get(Analysis, analysis_id)
        if analysis is not None:
            _finish(db, analysis, "error", str(exc)[:2000])
