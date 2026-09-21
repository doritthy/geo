# Known limitations / scope decisions

This is a real, running full-stack application, not a mockup — but a handful
of professional geo formats and engineering techniques are genuinely hard
(multi-month efforts in commercial software like Petrel/RESQML SDKs). Where
we simplified, it's documented here rather than silently faked.

- **RESQML**: files are accepted and stored, but not parsed into grids/wells
  (RESQML is a full EPC/XML+HDF5 standard; parsing it properly needs a
  dedicated SDK). Upload is rejected with a clear `error_message` pointing here.
- **DXF/DWG**: same — accepted/stored, not rendered. DWG in particular is a
  closed binary format requiring Teigha/ODA licensing.
- **Corner-point grids (GRDECL)**: cells are visualized as axis-aligned boxes
  positioned at each active cell's centroid with its bounding-box size,
  derived from `COORD`/`ZCORN` (or from `DX`/`DY`/`DZ`/`TOPS` for simplified
  regular grids). This is not the exact hexahedral cell geometry (corner-point
  cells can be non-orthogonal/faulted), but it is the standard, performant way
  to visualize large grids as an `InstancedMesh` and is accurate enough for
  property inspection and cross-sectioning. Exact skewed-hex rendering is a
  follow-up (would use a custom hex-shader instead of box instances).
- **Point-inspection trilinear interpolation** operates on the structured
  `(i,j,k)` cell-center lattice, not on the true deformed hexahedral cell —
  correct for regular/near-regular grids, an approximation near faults.
- **Background jobs**: file parsing runs as an in-process FastAPI
  `BackgroundTask`, not a separate Celery/RQ worker fleet. Real work happens
  (nothing is mocked), but it shares the API process's CPU. Swapping to
  Celery+Redis for horizontal scaling is a drop-in change (the parser
  functions are already pure `bytes -> ParsedResult`, called the same way
  from a Celery task).
- **LOD**: the `/cells?lod=` and `/properties/{name}?lod=` query params do
  server-side uniform subsampling by index stride, not an octree/quadtree.
  It's enough to keep multi-million-cell grids interactive, but a true
  octree with view-dependent LOD is future work.
- **Map raster tiling**: GeoTIFFs are re-encoded to a single PNG for the
  2D map (reprojected to WGS84) rather than a full XYZ tile pyramid, so
  very large rasters (>~4000px) will be downsampled for display.

## Backend implementation notes (apps/api)

A few small scope decisions made while implementing the backend, where the
contract didn't spell out the exact behavior:

- **Well identity across files**: a LAS (`well_log`) or CSV (`well_trajectory`)
  upload is matched to an existing `wells` row by `(project_id, name)` and
  merges into it (new logs/trajectory points attach to the same well)
  rather than always creating a new well. The name comes from the LAS
  `WELL` header field, or the CSV filename (without extension) when the
  source has no explicit well name. This lets a LAS file and a trajectory
  CSV for the same well combine into one `WellDetail`.
- **CSV trajectory with X/Y/TVD but no MD column**: since `well_trajectory_points.md`
  is `NOT NULL`, when a CSV supplies X/Y/TVD directly with no MD column
  (and no `column_mapping` entry for it), MD is approximated as `TVD`
  (i.e. a vertical-well assumption for that row) rather than rejecting the
  upload.
- **Admin project listing**: `GET /api/projects` returns all projects in the
  admin's organization for an org-`admin` user (not only ones they hold an
  explicit `project_members` row for), consistent with "admin can do
  anything in their organization" in `docs/API_CONTRACT.md`'s Roles
  section. Non-admin users still only see projects they're an explicit
  member of.
- **Grid `/sample` internal bookkeeping**: the public `/cells` and
  `/properties/{name}` binary layouts are exactly as specified in
  `docs/API_CONTRACT.md` (no extra fields). To support `/sample`'s
  structured `(i,j,k)` trilinear lookup without changing `schema.sql` or
  the public binary layout, the backend additionally writes a private,
  non-API-exposed binary blob per grid (deterministic object-store key
  derived from the grid id) holding each active cell's natural `(i,j,k)`
  index in the same order as `cells.bin`. This is purely a server-side
  implementation detail for `/sample` and isn't part of the contract.
- **Object store for backend tests**: genuine MinIO server binaries are no
  longer published for download upstream, so `apps/api/tests` run against a
  real S3-compatible HTTP server via `moto`'s server mode instead of real
  MinIO for local/sandboxed test runs (docker-compose is unchanged and
  still uses real MinIO for actual deployment). See `apps/api/README.md`.
