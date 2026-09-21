"""Background parse job dispatch, run via FastAPI BackgroundTasks from the
files upload endpoint (see docs/LIMITATIONS.md: in-process, not Celery).

`dispatch_parse(file_id, db)` looks at the file's category/source_format,
calls the matching pure parser, writes the resulting rows, uploads any
binary buffers to object storage under deterministic keys, and sets
file.status to 'ready' or 'error'.
"""

import logging
import os
import uuid
from datetime import datetime, timezone

import numpy as np
from sqlalchemy.orm import Session

from app.binary import pack_float32_array, pack_grid_cells, pack_ijk, pack_well_log
from app.models import FileRecord, Grid, GridProperty, MapLayer, Surface, Well, WellLog, WellTrajectoryPoint
from app.parsers.geotiff_parser import parse_geotiff_map_raster, parse_geotiff_surface
from app.parsers.grdecl_parser import parse_grdecl
from app.parsers.las_parser import parse_las
from app.parsers.mesh_parser import parse_mesh
from app.parsers.shapefile_parser import parse_shapefile
from app.parsers.surfer_grd_parser import parse_surfer_grd
from app.parsers.trajectory_csv_parser import parse_csv_trajectory
from app.parsers.xyz_parser import parse_xyz
from app.storage import get_bytes, upload_bytes

logger = logging.getLogger(__name__)

_UNSUPPORTED_MESSAGES = {
    "resqml": (
        "RESQML files are accepted and stored but not parsed: RESQML is a full "
        "EPC/XML+HDF5 standard that needs a dedicated SDK to read correctly. "
        "See docs/LIMITATIONS.md."
    ),
    "dxf": (
        "DXF files are accepted and stored but not rendered in this pass. "
        "See docs/LIMITATIONS.md."
    ),
    "dwg": (
        "DWG is a closed binary CAD format requiring Teigha/ODA licensing to "
        "parse; the file is accepted and stored but not rendered. See "
        "docs/LIMITATIONS.md."
    ),
}


def _ijk_storage_key(project_id: uuid.UUID, grid_id: uuid.UUID) -> str:
    return f"projects/{project_id}/grids/{grid_id}/_ijk.bin"


def _get_or_create_well(
    db: Session,
    project_id: uuid.UUID,
    name: str,
    source_file_id: uuid.UUID,
    crs_epsg: int = 4326,
    surface_x: float | None = None,
    surface_y: float | None = None,
    kb_elevation: float | None = None,
    total_depth: float | None = None,
) -> Well:
    well = db.query(Well).filter(Well.project_id == project_id, Well.name == name).first()
    if well is None:
        well = Well(
            project_id=project_id,
            source_file_id=source_file_id,
            name=name,
            crs_epsg=crs_epsg,
            surface_x=surface_x,
            surface_y=surface_y,
            kb_elevation=kb_elevation,
            total_depth=total_depth,
        )
        db.add(well)
        db.flush()
        return well

    if well.surface_x is None and surface_x is not None:
        well.surface_x = surface_x
    if well.surface_y is None and surface_y is not None:
        well.surface_y = surface_y
    if well.kb_elevation is None and kb_elevation is not None:
        well.kb_elevation = kb_elevation
    if total_depth is not None:
        well.total_depth = max(well.total_depth or 0.0, total_depth)
    return well


def _process_las(db: Session, file: FileRecord) -> None:
    raw = get_bytes(file.storage_key)
    parsed = parse_las(raw)

    name = parsed.well_name
    if not name or name.upper() == "UNKNOWN":
        name = os.path.splitext(file.filename)[0] or "UNKNOWN"

    crs_epsg = file.metadata_.get("crs_epsg") or 4326
    well = _get_or_create_well(
        db, file.project_id, name, file.id,
        crs_epsg=crs_epsg,
        surface_x=parsed.surface_x, surface_y=parsed.surface_y,
        kb_elevation=parsed.kb_elevation, total_depth=parsed.total_depth,
    )

    for curve in parsed.curves:
        finite = curve.values[np.isfinite(curve.values)]
        min_v = float(finite.min()) if finite.size else 0.0
        max_v = float(finite.max()) if finite.size else 0.0
        log = WellLog(
            well_id=well.id,
            source_file_id=file.id,
            curve_name=curve.curve_name,
            unit=curve.unit,
            storage_key="",
            min_value=min_v,
            max_value=max_v,
            sample_count=len(curve.values),
        )
        db.add(log)
        db.flush()
        storage_key = f"projects/{file.project_id}/wells/{well.id}/logs/{log.id}.bin"
        log.storage_key = storage_key
        upload_bytes(storage_key, pack_well_log(curve.depths, curve.values))

    if parsed.trajectory:
        existing = db.query(WellTrajectoryPoint.seq).filter(WellTrajectoryPoint.well_id == well.id).count()
        if existing == 0:
            for seq, pt in enumerate(parsed.trajectory):
                db.add(
                    WellTrajectoryPoint(
                        well_id=well.id, seq=seq, md=pt.md, inclination=pt.inclination,
                        azimuth=pt.azimuth, tvd=pt.tvd, x=pt.x, y=pt.y, z=pt.z,
                    )
                )

    file.metadata_ = {**file.metadata_, "well_id": str(well.id), "curve_count": len(parsed.curves)}


