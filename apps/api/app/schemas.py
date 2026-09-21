from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

UserRole = Literal["admin", "geologist", "viewer"]
ProjectRole = Literal["owner", "editor", "viewer"]
FileStatus = Literal["uploaded", "processing", "ready", "error"]
WellType = Literal["producer", "injector", "observation", "exploration"]
MarkerType = Literal["KOP", "RESERVOIR_ENTRY", "LANDING", "TD", "CUSTOM"]
FileCategory = Literal[
    "well_log", "well_trajectory", "grid", "surface", "map_raster", "map_vector", "mesh"
]


# ---------- Auth ----------


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None
    organization_name: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class User(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str | None
    role: UserRole
    organization_id: uuid.UUID


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: User


class AddMemberRequest(BaseModel):
    email: EmailStr
    role: ProjectRole = "viewer"


# ---------- Projects ----------


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    default_crs_epsg: int = 4326


class Project(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    default_crs_epsg: int
    created_at: datetime


# ---------- Files ----------


class FileRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    project_id: uuid.UUID
    filename: str
    source_format: str
    category: str
    size_bytes: int
    status: FileStatus
    error_message: str | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_", serialization_alias="metadata")
    uploaded_at: datetime


# ---------- Wells ----------


class WellSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    well_type: WellType
    surface_x: float | None
    surface_y: float | None
    total_depth: float | None


class WellDetail(WellSummary):
    kb_elevation: float | None
    crs_epsg: int
    project_id: uuid.UUID


class TrajectoryPoint(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seq: int
    md: float
    inclination: float | None
    azimuth: float | None
    tvd: float
    x: float
    y: float
    z: float


class WellMarker(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    marker_type: MarkerType
    label: str | None
    md: float
    tvd: float | None
    x: float | None
    y: float | None
    z: float | None


class LogCurveSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    curve_name: str
    unit: str | None
    min_value: float
    max_value: float
    sample_count: int


# ---------- Grids ----------


class GridSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    nx: int
    ny: int
    nz: int
    active_cell_count: int


class GridPropertySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    unit: str | None
    min_value: float
    max_value: float


class GridBounds(BaseModel):
    minX: float
    minY: float
    minZ: float
    maxX: float
    maxY: float
    maxZ: float


class GridDetail(GridSummary):
    bounds: GridBounds
    crs_epsg: int
    properties: list[GridPropertySummary]


class SampleRequest(BaseModel):
    x: float
    y: float
    z: float
    property: str


class SampleResponse(BaseModel):
    value: float | None
    i: int
    j: int
    k: int
    interpolation: Literal["trilinear", "nearest"]


# ---------- Surfaces ----------


class SurfaceKind(BaseModel):
    pass


class SurfaceSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    surface_kind: Literal["top", "base", "custom"]
    min_z: float | None
    max_z: float | None


class SurfaceDetail(SurfaceSummary):
    cols: int | None
    rows: int | None
    origin_x: float | None
    origin_y: float | None
    cell_size_x: float | None
    cell_size_y: float | None
    crs_epsg: int


# ---------- Map layers ----------


class MapLayerSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    layer_kind: Literal["raster", "vector"]
    bounds_geojson: Any


class MapLayerVectorDetail(MapLayerSummary):
    geojson: Any


class MapLayerRasterDetail(MapLayerSummary):
    image_url: str


# ---------- Formations ----------


class FormationCreate(BaseModel):
    name: str
    description: str | None = None
    color: str = "#4C9AFF"
    top_surface_id: uuid.UUID | None = None
    base_surface_id: uuid.UUID | None = None


class Formation(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    color: str
    top_surface_id: uuid.UUID | None
    base_surface_id: uuid.UUID | None
