import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Double,
    Enum,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# NOTE: geometry columns (wells.location) use PostGIS GEOMETRY type. We don't
# need to read/write it through the ORM for anything the contract requires
# (surface_x/surface_y/x/y/z columns carry the real coordinates the API
# returns), so it is intentionally left off the model rather than pulling in
# GeoAlchemy2 as an extra dependency. This keeps the ORM's other columns an
# exact match for schema.sql without touching that column.

user_role_enum = Enum("admin", "geologist", "viewer", name="user_role", create_type=False)
project_role_enum = Enum("owner", "editor", "viewer", name="project_role", create_type=False)
file_status_enum = Enum("uploaded", "processing", "ready", "error", name="file_status", create_type=False)
well_type_enum = Enum(
    "producer", "injector", "observation", "exploration", name="well_type", create_type=False
)
marker_type_enum = Enum(
    "KOP", "RESERVOIR_ENTRY", "LANDING", "TD", "CUSTOM", name="marker_type", create_type=False
)


def gen_uuid() -> uuid.UUID:
    return uuid.uuid4()


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    users: Mapped[list["User"]] = relationship(back_populates="organization")
    projects: Mapped[list["Project"]] = relationship(back_populates="organization")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(user_role_enum, nullable=False, default="viewer")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    organization: Mapped["Organization"] = relationship(back_populates="users")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_crs_epsg: Mapped[int] = mapped_column(Integer, nullable=False, default=4326)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    organization: Mapped["Organization"] = relationship(back_populates="projects")
    members: Mapped[list["ProjectMember"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class ProjectMember(Base):
    __tablename__ = "project_members"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(project_role_enum, nullable=False, default="viewer")

    project: Mapped["Project"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship()


class FileRecord(Base):
    __tablename__ = "files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    source_format: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(file_status_enum, nullable=False, default="uploaded")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(nullable=True)


class Well(Base):
    __tablename__ = "wells"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_file_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("files.id"), nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    well_type: Mapped[str] = mapped_column(well_type_enum, nullable=False, default="producer")
    surface_x: Mapped[float | None] = mapped_column(Double, nullable=True)
    surface_y: Mapped[float | None] = mapped_column(Double, nullable=True)
    kb_elevation: Mapped[float | None] = mapped_column(Double, nullable=True)
    total_depth: Mapped[float | None] = mapped_column(Double, nullable=True)
    crs_epsg: Mapped[int] = mapped_column(Integer, nullable=False, default=4326)
    # `location` PostGIS geometry column intentionally not mapped (see note above)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class WellTrajectoryPoint(Base):
    __tablename__ = "well_trajectory_points"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    well_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wells.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    md: Mapped[float] = mapped_column(Double, nullable=False)
    inclination: Mapped[float | None] = mapped_column(Double, nullable=True)
    azimuth: Mapped[float | None] = mapped_column(Double, nullable=True)
    tvd: Mapped[float] = mapped_column(Double, nullable=False)
    x: Mapped[float] = mapped_column(Double, nullable=False)
    y: Mapped[float] = mapped_column(Double, nullable=False)
    z: Mapped[float] = mapped_column(Double, nullable=False)

    __table_args__ = (UniqueConstraint("well_id", "seq"),)


class WellMarker(Base):
    __tablename__ = "well_markers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    well_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wells.id", ondelete="CASCADE"), nullable=False
    )
    marker_type: Mapped[str] = mapped_column(marker_type_enum, nullable=False)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    md: Mapped[float] = mapped_column(Double, nullable=False)
    tvd: Mapped[float | None] = mapped_column(Double, nullable=True)
    x: Mapped[float | None] = mapped_column(Double, nullable=True)
    y: Mapped[float | None] = mapped_column(Double, nullable=True)
    z: Mapped[float | None] = mapped_column(Double, nullable=True)


class WellLog(Base):
    __tablename__ = "well_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    well_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wells.id", ondelete="CASCADE"), nullable=False
    )
    source_file_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("files.id"), nullable=True)
    curve_name: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    min_value: Mapped[float | None] = mapped_column(Double, nullable=True)
    max_value: Mapped[float | None] = mapped_column(Double, nullable=True)
    sample_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Grid(Base):
    __tablename__ = "grids"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_file_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("files.id"), nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    nx: Mapped[int] = mapped_column(Integer, nullable=False)
    ny: Mapped[int] = mapped_column(Integer, nullable=False)
    nz: Mapped[int] = mapped_column(Integer, nullable=False)
    crs_epsg: Mapped[int] = mapped_column(Integer, nullable=False, default=4326)
    bounds_min_x: Mapped[float | None] = mapped_column(Double, nullable=True)
    bounds_min_y: Mapped[float | None] = mapped_column(Double, nullable=True)
    bounds_min_z: Mapped[float | None] = mapped_column(Double, nullable=True)
    bounds_max_x: Mapped[float | None] = mapped_column(Double, nullable=True)
    bounds_max_y: Mapped[float | None] = mapped_column(Double, nullable=True)
    bounds_max_z: Mapped[float | None] = mapped_column(Double, nullable=True)
    cell_geometry_storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    active_cell_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class GridProperty(Base):
    __tablename__ = "grid_properties"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    grid_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("grids.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    min_value: Mapped[float | None] = mapped_column(Double, nullable=True)
    max_value: Mapped[float | None] = mapped_column(Double, nullable=True)

    __table_args__ = (UniqueConstraint("grid_id", "name"),)


class Surface(Base):
    __tablename__ = "surfaces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_file_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("files.id"), nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    surface_kind: Mapped[str] = mapped_column(Text, nullable=False, default="top")
    crs_epsg: Mapped[int] = mapped_column(Integer, nullable=False, default=4326)
    cols: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    origin_x: Mapped[float | None] = mapped_column(Double, nullable=True)
    origin_y: Mapped[float | None] = mapped_column(Double, nullable=True)
    cell_size_x: Mapped[float | None] = mapped_column(Double, nullable=True)
    cell_size_y: Mapped[float | None] = mapped_column(Double, nullable=True)
    nodata_value: Mapped[float | None] = mapped_column(Double, nullable=True)
    heights_storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    min_z: Mapped[float | None] = mapped_column(Double, nullable=True)
    max_z: Mapped[float | None] = mapped_column(Double, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class MapLayer(Base):
    __tablename__ = "map_layers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_file_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("files.id"), nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    layer_kind: Mapped[str] = mapped_column(Text, nullable=False)
    crs_epsg: Mapped[int] = mapped_column(Integer, nullable=False, default=4326)
    bounds_geojson: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    geojson: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Formation(Base):
    __tablename__ = "formations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str] = mapped_column(Text, nullable=False, default="#4C9AFF")
    top_surface_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("surfaces.id"), nullable=True)
    base_surface_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("surfaces.id"), nullable=True)
