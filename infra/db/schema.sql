-- Subsurface 3D Workspace — PostgreSQL + PostGIS schema
-- Applied automatically on first Postgres container start (mounted into /docker-entrypoint-initdb.d)

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TYPE user_role AS ENUM ('admin', 'geologist', 'viewer');
CREATE TYPE project_role AS ENUM ('owner', 'editor', 'viewer');
CREATE TYPE file_status AS ENUM ('uploaded', 'processing', 'ready', 'error');
CREATE TYPE well_type AS ENUM ('producer', 'injector', 'observation', 'exploration');
CREATE TYPE marker_type AS ENUM ('KOP', 'RESERVOIR_ENTRY', 'LANDING', 'TD', 'CUSTOM');

-- Multi-tenancy root: every user and project belongs to exactly one organization.
CREATE TABLE organizations (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  full_name TEXT,
  role user_role NOT NULL DEFAULT 'viewer', -- org-wide role (RBAC)
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE projects (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  default_crs_epsg INTEGER NOT NULL DEFAULT 4326,
  created_by UUID REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Per-project ACL layered on top of org role -> enables project isolation between tenants.
CREATE TABLE project_members (
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role project_role NOT NULL DEFAULT 'viewer',
  PRIMARY KEY (project_id, user_id)
);

CREATE TABLE files (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  filename TEXT NOT NULL,
  source_format TEXT NOT NULL, -- las | grdecl | geotiff | shp | csv_trajectory | obj | ply | stl | xyz | surfer_grd
  category TEXT NOT NULL,      -- well_log | well_trajectory | grid | surface | map_raster | map_vector | mesh
  storage_key TEXT NOT NULL,   -- object key of the RAW upload in the object store
  size_bytes BIGINT NOT NULL,
  status file_status NOT NULL DEFAULT 'uploaded',
  error_message TEXT,
  metadata JSONB NOT NULL DEFAULT '{}',
  uploaded_by UUID REFERENCES users(id),
  uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  processed_at TIMESTAMPTZ
);
CREATE INDEX idx_files_project ON files(project_id);

CREATE TABLE wells (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  source_file_id UUID REFERENCES files(id),
  name TEXT NOT NULL,
  well_type well_type NOT NULL DEFAULT 'producer',
  surface_x DOUBLE PRECISION,
  surface_y DOUBLE PRECISION,
  kb_elevation DOUBLE PRECISION,
  total_depth DOUBLE PRECISION,
  crs_epsg INTEGER NOT NULL DEFAULT 4326,
  location GEOMETRY(PointZ, 4326), -- reprojected to WGS84 for map display
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_wells_project ON wells(project_id);
CREATE INDEX idx_wells_location ON wells USING GIST(location);

CREATE TABLE well_trajectory_points (
  id BIGSERIAL PRIMARY KEY,
  well_id UUID NOT NULL REFERENCES wells(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL,
  md DOUBLE PRECISION NOT NULL,
  inclination DOUBLE PRECISION,
  azimuth DOUBLE PRECISION,
  tvd DOUBLE PRECISION NOT NULL,
  x DOUBLE PRECISION NOT NULL,
  y DOUBLE PRECISION NOT NULL,
  z DOUBLE PRECISION NOT NULL, -- absolute elevation (KB - TVD)
  UNIQUE(well_id, seq)
);

CREATE TABLE well_markers (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  well_id UUID NOT NULL REFERENCES wells(id) ON DELETE CASCADE,
  marker_type marker_type NOT NULL,
  label TEXT,
  md DOUBLE PRECISION NOT NULL,
  tvd DOUBLE PRECISION,
  x DOUBLE PRECISION,
  y DOUBLE PRECISION,
  z DOUBLE PRECISION
);

CREATE TABLE well_logs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  well_id UUID NOT NULL REFERENCES wells(id) ON DELETE CASCADE,
  source_file_id UUID REFERENCES files(id),
  curve_name TEXT NOT NULL, -- GR, RES, NPHI, RHOB, SW, ...
  unit TEXT,
  storage_key TEXT NOT NULL, -- binary interleaved [depth0,value0,depth1,value1,...] float32, see docs/API_CONTRACT.md
  min_value DOUBLE PRECISION,
  max_value DOUBLE PRECISION,
  sample_count INTEGER,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE grids (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  source_file_id UUID REFERENCES files(id),
  name TEXT NOT NULL,
  nx INTEGER NOT NULL,
  ny INTEGER NOT NULL,
  nz INTEGER NOT NULL,
  crs_epsg INTEGER NOT NULL DEFAULT 4326,
  bounds_min_x DOUBLE PRECISION, bounds_min_y DOUBLE PRECISION, bounds_min_z DOUBLE PRECISION,
  bounds_max_x DOUBLE PRECISION, bounds_max_y DOUBLE PRECISION, bounds_max_z DOUBLE PRECISION,
  cell_geometry_storage_key TEXT, -- binary cell centers+sizes+ijk, see docs/API_CONTRACT.md
  active_cell_count INTEGER,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_grids_project ON grids(project_id);

CREATE TABLE grid_properties (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  grid_id UUID NOT NULL REFERENCES grids(id) ON DELETE CASCADE,
  name TEXT NOT NULL, -- SO, SW, PORO, PERMX, PERMY, PERMZ, NTG, THICKNESS, ...
  unit TEXT,
  storage_key TEXT NOT NULL, -- float32 array, one value per active cell, same order as grid.cell_geometry_storage_key
  min_value DOUBLE PRECISION,
  max_value DOUBLE PRECISION,
  UNIQUE(grid_id, name)
);

CREATE TABLE surfaces (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  source_file_id UUID REFERENCES files(id),
  name TEXT NOT NULL,
  surface_kind TEXT NOT NULL DEFAULT 'top', -- top | base | custom
  crs_epsg INTEGER NOT NULL DEFAULT 4326,
  cols INTEGER, rows INTEGER,
  origin_x DOUBLE PRECISION, origin_y DOUBLE PRECISION,
  cell_size_x DOUBLE PRECISION, cell_size_y DOUBLE PRECISION,
  nodata_value DOUBLE PRECISION,
  heights_storage_key TEXT, -- float32 row-major raster of Z values
  min_z DOUBLE PRECISION, max_z DOUBLE PRECISION,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_surfaces_project ON surfaces(project_id);

CREATE TABLE map_layers (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  source_file_id UUID REFERENCES files(id),
  name TEXT NOT NULL,
  layer_kind TEXT NOT NULL, -- raster | vector
  crs_epsg INTEGER NOT NULL DEFAULT 4326,
  bounds_geojson JSONB,
  storage_key TEXT, -- for rasters: cloud-optimized PNG/JPEG rendered from source, served via presigned URL
  geojson JSONB,     -- for vector layers (shapefile -> GeoJSON, reprojected to WGS84)
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_maplayers_project ON map_layers(project_id);

CREATE TABLE formations (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  color TEXT NOT NULL DEFAULT '#4C9AFF',
  top_surface_id UUID REFERENCES surfaces(id),
  base_surface_id UUID REFERENCES surfaces(id)
);
CREATE INDEX idx_formations_project ON formations(project_id);