def _process_csv_trajectory(db: Session, file: FileRecord) -> None:
    raw = get_bytes(file.storage_key)
    column_mapping = file.metadata_.get("column_mapping")
    name = os.path.splitext(file.filename)[0] or "UNKNOWN"
    crs_epsg = file.metadata_.get("crs_epsg") or 4326

    rows = parse_csv_trajectory(raw, column_mapping, kb_elevation=0.0)
    if not rows:
        raise ValueError("No valid trajectory rows parsed from CSV")

    well = _get_or_create_well(
        db, file.project_id, name, file.id,
        crs_epsg=crs_epsg,
        surface_x=rows[0].x, surface_y=rows[0].y,
        total_depth=max(r.md for r in rows),
    )

    db.query(WellTrajectoryPoint).filter(WellTrajectoryPoint.well_id == well.id).delete()
    for seq, row in enumerate(rows):
        db.add(
            WellTrajectoryPoint(
                well_id=well.id, seq=seq, md=row.md, inclination=row.inclination,
                azimuth=row.azimuth, tvd=row.tvd, x=row.x, y=row.y, z=row.z,
            )
        )

    file.metadata_ = {**file.metadata_, "well_id": str(well.id), "point_count": len(rows)}


def _process_grdecl(db: Session, file: FileRecord) -> None:
    raw = get_bytes(file.storage_key)
    parsed = parse_grdecl(raw)

    name = os.path.splitext(file.filename)[0] or "grid"
    crs_epsg = file.metadata_.get("crs_epsg") or 4326
    active_count = int(parsed.active_mask.sum())

    grid = Grid(
        project_id=file.project_id, source_file_id=file.id, name=name,
        nx=parsed.nx, ny=parsed.ny, nz=parsed.nz, crs_epsg=crs_epsg,
        bounds_min_x=parsed.bounds[0], bounds_min_y=parsed.bounds[1], bounds_min_z=parsed.bounds[2],
        bounds_max_x=parsed.bounds[3], bounds_max_y=parsed.bounds[4], bounds_max_z=parsed.bounds[5],
        active_cell_count=active_count,
    )
    db.add(grid)
    db.flush()

    cell_ids = np.arange(active_count, dtype=np.uint32)
    cells_key = f"projects/{file.project_id}/grids/{grid.id}/cells.bin"
    upload_bytes(cells_key, pack_grid_cells(parsed.centers, parsed.sizes, cell_ids))
    grid.cell_geometry_storage_key = cells_key

    # Internal-only (not part of the public API): natural (i, j, k) index per
    # active cell, in the same order as cells.bin/properties, so /sample can
    # reconstruct the structured lattice. Key is deterministic from grid.id,
    # so no schema change is needed to remember it.
    k_full, j_full, i_full = np.indices((parsed.nz, parsed.ny, parsed.nx))
    ijk_active = np.column_stack(
        [i_full.reshape(-1)[parsed.active_mask], j_full.reshape(-1)[parsed.active_mask], k_full.reshape(-1)[parsed.active_mask]]
    )
    upload_bytes(_ijk_storage_key(file.project_id, grid.id), pack_ijk(ijk_active))

    for prop_name, values in parsed.properties.items():
        finite = values[np.isfinite(values)]
        min_v = float(finite.min()) if finite.size else 0.0
        max_v = float(finite.max()) if finite.size else 0.0
        prop_key = f"projects/{file.project_id}/grids/{grid.id}/properties/{prop_name}.bin"
        upload_bytes(prop_key, pack_float32_array(values))
        db.add(
            GridProperty(
                grid_id=grid.id, name=prop_name, unit=None,
                storage_key=prop_key, min_value=min_v, max_value=max_v,
            )
        )

    file.metadata_ = {**file.metadata_, "grid_id": str(grid.id), "active_cell_count": active_count}


