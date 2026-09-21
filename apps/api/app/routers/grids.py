import uuid

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.binary import pack_float32_array, pack_grid_cells, unpack_float32_array, unpack_ijk
from app.db import get_db
from app.deps import get_project_scoped_or_404, project_viewer
from app.jobs import _ijk_storage_key
from app.models import Grid, GridProperty, Project, User
from app.schemas import GridBounds, GridDetail, GridPropertySummary, GridSummary, SampleRequest, SampleResponse
from app.security import get_current_user
from app.storage import get_bytes

router = APIRouter(tags=["grids"])


@router.get("/api/projects/{project_id}/grids", response_model=list[GridSummary])
def list_grids(project: Project = Depends(project_viewer), db: Session = Depends(get_db)) -> list[Grid]:
    return db.query(Grid).filter(Grid.project_id == project.id).order_by(Grid.name).all()


@router.get("/api/grids/{grid_id}", response_model=GridDetail)
def get_grid(grid_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    grid: Grid = get_project_scoped_or_404(Grid, grid_id, db, user)
    properties = db.query(GridProperty).filter(GridProperty.grid_id == grid.id).order_by(GridProperty.name).all()
    return {
        "id": grid.id,
        "name": grid.name,
        "nx": grid.nx,
        "ny": grid.ny,
        "nz": grid.nz,
        "active_cell_count": grid.active_cell_count or 0,
        "crs_epsg": grid.crs_epsg,
        "bounds": GridBounds(
            minX=grid.bounds_min_x or 0, minY=grid.bounds_min_y or 0, minZ=grid.bounds_min_z or 0,
            maxX=grid.bounds_max_x or 0, maxY=grid.bounds_max_y or 0, maxZ=grid.bounds_max_z or 0,
        ),
        "properties": [
            GridPropertySummary(name=p.name, unit=p.unit, min_value=p.min_value or 0, max_value=p.max_value or 0)
            for p in properties
        ],
    }


def _lod_stride(lod: int) -> int:
    return 4**lod


@router.get("/api/grids/{grid_id}/cells")
def get_cells(
    grid_id: uuid.UUID,
    lod: int = Query(0, ge=0, le=3),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    grid: Grid = get_project_scoped_or_404(Grid, grid_id, db, user)
    if not grid.cell_geometry_storage_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grid geometry not available")

    raw = get_bytes(grid.cell_geometry_storage_key)
    n = grid.active_cell_count or 0
    # Layout: Float32[n*3] centers, Float32[n*3] sizes, Uint32[n] cellId.
    centers = np.frombuffer(raw, dtype="<f4", count=n * 3, offset=0).reshape(n, 3)
    sizes = np.frombuffer(raw, dtype="<f4", count=n * 3, offset=n * 3 * 4).reshape(n, 3)

    stride = _lod_stride(lod)
    selected = np.arange(0, n, stride)
    new_centers = centers[selected]
    new_sizes = sizes[selected]
    new_ids = np.arange(len(selected), dtype=np.uint32)

    body = pack_grid_cells(new_centers, new_sizes, new_ids)
    return Response(
        content=body,
        media_type="application/octet-stream",
        headers={"X-Cell-Count": str(len(selected))},
    )


@router.get("/api/grids/{grid_id}/properties/{name}")
def get_property(
    grid_id: uuid.UUID,
    name: str,
    lod: int = Query(0, ge=0, le=3),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    grid: Grid = get_project_scoped_or_404(Grid, grid_id, db, user)
    prop = db.query(GridProperty).filter(GridProperty.grid_id == grid.id, GridProperty.name == name).first()
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")

    raw = get_bytes(prop.storage_key)
    values = unpack_float32_array(raw)
    stride = _lod_stride(lod)
    selected = values[::stride]
    return Response(content=pack_float32_array(selected), media_type="application/octet-stream")


@router.post("/api/grids/{grid_id}/sample", response_model=SampleResponse)
def sample_grid(
    grid_id: uuid.UUID,
    payload: SampleRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SampleResponse:
    grid: Grid = get_project_scoped_or_404(Grid, grid_id, db, user)
    prop = db.query(GridProperty).filter(GridProperty.grid_id == grid.id, GridProperty.name == payload.property).first()
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")
    if not grid.cell_geometry_storage_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grid geometry not available")

    n = grid.active_cell_count or 0
    raw_cells = get_bytes(grid.cell_geometry_storage_key)
    centers = np.frombuffer(raw_cells, dtype="<f4", count=n * 3, offset=0).reshape(n, 3).astype(np.float64)
    values = unpack_float32_array(get_bytes(prop.storage_key)).astype(np.float64)

    try:
        ijk_raw = get_bytes(_ijk_storage_key(grid.project_id, grid.id))
        ijk = unpack_ijk(ijk_raw)
    except Exception:
        ijk = None

    point = np.array([payload.x, payload.y, payload.z], dtype=np.float64)

    def nearest_result() -> SampleResponse:
        d2 = np.sum((centers - point) ** 2, axis=1)
        idx = int(np.argmin(d2))
        val = float(values[idx]) if np.isfinite(values[idx]) else None
        if ijk is not None:
            i, j, k = (int(v) for v in ijk[idx])
        else:
            i, j, k = 0, 0, 0
        return SampleResponse(value=val, i=i, j=j, k=k, interpolation="nearest")

    bounds = (grid.bounds_min_x, grid.bounds_min_y, grid.bounds_min_z, grid.bounds_max_x, grid.bounds_max_y, grid.bounds_max_z)
    if ijk is None or any(b is None for b in bounds) or n == 0:
        return nearest_result()

    inside = (
        bounds[0] <= payload.x <= bounds[3]
        and bounds[1] <= payload.y <= bounds[4]
        and bounds[2] <= payload.z <= bounds[5]
    )
    if not inside:
        return nearest_result()

    nx, ny, nz = grid.nx, grid.ny, grid.nz
    cx3 = np.full((nz, ny, nx), np.nan)
    cy3 = np.full((nz, ny, nx), np.nan)
    cz3 = np.full((nz, ny, nx), np.nan)
    v3 = np.full((nz, ny, nx), np.nan)
    ii, jj, kk = ijk[:, 0], ijk[:, 1], ijk[:, 2]
    cx3[kk, jj, ii] = centers[:, 0]
    cy3[kk, jj, ii] = centers[:, 1]
    cz3[kk, jj, ii] = centers[:, 2]
    v3[kk, jj, ii] = values

    x_axis = np.nanmean(cx3, axis=(0, 1))
    y_axis = np.nanmean(cy3, axis=(0, 2))
    z_axis = np.nanmean(cz3, axis=(1, 2))

    def locate(axis: np.ndarray, value: float) -> tuple[int, int, float]:
        m = len(axis)
        if m < 2:
            return 0, 0, 0.0
        ascending = axis[-1] >= axis[0]
        a = axis if ascending else axis[::-1]
        pos = int(np.searchsorted(a, value)) - 1
        pos = max(0, min(pos, m - 2))
        if not ascending:
            pos = m - 2 - pos
        lo, hi = pos, pos + 1
        denom = axis[hi] - axis[lo]
        t = 0.0 if denom == 0 else (value - axis[lo]) / denom
        t = float(np.clip(t, 0.0, 1.0))
        return lo, hi, t

    i0, i1, tx = locate(x_axis, payload.x)
    j0, j1, ty = locate(y_axis, payload.y)
    k0, k1, tz = locate(z_axis, payload.z)

    corners = [
        v3[k0, j0, i0], v3[k0, j0, i1], v3[k0, j1, i0], v3[k0, j1, i1],
        v3[k1, j0, i0], v3[k1, j0, i1], v3[k1, j1, i0], v3[k1, j1, i1],
    ]
    if any(np.isnan(c) for c in corners):
        return nearest_result()

    c00 = corners[0] * (1 - tx) + corners[1] * tx
    c01 = corners[2] * (1 - tx) + corners[3] * tx
    c10 = corners[4] * (1 - tx) + corners[5] * tx
    c11 = corners[6] * (1 - tx) + corners[7] * tx
    c0 = c00 * (1 - ty) + c01 * ty
    c1 = c10 * (1 - ty) + c11 * ty
    value = float(c0 * (1 - tz) + c1 * tz)

    i_res = i0 if tx < 0.5 else i1
    j_res = j0 if ty < 0.5 else j1
    k_res = k0 if tz < 0.5 else k1

    return SampleResponse(value=value, i=i_res, j=j_res, k=k_res, interpolation="trilinear")
