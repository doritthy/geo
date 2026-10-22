from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

UserRole = Literal["admin", "geologist", "viewer"]
ProjectRole = Literal["owner", "editor", "viewer"]
FileStatus = Literal["uploaded", "processing", "ready", "error"]
WellType = Literal["producer", "injector", "observation", "exploration"]
MarkerType = Literal["KOP", "RESERVOIR_ENTRY", "LANDING", "TD", "CUSTOM"]
FileCategory = Literal[
    "well_log", "well_trajectory", "grid", "surface", "map_raster", "map_vector", "mesh",
    # construction digital twin
    "bim", "point_cloud", "reality_mesh",
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
    crs: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    crs: str | None = None


class Project(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    default_crs_epsg: int
    crs: str | None = None
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
    # XYZ pyramid (absent for layers imported before tiling existed).
    tiles_url: str | None = None  # template with {z}/{x}/{y}
    min_zoom: int | None = None
    max_zoom: int | None = None


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


# ---------- Construction digital twin ----------

AssetKind = Literal["bim", "point_cloud", "mesh"]
DocType = Literal["pd", "rd", "other"]


class SceneAsset(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    source_file_id: uuid.UUID | None
    name: str
    kind: AssetKind
    georef: dict[str, Any]
    stats: dict[str, Any]
    version_group: uuid.UUID
    version: int
    captured_at: date | None
    created_at: datetime
    tileset_url: str


class SceneAssetUpdate(BaseModel):
    name: str | None = None
    captured_at: date | None = None
    # Anchor placement (local models) / fine alignment offset for absolute ones.
    longitude: float | None = None
    latitude: float | None = None
    height: float | None = None
    heading: float | None = None
    scale: float | None = Field(default=None, gt=0)
    offset_enu: list[float] | None = Field(default=None, min_length=3, max_length=3)
    reset_alignment: bool = False


class BimElementSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    global_id: str
    ifc_type: str
    name: str | None
    storey: str | None


class BimElementDetail(BimElementSummary):
    properties: dict[str, Any]
    bbox: dict[str, Any] | None = None
    documents: list["DocumentSummary"] = []
    annotations: list["Annotation"] = []


class ElementPage(BaseModel):
    total: int
    items: list[BimElementSummary]


class CompareResult(BaseModel):
    base_asset_id: uuid.UUID
    other_asset_id: uuid.UUID
    counts: dict[str, int]
    added: list[BimElementSummary]
    removed: list[BimElementSummary]
    modified_geometry: list[BimElementSummary]
    modified_properties: list[BimElementSummary]
    truncated: bool


class AnnotationCreate(BaseModel):
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    height: float
    title: str = Field(min_length=1, max_length=200)
    body: str | None = None
    color: str = "#F5A623"
    asset_id: uuid.UUID | None = None
    element_global_id: str | None = None


class AnnotationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = None
    color: str | None = None


class Annotation(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    asset_id: uuid.UUID | None
    element_global_id: str | None
    longitude: float
    latitude: float
    height: float
    title: str
    body: str | None
    color: str
    created_by: uuid.UUID | None
    author_name: str | None = None
    created_at: datetime


class DocumentVersion(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: int
    filename: str
    size_bytes: int
    comment: str | None
    uploaded_at: datetime
    text_status: str = "pending"  # pending | ready | none (no text layer) | error


class DocumentLink(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    asset_id: uuid.UUID
    element_global_id: str | None


class DocumentLinkCreate(BaseModel):
    asset_id: uuid.UUID
    element_global_id: str | None = None


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    doc_type: DocType
    code: str | None
    description: str | None
    created_at: datetime
    latest_version: DocumentVersion | None = None
    # Fragment of the matching text when searching; matches are wrapped in
    # \u0001 … \u0002 so the client can highlight without trusting HTML.
    snippet: str | None = None


class DocumentDetail(DocumentSummary):
    versions: list[DocumentVersion]
    links: list[DocumentLink]


class CrsInfo(BaseModel):
    input: str
    name: str
    code: str | None
    proj4: str
    is_projected: bool
    is_geographic: bool
    area_of_use: str | None


BimElementDetail.model_rebuild()
