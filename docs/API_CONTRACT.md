# Subsurface 3D Workspace — API & Data Contract

This is the binding contract between `apps/api` (FastAPI backend) and `apps/web`
(Next.js frontend). Both were built against this document — if either side needs
to deviate, update this file in the same change.

Base URL: `NEXT_PUBLIC_API_URL` (frontend) / served by the API at `/api/*`.
All JSON endpoints return `application/json`. Auth uses a JWT bearer token
(`Authorization: Bearer <token>`) obtained from `/api/auth/login`.

## Roles

- **User role** (org-wide, `users.role`): `admin`, `geologist`, `viewer`.
- **Project role** (`project_members.role`): `owner`, `editor`, `viewer`.
- Effective permission on a project = max(org role admin override, project role).
  `admin` can do anything in their organization. `owner`/`editor` can upload
  files and edit project metadata. `viewer` (project or org role) is read-only.
- Every resource is scoped by `project_id`, and every project by `organization_id`
  — this is the multi-tenancy boundary. The API must reject any request for a
  project/file/well/grid/surface that does not belong to the caller's
  organization (or where the caller is not a project member), with 404 (not 403,
  to avoid leaking existence).

## Auth

- `POST /api/auth/register` `{email, password, full_name, organization_name}`
  → creates a new organization + first user as `admin`. Returns `{access_token, token_type, user}`.
- `POST /api/auth/login` `{email, password}` → `{access_token, token_type, user}`
- `GET /api/auth/me` → current `User`
- `POST /api/projects/{project_id}/members` `{email, role}` (owner/admin only) → adds an existing user of the same org to the project.

```ts
interface User { id: string; email: string; full_name: string | null; role: 'admin'|'geologist'|'viewer'; organization_id: string }
```

## Projects

- `GET /api/projects` → `Project[]` (projects the user is a member of)
- `POST /api/projects` `{name, description?, default_crs_epsg?}` → `Project`
- `GET /api/projects/{id}` → `Project`
- `DELETE /api/projects/{id}` (owner/admin only)

```ts
interface Project { id: string; name: string; description: string|null; default_crs_epsg: number; created_at: string }
```

## Files (ingestion)

- `POST /api/projects/{id}/files` — `multipart/form-data` with fields `file`, `category`
  (`well_log`|`well_trajectory`|`grid`|`surface`|`map_raster`|`map_vector`|`mesh`),
  optional `crs_epsg` (int, EPSG code of the source data, e.g. 32639 for
  WGS84/UTM39N) and optional `column_mapping` (JSON string, see below).
  `source_format` is inferred from the file extension server-side
  (`.las`→las, `.grdecl`/`.data`/`.inc`→grdecl, `.tif`/`.tiff`→geotiff,
  `.shp`(+ zip of sidecar files)→shp, `.csv`/`.txt`→csv_trajectory,
  `.obj`→obj, `.ply`→ply, `.stl`→stl, `.xyz`→xyz, `.grd`→surfer_grd).
  Returns the `FileRecord` immediately with `status=uploaded`, then parses
  it in a background task; poll `GET /api/files/{id}` for `status`
  (`processing`→`ready`|`error`).
  `column_mapping` (only used for `csv_trajectory`): `{"md":"MD","incl":"Incl","azim":"Azim","x":"X","y":"Y","tvd":"TVD"}` —
  lets the user map arbitrary CSV headers to the required fields.
- `GET /api/projects/{id}/files` → `FileRecord[]`
- `GET /api/files/{id}` → `FileRecord`
- `GET /api/files/{id}/download` → 307 redirect to a presigned object-store URL

```ts
interface FileRecord {
  id: string; project_id: string; filename: string; source_format: string; category: string;
  size_bytes: number; status: 'uploaded'|'processing'|'ready'|'error'; error_message: string|null;
  metadata: Record<string, unknown>; uploaded_at: string;
}
```

Unsupported/complex formats the backend detects but does not fully parse
(RESQML, DXF/DWG) are still accepted and stored (`status='error'`,
`error_message` explains the limitation) rather than rejected — see
`docs/LIMITATIONS.md`.

## Wells

- `GET /api/projects/{id}/wells` → `WellSummary[]`
- `GET /api/wells/{id}` → `WellDetail`
- `GET /api/wells/{id}/trajectory` → `TrajectoryPoint[]` (JSON; trajectories are small, typically <2000 points)
- `GET /api/wells/{id}/markers` → `WellMarker[]`
- `GET /api/wells/{id}/logs` → `LogCurveSummary[]`
- `GET /api/wells/{id}/logs/{log_id}/data` → **binary**, `application/octet-stream`:
  a flat `Float32Array` of interleaved `[depth0, value0, depth1, value1, ...]`,
  little-endian. `sample_count` (from the summary) tells the client how many
  pairs to expect (`buffer.byteLength === sample_count * 2 * 4`).

