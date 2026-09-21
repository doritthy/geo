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
