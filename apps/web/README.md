# Subsurface 3D Workspace — Frontend

Next.js 14 (App Router, TypeScript) frontend for the Subsurface 3D Workspace,
built against `docs/API_CONTRACT.md` and `docs/LIMITATIONS.md` at the repo
root. It is a real client against a real FastAPI backend (`apps/api`) — there
is no mock data baked into the shipped app.

## Running

### Local dev

```bash
npm install
cp .env.local.example .env.local   # set NEXT_PUBLIC_API_URL if not localhost:8000
npm run dev
```

Open http://localhost:3000. You'll need the API (and Postgres/MinIO) running
separately — see the repo root `docker-compose.yml`.

### Via docker-compose (full stack)

From the repo root:

```bash
docker compose up --build
```

This builds `apps/web` per its `Dockerfile`, sets `NEXT_PUBLIC_API_URL=http://localhost:8000`
(matching `docker-compose.yml`), and serves the app on port 3000.

### Build check

```bash
npm run build
```

## Environment variables

| Var | Meaning |
|---|---|
| `NEXT_PUBLIC_API_URL` | Base URL of the FastAPI backend, e.g. `http://localhost:8000`. All `lib/api.ts` calls are made against `${NEXT_PUBLIC_API_URL}/api/...`. |

## Architecture

- `lib/types.ts` — TypeScript interfaces copied verbatim from the ` ```ts ` blocks in `docs/API_CONTRACT.md`.
- `lib/api.ts` — typed fetch client for every contract endpoint (JSON and binary), attaching `Authorization: Bearer <token>`.
- `lib/binary.ts` — decoders for the three binary payloads (grid cells, grid properties, surface heights, well log data), matching the contract's little-endian `Float32Array`/`Uint32Array` layouts field-for-field.
- `lib/auth.ts` — token storage (see "Auth storage" below) and a `useCurrentUser()` hook.
- `lib/store.ts` — a single `zustand` store for workspace UI state (active project/grid/property, layer visibility, colormap, Z-exaggeration, clip planes, view mode, point-inspection result, etc).
- `lib/colormaps.ts` — Jet/Viridis/Rainbow/Spectral value→RGB lookup functions plus a CSS-gradient helper for the legend.
- `components/viewer3d/*` — the react-three-fiber 3D viewer: instanced-box grids, displaced-plane surfaces, tube-geometry well trajectories, cross-section clip planes, color legend, and click-to-inspect raycasting.
- `components/map2d/Map2D.tsx` — react-leaflet GIS mode (OSM / Esri World Imagery base layers, well markers, vector/raster map-layer overlays).
- `components/workspace/*` — the app chrome: top nav, layer-tree/formation/mini-map left panel, point-inspection right panel, and the drag-and-drop ingestion dialog.

## Auth storage

Per the task brief's explicit tradeoff, the JWT returned by
`/api/auth/login` / `/api/auth/register` is stored in **`localStorage`**
(`lib/auth.ts`), not an httpOnly cookie. The contract's auth endpoints return
a bearer token as JSON rather than setting a cookie, and frontend/backend run
on different ports in dev, so the natural integration is an
`Authorization: Bearer <token>` header attached by `lib/api.ts` to every
request. This is acceptable for this project's scope; a hardening pass would
move to an httpOnly cookie plus a small session/proxy endpoint to reduce XSS
exposure.

## What's fully working

- Register / login / logout, protected routing to `/projects`.
- Project list + create-project dialog; per-project workspace shell.
- Real file upload (drag-and-drop or file picker) with per-file category,
  optional source CRS, CSV column-mapping (with CSV header auto-detection),
  upload progress (via `XMLHttpRequest`), and status polling until
  `ready`/`error`.
- 3D viewer: instanced-box grid rendering from the exact binary layout in the
  contract, property coloring (4 colormaps), threshold filtering (hides
  instances outside a numeric range), LOD selector (`lod=0..3`), Z-exaggeration,
  camera presets (Top/North/South/East/West/Flip-Z), perspective/orthographic
  toggle, and click-to-inspect (raycast → cellId → local value, plus a live
  `POST /grids/{id}/sample` call for the exact trilinear value).
- Well trajectories as `TubeGeometry`, colored by well role, with
  KOP/Reservoir-Entry/Landing/TD markers as billboarded HTML labels, and (when
  a `GR` or other log curve is present) an offset colored line along the
  wellbore.
- Structural surfaces as a displaced mesh built from the row-major height
  buffer, holes left where the source data is `NaN`/nodata.
- Cross-section controls: independent X/Y/Z clip-plane sliders (with a
  "flip side" toggle) applied as real WebGL local clipping planes to every
  layer's material simultaneously.
- 2D GIS mode: react-leaflet map with an OSM/Esri World Imagery layer switch,
  well markers with popups, and vector (`GeoJSON`) / raster (`ImageOverlay`)
  map-layer overlays, plus a live lat/lon readout.
- Formation cards and CSV well-list export.

## What's simplified (and why)

- **PDF export** is the browser's native print dialog (`window.print()`),
  not a generated PDF file — flagged in the UI's tooltip. A "real" PDF
  export would need a client-side PDF library and dedicated print layout,
  which was deprioritized per the stated priority order.
- **"2D Map" view mode** is implemented as the same 3D viewer switched to a
  top-down orthographic camera (a true "structural map" read of the 3D
  scene), distinct from the full "GIS" mode's 2D react-leaflet map. The
  contract doesn't define a separate 2D-specific endpoint, so this was the
  most consistent reading of "3D / 2D-Map / GIS" as three view modes.
- **Well/map-layer geographic placement**: `WellSummary.surface_x/y` are in
  the *project's* CRS (e.g. UTM), not WGS84 lat/lon, and the contract has no
  generic reprojection endpoint. Without a projection library and a
  code↔definition lookup (out of contract scope), `Map2D`/`MiniMap` can only
  place wells correctly when their coordinates already look like lat/lon
  (small magnitude); otherwise they fall back to a neutral map center. Vector
  (`GeoJSON`) and raster (`image_url`) map layers are unaffected, since the
  backend already reprojects those to WGS84 per `docs/LIMITATIONS.md`.
- **Arbitrary cross-section cut**: only the axis-aligned X/Y/Z clip-plane
  sliders are implemented; `components/viewer3d/clipPlanes.ts` exports
  `buildArbitraryCutPlane(p1, p2, flipped)` for a line-defined vertical
  cutting plane, but it isn't yet wired to a "draw two points" interaction
  in the UI, per the priority order's suggested fallback.
- **Grid `cellId` semantics**: the contract states the `Uint32Array` cellId
  field is "the index into property arrays … at the same lod" while also
  stating the property array is "same order/subsampling as `/cells` at that
  lod" — i.e. positionally aligned. This frontend treats `cellId` as a
  stable per-cell identifier (shown in the inspector, e.g. for correlating
  clicks across LOD levels) and colors instance `k` from `property[k]`
  (direct positional indexing), consistent with the property endpoint's own
  description. If the backend instead means "index into the property array"
  literally (i.e. `property[cellId[k]]`), this is a one-line fix in
  `GridInstancedMesh.tsx`.
- Log-curve ribbons on well trajectories render as a colored polyline
  offset from the tube (not a full 3D ribbon mesh), and only the first
  `GR` curve (or the first curve if no `GR`) is shown, per the "optionally
  render a log curve" scope note.
- No dev seed/mock server is included; the app was validated via `npm run
  build` plus careful re-reading of the binary layouts, since the backend
  isn't available in this environment (see the contract-review notes above).
