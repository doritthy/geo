// TypeScript interfaces mirrored EXACTLY from the ```ts blocks in docs/API_CONTRACT.md.
// Do not add fields that aren't in the contract.

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  role: 'admin' | 'geologist' | 'viewer';
  organization_id: string;
}

export interface Project {
  id: string;
  name: string;
  description: string | null;
  default_crs_epsg: number;
  created_at: string;
}

export type FileCategory =
  | 'well_log'
  | 'well_trajectory'
  | 'grid'
  | 'surface'
  | 'map_raster'
  | 'map_vector'
  | 'mesh';

export type FileStatus = 'uploaded' | 'processing' | 'ready' | 'error';

export interface FileRecord {
  id: string;
  project_id: string;
  filename: string;
  source_format: string;
  category: string;
  size_bytes: number;
  status: FileStatus;
  error_message: string | null;
  metadata: Record<string, unknown>;
  uploaded_at: string;
}

export interface ColumnMapping {
  md: string;
  incl: string;
  azim: string;
  x: string;
  y: string;
  tvd: string;
}

export type WellType = 'producer' | 'injector' | 'observation' | 'exploration';

export interface WellSummary {
  id: string;
  name: string;
  well_type: WellType;
  surface_x: number;
  surface_y: number;
  total_depth: number | null;
}

export interface WellDetail extends WellSummary {
  kb_elevation: number | null;
  crs_epsg: number;
  project_id: string;
}

export interface TrajectoryPoint {
  seq: number;
  md: number;
  inclination: number | null;
  azimuth: number | null;
  tvd: number;
  x: number;
  y: number;
  z: number;
}

export type MarkerType = 'KOP' | 'RESERVOIR_ENTRY' | 'LANDING' | 'TD' | 'CUSTOM';

export interface WellMarker {
  id: string;
  marker_type: MarkerType;
  label: string | null;
  md: number;
  tvd: number | null;
  x: number | null;
  y: number | null;
  z: number | null;
}

export interface LogCurveSummary {
  id: string;
  curve_name: string;
  unit: string | null;
  min_value: number;
  max_value: number;
  sample_count: number;
}

export interface GridSummary {
  id: string;
  name: string;
  nx: number;
  ny: number;
  nz: number;
  active_cell_count: number;
}

export interface GridPropertySummary {
  name: string;
  unit: string | null;
  min_value: number;
  max_value: number;
}

export interface GridDetail extends GridSummary {
  bounds: { minX: number; minY: number; minZ: number; maxX: number; maxY: number; maxZ: number };
  crs_epsg: number;
  properties: GridPropertySummary[];
}

export interface GridSampleResult {
  value: number | null;
  i: number;
  j: number;
  k: number;
  interpolation: 'trilinear' | 'nearest';
}

export interface SurfaceSummary {
  id: string;
  name: string;
  surface_kind: 'top' | 'base' | 'custom';
  min_z: number;
  max_z: number;
}

export interface SurfaceDetail extends SurfaceSummary {
  cols: number;
  rows: number;
  origin_x: number;
  origin_y: number;
  cell_size_x: number;
  cell_size_y: number;
  crs_epsg: number;
}

export interface MapLayerSummary {
  id: string;
  name: string;
  layer_kind: 'raster' | 'vector';
  bounds_geojson: unknown;
}

export interface MapLayerVectorDetail extends MapLayerSummary {
  layer_kind: 'vector';
  geojson: GeoJSON.FeatureCollection;
}

export interface MapLayerRasterDetail extends MapLayerSummary {
  layer_kind: 'raster';
  image_url: string;
}

export type MapLayerDetail = MapLayerVectorDetail | MapLayerRasterDetail;

export interface Formation {
  id: string;
  name: string;
  description: string | null;
  color: string;
  top_surface_id: string | null;
  base_surface_id: string | null;
}

export interface ApiError {
  detail: string;
}