def _process_surface(db: Session, file: FileRecord, parsed) -> None:
    name = os.path.splitext(file.filename)[0] or "surface"
    surface = Surface(
        project_id=file.project_id, source_file_id=file.id, name=name, surface_kind="top",
        crs_epsg=parsed.crs_epsg, cols=parsed.cols, rows=parsed.rows,
        origin_x=parsed.origin_x, origin_y=parsed.origin_y,
        cell_size_x=parsed.cell_size_x, cell_size_y=parsed.cell_size_y,
        nodata_value=parsed.nodata, min_z=parsed.min_z, max_z=parsed.max_z,
    )
    db.add(surface)
    db.flush()

    heights_key = f"projects/{file.project_id}/surfaces/{surface.id}/heights.bin"
    upload_bytes(heights_key, pack_float32_array(np.nan_to_num(parsed.heights, nan=np.nan)))
    surface.heights_storage_key = heights_key

    file.metadata_ = {**file.metadata_, "surface_id": str(surface.id)}


def _process_geotiff(db: Session, file: FileRecord) -> None:
    raw = get_bytes(file.storage_key)
    crs_hint = file.metadata_.get("crs_epsg")

    if file.category == "map_raster":
        parsed = parse_geotiff_map_raster(raw, crs_epsg_hint=crs_hint)
        name = os.path.splitext(file.filename)[0] or "raster layer"
        raster_key = f"projects/{file.project_id}/map_layers/{uuid.uuid4()}/raster.png"
        upload_bytes(raster_key, parsed.png_bytes, content_type="image/png")
        layer = MapLayer(
            project_id=file.project_id, source_file_id=file.id, name=name, layer_kind="raster",
            crs_epsg=4326, bounds_geojson=parsed.bounds_geojson, storage_key=raster_key,
        )
        db.add(layer)
        db.flush()
        file.metadata_ = {**file.metadata_, "map_layer_id": str(layer.id)}
    else:
        parsed = parse_geotiff_surface(raw, crs_epsg_hint=crs_hint)
        _process_surface(db, file, parsed)


def _process_surfer_grd(db: Session, file: FileRecord) -> None:
    raw = get_bytes(file.storage_key)
    parsed = parse_surfer_grd(raw, crs_epsg_hint=file.metadata_.get("crs_epsg"))
    _process_surface(db, file, parsed)


def _process_xyz(db: Session, file: FileRecord) -> None:
    raw = get_bytes(file.storage_key)
    parsed = parse_xyz(raw, crs_epsg_hint=file.metadata_.get("crs_epsg"))
    _process_surface(db, file, parsed)


def _process_shapefile(db: Session, file: FileRecord) -> None:
    raw = get_bytes(file.storage_key)
    parsed = parse_shapefile(raw, file.filename)
    name = os.path.splitext(file.filename)[0] or "vector layer"
    layer = MapLayer(
        project_id=file.project_id, source_file_id=file.id, name=name, layer_kind="vector",
        crs_epsg=parsed.crs_epsg, bounds_geojson=parsed.bounds_geojson, geojson=parsed.geojson,
    )
    db.add(layer)
    db.flush()
    file.metadata_ = {**file.metadata_, "map_layer_id": str(layer.id)}


def _process_mesh(db: Session, file: FileRecord) -> None:
    raw = get_bytes(file.storage_key)
    parsed = parse_mesh(raw, file.source_format)
    file.metadata_ = {
        **file.metadata_,
        "vertex_count": parsed.vertex_count,
        "face_count": parsed.face_count,
        "bounds_min": parsed.bounds_min,
        "bounds_max": parsed.bounds_max,
    }


def dispatch_parse(file_id: uuid.UUID, db: Session) -> None:
    file = db.get(FileRecord, file_id)
    if file is None:
        return

    file.status = "processing"
    db.commit()

    try:
        fmt = file.source_format
        if fmt in _UNSUPPORTED_MESSAGES:
            file.status = "error"
            file.error_message = _UNSUPPORTED_MESSAGES[fmt]
        elif fmt == "las":
            _process_las(db, file)
            file.status = "ready"
        elif fmt == "csv_trajectory":
            _process_csv_trajectory(db, file)
            file.status = "ready"
        elif fmt == "grdecl":
            _process_grdecl(db, file)
            file.status = "ready"
        elif fmt == "geotiff":
            _process_geotiff(db, file)
            file.status = "ready"
        elif fmt == "surfer_grd":
            _process_surfer_grd(db, file)
            file.status = "ready"
        elif fmt == "xyz":
            _process_xyz(db, file)
            file.status = "ready"
        elif fmt == "shp":
            _process_shapefile(db, file)
            file.status = "ready"
        elif fmt in ("obj", "ply", "stl"):
            _process_mesh(db, file)
            file.status = "ready"
        else:
            file.status = "error"
            file.error_message = f"Unsupported source_format '{fmt}'"

        file.processed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:  # noqa: BLE001 -- must never crash the worker
        logger.exception("Parse job failed for file %s", file_id)
        db.rollback()
        file = db.get(FileRecord, file_id)
        if file is not None:
            file.status = "error"
            file.error_message = str(exc)[:2000]
            file.processed_at = datetime.now(timezone.utc)
            db.commit()