```ts
type WellType = 'producer'|'injector'|'observation'|'exploration';
interface WellSummary { id: string; name: string; well_type: WellType; surface_x: number; surface_y: number; total_depth: number|null }
interface WellDetail extends WellSummary { kb_elevation: number|null; crs_epsg: number; project_id: string }
interface TrajectoryPoint { seq: number; md: number; inclination: number|null; azimuth: number|null; tvd: number; x: number; y: number; z: number }
interface WellMarker { id: string; marker_type: 'KOP'|'RESERVOIR_ENTRY'|'LANDING'|'TD'|'CUSTOM'; label: string|null; md: number; tvd: number|null; x:number|null; y:number|null; z:number|null }
interface LogCurveSummary { id: string; curve_name: string; unit: string|null; min_value:number; max_value:number; sample_count:number }
```

## Grids (3D property grids)

Grids are rendered client-side as an **InstancedMesh of boxes**, one instance
per active cell (documented tradeoff vs. exact corner-point hexahedra — see
`docs/LIMITATIONS.md`). This is what makes 1–10M cell volumes tractable in
WebGL: a single draw call via `THREE.InstancedMesh` + `InstancedBufferAttribute`
for per-instance color, with an LOD query param that subsamples cells.

- `GET /api/projects/{id}/grids` → `GridSummary[]`
- `GET /api/grids/{id}` → `GridDetail` (includes `properties: GridPropertySummary[]`)
- `GET /api/grids/{id}/cells?lod=0` → **binary**, `application/octet-stream`.
  `lod` is an integer 0-3 (0=full detail, higher = server subsamples every
  Nth active cell, N = 4^lod). Layout (little-endian), all arrays length
  `cellCount` (given in the response header `X-Cell-Count`, and derivable
  from `Content-Length`):
  - `Float32Array[cellCount*3]` — instance centers `(x,y,z)`
  - `Float32Array[cellCount*3]` — instance sizes `(dx,dy,dz)`
  - `Uint32Array[cellCount]` — `cellId`, the index into property arrays returned by `/properties/{name}` **at the same `lod`** (property arrays are subsampled identically so indices line up)
- `GET /api/grids/{id}/properties/{name}?lod=0` → **binary** `Float32Array[cellCount]`, one value per cell, same order/subsampling as `/cells` at that `lod`.
- `POST /api/grids/{id}/sample` `{x, y, z, property}` → `{value: number|null, i:number, j:number, k:number, interpolation: "trilinear"|"nearest"}`
  — used for point-inspection; trilinearly interpolates across the structured
  `(i,j,k)` cell index using the 8 nearest cell centers when `(x,y,z)` falls
  inside the grid's bounding box, otherwise `nearest`.

```ts
interface GridSummary { id: string; name: string; nx:number; ny:number; nz:number; active_cell_count:number }
interface GridPropertySummary { name: string; unit: string|null; min_value:number; max_value:number }
interface GridDetail extends GridSummary {
  bounds: { minX:number;minY:number;minZ:number;maxX:number;maxY:number;maxZ:number };
  crs_epsg: number; properties: GridPropertySummary[];
}
```

## Surfaces (structural maps / GeoTIFF grids)

Rendered as a displaced `PlaneGeometry` (one vertex per raster cell).

- `GET /api/projects/{id}/surfaces` → `SurfaceSummary[]`
- `GET /api/surfaces/{id}` → `SurfaceDetail`
- `GET /api/surfaces/{id}/heights` → **binary** `Float32Array[rows*cols]`, row-major, `NaN` where `nodata`.

```ts
interface SurfaceSummary { id:string; name:string; surface_kind:'top'|'base'|'custom'; min_z:number; max_z:number }
interface SurfaceDetail extends SurfaceSummary {
  cols:number; rows:number; origin_x:number; origin_y:number; cell_size_x:number; cell_size_y:number; crs_epsg:number;
}
```

## Map layers (2D / GIS mode)

- `GET /api/projects/{id}/map-layers` → `MapLayerSummary[]`
- `GET /api/map-layers/{id}` → for `layer_kind='vector'`: `{..., geojson: FeatureCollection}`; for `'raster'`: `{..., image_url: string}` (presigned)

```ts
interface MapLayerSummary { id:string; name:string; layer_kind:'raster'|'vector'; bounds_geojson: unknown }
```

## Formations

- `GET /api/projects/{id}/formations` → `Formation[]`
- `POST /api/projects/{id}/formations` `{name, description?, color?, top_surface_id?, base_surface_id?}`

```ts
interface Formation { id:string; name:string; description:string|null; color:string; top_surface_id:string|null; base_surface_id:string|null }
```

## Errors

All errors: `{ "detail": string }` with standard HTTP status codes
(400 validation, 401 unauthenticated, 404 not found/not authorized, 422 body
validation from FastAPI, 500 unexpected).

## Environment variables (shared)

| Var | Used by | Meaning |
|---|---|---|
| `DATABASE_URL` | api | `postgresql://user:pass@host:5432/db` |
| `JWT_SECRET` | api | HMAC secret for access tokens |
| `JWT_EXPIRE_MINUTES` | api | default 1440 |
| `S3_ENDPOINT_URL` | api | MinIO endpoint, e.g. `http://minio:9000` |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | api | MinIO credentials |
| `S3_BUCKET` | api | default `subsurface-data` |
| `NEXT_PUBLIC_API_URL` | web | e.g. `http://localhost:8000` |
