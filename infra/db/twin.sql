-- Construction digital twin — scene assets (BIM / point clouds / reality meshes),
-- BIM element index, annotations and project documents (ПД/РД).
-- Applied after schema.sql (docker-entrypoint-initdb.d/02-twin.sql). Idempotent,
-- so it can also be run by hand against an existing database.

-- Project CRS as free text so local systems (МСК, custom PROJ strings) work,
-- not only EPSG codes. NULL -> fall back to default_crs_epsg.
ALTER TABLE projects ADD COLUMN IF NOT EXISTS crs TEXT;

-- One renderable 3D layer, always served as an OGC 3D Tiles tileset.
--
-- georef.mode = 'absolute' -> tiles are written in ECEF (exact per-vertex transform
--                             from the source CRS); the client applies no transform.
-- georef.mode = 'anchor' -> tiles are written in a local east/north/up metric frame;
--                           the client places it with longitude/latitude/height/
--                           heading/scale from `georef`.
CREATE TABLE IF NOT EXISTS scene_assets (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  source_file_id UUID REFERENCES files(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,                 -- bim | point_cloud | mesh
  storage_prefix TEXT NOT NULL,       -- object-store prefix holding tileset.json + tiles
  georef JSONB NOT NULL DEFAULT '{}',
  stats JSONB NOT NULL DEFAULT '{}',  -- element_count / point_count / tile_count / bounds ...
  -- Versioning: uploads that replace an earlier model share version_group.
  version_group UUID NOT NULL DEFAULT uuid_generate_v4(),
  version INTEGER NOT NULL DEFAULT 1,
  captured_at DATE,                   -- survey / issue date, drives the timeline
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_scene_assets_project ON scene_assets(project_id);
CREATE INDEX IF NOT EXISTS idx_scene_assets_group ON scene_assets(version_group);

-- Per-element index of a BIM asset: what a click on a 3D feature resolves to.
CREATE TABLE IF NOT EXISTS bim_elements (
  id BIGSERIAL PRIMARY KEY,
  asset_id UUID NOT NULL REFERENCES scene_assets(id) ON DELETE CASCADE,
  global_id TEXT NOT NULL,
  ifc_type TEXT NOT NULL,
  name TEXT,
  storey TEXT,
  properties JSONB NOT NULL DEFAULT '{}',
  geometry_hash TEXT,                 -- for version comparison
  properties_hash TEXT,
  bbox JSONB,                         -- {min:[x,y,z], max:[x,y,z]} in the asset's tile frame
  UNIQUE (asset_id, global_id)
);
ALTER TABLE bim_elements ADD COLUMN IF NOT EXISTS bbox JSONB;
CREATE INDEX IF NOT EXISTS idx_bim_elements_type ON bim_elements(asset_id, ifc_type);

CREATE TABLE IF NOT EXISTS annotations (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  asset_id UUID REFERENCES scene_assets(id) ON DELETE SET NULL,
  element_global_id TEXT,             -- binds the note to a structural element
  longitude DOUBLE PRECISION NOT NULL,
  latitude DOUBLE PRECISION NOT NULL,
  height DOUBLE PRECISION NOT NULL,
  title TEXT NOT NULL,
  body TEXT,
  color TEXT NOT NULL DEFAULT '#F5A623',
  created_by UUID REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_annotations_project ON annotations(project_id);

CREATE TABLE IF NOT EXISTS documents (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  doc_type TEXT NOT NULL DEFAULT 'other', -- pd (проектная) | rd (рабочая) | other
  code TEXT,                              -- шифр / марка комплекта
  description TEXT,
  created_by UUID REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_documents_project ON documents(project_id);

CREATE TABLE IF NOT EXISTS document_versions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  version INTEGER NOT NULL,
  filename TEXT NOT NULL,
  storage_key TEXT NOT NULL,
  size_bytes BIGINT NOT NULL,
  comment TEXT,
  uploaded_by UUID REFERENCES users(id),
  uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (document_id, version)
);

-- Links a document to a BIM element (or a whole asset when element_global_id is NULL).
CREATE TABLE IF NOT EXISTS document_links (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  asset_id UUID NOT NULL REFERENCES scene_assets(id) ON DELETE CASCADE,
  element_global_id TEXT,
  UNIQUE (document_id, asset_id, element_global_id)
);
CREATE INDEX IF NOT EXISTS idx_document_links_element ON document_links(asset_id, element_global_id);

-- Autodesk Platform Services (ACC / BIM 360) integration.
-- 3-legged OAuth tokens per user (encrypted at rest with a key derived from JWT_SECRET).
CREATE TABLE IF NOT EXISTS autodesk_connections (
  user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  access_token TEXT NOT NULL,
  refresh_token TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- An ACC/BIM 360 item imported into a project; with a webhook it is
-- re-imported as a new model version whenever a new version is published.
CREATE TABLE IF NOT EXISTS autodesk_links (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id UUID REFERENCES users(id) ON DELETE SET NULL,  -- whose token re-imports use
  hub_id TEXT,
  aps_project_id TEXT NOT NULL,
  item_id TEXT NOT NULL,
  folder_id TEXT,
  name TEXT NOT NULL,
  last_version_id TEXT,
  version_group UUID,                -- scene_assets.version_group the imports land in
  hook_id TEXT,
  options JSONB NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'pending', -- pending | translating | ready | error
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_autodesk_links_item ON autodesk_links(item_id);
CREATE INDEX IF NOT EXISTS idx_autodesk_links_project ON autodesk_links(project_id);

-- Server-side analyses: deviation maps (scan vs BIM), ICP alignment, ...
CREATE TABLE IF NOT EXISTS analyses (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,                       -- deviation | alignment
  params JSONB NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'pending',   -- pending | running | ready | error
  error_message TEXT,
  result JSONB NOT NULL DEFAULT '{}',
  result_asset_id UUID REFERENCES scene_assets(id) ON DELETE SET NULL,
  created_by UUID REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_analyses_project ON analyses(project_id);

-- Замечания и предписания (issue tracking) with photo evidence and history.
CREATE TABLE IF NOT EXISTS issues (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  number INTEGER NOT NULL,                       -- sequential per project
  kind TEXT NOT NULL DEFAULT 'remark',           -- remark (замечание) | prescription (предписание)
  title TEXT NOT NULL,
  description TEXT,
  status TEXT NOT NULL DEFAULT 'open',           -- open | in_progress | review | closed
  priority TEXT NOT NULL DEFAULT 'normal',       -- low | normal | high | critical
  assignee_id UUID REFERENCES users(id) ON DELETE SET NULL,
  due_date DATE,
  longitude DOUBLE PRECISION,
  latitude DOUBLE PRECISION,
  height DOUBLE PRECISION,
  asset_id UUID REFERENCES scene_assets(id) ON DELETE SET NULL,
  element_global_id TEXT,
  created_by UUID REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  closed_at TIMESTAMPTZ,
  UNIQUE (project_id, number)
);
CREATE INDEX IF NOT EXISTS idx_issues_project ON issues(project_id, status);

CREATE TABLE IF NOT EXISTS issue_attachments (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  issue_id UUID NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
  filename TEXT NOT NULL,
  storage_key TEXT NOT NULL,
  content_type TEXT,
  size_bytes BIGINT NOT NULL,
  longitude DOUBLE PRECISION,                    -- from photo EXIF GPS, if present
  latitude DOUBLE PRECISION,
  taken_at TIMESTAMPTZ,
  uploaded_by UUID REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- History: creation, status / assignee / field changes, comments, photos.
CREATE TABLE IF NOT EXISTS issue_events (
  id BIGSERIAL PRIMARY KEY,
  issue_id UUID NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
  user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  kind TEXT NOT NULL,                            -- created | status | assigned | updated | comment | attachment
  data JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_issue_events_issue ON issue_events(issue_id);
