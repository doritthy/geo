# Subsurface 3D Workspace

A full-stack platform for uploading, visualizing and analyzing 3D geological
models, structural maps and well data — corner-point grids (GRDECL), well
logs/trajectories (LAS/CSV), structural surfaces (GeoTIFF/Surfer .grd), and
GIS vector/raster layers (Shapefile/GeoTIFF), rendered in an interactive
Three.js 3D viewer alongside a Leaflet-based 2D/GIS mode.

This is a real, running client-server application with authentication, a
Postgres+PostGIS database, S3-compatible object storage, and actual file
parsers — not a static mockup. See `docs/LIMITATIONS.md` for the handful of
professional-format/engineering simplifications made to keep the scope
tractable (RESQML/DXF, exact corner-point hex rendering vs. instanced boxes,
LOD strategy, etc.), and `docs/API_CONTRACT.md` for the full API/DB contract
both halves of the app were built against.

## Architecture

```
apps/web   Next.js 14 (App Router, TypeScript) + Tailwind + react-three-fiber/Three.js + react-leaflet
apps/api   FastAPI (Python) — auth, projects, file ingestion, geoscience parsers
infra/db   PostgreSQL + PostGIS schema (infra/db/schema.sql)
           MinIO (S3-compatible) object storage for raw uploads + processed binary buffers
docs/      API_CONTRACT.md (binding API/DB/binary-format spec), LIMITATIONS.md
```

- **Auth**: JWT bearer tokens, bcrypt password hashing.
- **Multi-tenancy / RBAC**: every project belongs to an organization; org
  roles (`admin`/`geologist`/`viewer`) and per-project roles
  (`owner`/`editor`/`viewer`) gate access. Cross-tenant access returns 404,
  never 403 (avoids leaking existence).
- **Ingestion**: drag-and-drop upload → stored raw in MinIO → background
  parse job → structured rows in Postgres + processed binary buffers
  (float32/uint32) back in MinIO for the viewer to fetch directly.
- **3D rendering at scale**: grid cells are rendered as a single
  `THREE.InstancedMesh` (one box instance per active cell) rather than
  per-cell meshes, with server-side LOD subsampling — this is what makes
  multi-million-cell volumes tractable in WebGL. See `docs/LIMITATIONS.md`
  for the exact tradeoff vs. true hexahedral corner-point geometry.

## Running it

### With Docker (recommended)

```bash
docker compose up --build
```

- Frontend: http://localhost:3000
- API + interactive docs: http://localhost:8000/docs
- MinIO console: http://localhost:9001 (subsurface / subsurface123)
- Postgres: localhost:5432 (subsurface / subsurface)

`infra/db/schema.sql` is applied automatically on first Postgres start.

### Standalone (without Docker)

See `apps/api/README.md` and `apps/web/README.md` for running each side
directly against a local Postgres+PostGIS and an S3-compatible endpoint.

## What's implemented and verified

- Register/login, project CRUD, project membership/roles — verified with a
  live end-to-end run: cross-org access correctly returns 404, unauthenticated
  requests return 401.
- File upload → background parsing → status polling, for LAS, GRDECL
  (including full COORD/ZCORN corner-point pillar decoding, not just the
  regular-grid fallback), GeoTIFF, Shapefile, CSV well trajectories
  (minimum-curvature MD/Incl/Azim → TVD/X/Y/Z), OBJ/PLY/STL, Surfer .grd, XYZ.
  Verified live: a LAS upload produces a queryable well + log curve whose
  binary sample data decodes correctly; a GRDECL upload produces a grid whose
  binary cell/property buffers and trilinear point-sample all decode/compute
  correctly.
- 3D viewer: instanced grid rendering with 4 colormaps, threshold filtering,
  Z-exaggeration, perspective/orthographic toggle, camera presets, X/Y/Z
  cross-section clipping, well trajectories with role coloring and
  KOP/Reservoir-Entry/Landing/TD markers, point inspection via raycast +
  server-side trilinear sampling.
- 2D/GIS mode: Leaflet map with OSM/satellite base layers, well markers,
  vector/raster overlay layers.
- Backend: 19 automated tests passing against a real Postgres+PostGIS
  database and a real S3-compatible HTTP server. Frontend: `npm run build`
  passes with zero TypeScript errors.
- RESQML and DXF/DWG uploads are accepted and stored but intentionally not
  parsed (see `docs/LIMITATIONS.md`) — they're flagged with a clear error
  rather than silently failing or being rejected outright.

## Repo layout

```
apps/api/          FastAPI backend (see apps/api/README.md)
apps/web/           Next.js frontend (see apps/web/README.md)
infra/db/schema.sql PostgreSQL + PostGIS schema
docker-compose.yml   Full local stack: postgres, minio, api, web
docs/API_CONTRACT.md Binding API/DB/binary-format contract
docs/LIMITATIONS.md  Documented scope simplifications
```
