// Types for the construction digital twin API (apps/api/app/schemas.py,
// "Construction digital twin" section).

export type AssetKind = 'bim' | 'point_cloud' | 'mesh';
export type DocType = 'pd' | 'rd' | 'other';

export interface AnchorGeoref {
  mode: 'anchor';
  source: 'upload' | 'IfcSite' | 'unplaced' | 'manual';
  longitude: number;
  latitude: number;
  height: number;
  heading: number;
  scale: number;
  local_origin?: number[];
  alignment?: number[];
}

export interface AbsoluteGeoref {
  mode: 'absolute';
  source?: string;
  crs?: string;
  height_offset?: number;
  offset_enu?: number[] | null;
  alignment?: number[];
  alignment_source?: string;
}

export type Georef = AnchorGeoref | AbsoluteGeoref;

export interface SceneAsset {
  id: string;
  project_id: string;
  source_file_id: string | null;
  name: string;
  kind: AssetKind;
  georef: Georef;
  stats: {
    element_count?: number;
    point_count?: number;
    triangle_count?: number;
    tile_count?: number;
    ifc_types?: Record<string, number>;
    storeys?: Record<string, number>;
    ifc_schema?: string;
    center?: { longitude: number; latitude: number; height: number };
    textured?: boolean;
    [key: string]: unknown;
  };
  version_group: string;
  version: number;
  captured_at: string | null;
  created_at: string;
  tileset_url: string;
}

export interface SceneAssetUpdate {
  name?: string;
  captured_at?: string | null;
  longitude?: number;
  latitude?: number;
  height?: number;
  heading?: number;
  scale?: number;
  offset_enu?: number[] | null;
  reset_alignment?: boolean;
}

export interface BimElementSummary {
  global_id: string;
  ifc_type: string;
  name: string | null;
  storey: string | null;
}

export interface BimElementDetail extends BimElementSummary {
  properties: {
    psets?: Record<string, Record<string, unknown>>;
    [key: string]: unknown;
  };
  bbox: { min: number[]; max: number[] } | null;
  documents: DocumentSummary[];
  annotations: Annotation[];
}

export interface ElementPage {
  total: number;
  items: BimElementSummary[];
}

export interface CompareResult {
  base_asset_id: string;
  other_asset_id: string;
  counts: { added: number; removed: number; modified_geometry: number; modified_properties: number; unchanged: number };
  added: BimElementSummary[];
  removed: BimElementSummary[];
  modified_geometry: BimElementSummary[];
  modified_properties: BimElementSummary[];
  truncated: boolean;
}

export interface Annotation {
  id: string;
  project_id: string;
  asset_id: string | null;
  element_global_id: string | null;
  longitude: number;
  latitude: number;
  height: number;
  title: string;
  body: string | null;
  color: string;
  created_by: string | null;
  author_name: string | null;
  created_at: string;
}

export interface AnnotationCreate {
  longitude: number;
  latitude: number;
  height: number;
  title: string;
  body?: string;
  color?: string;
  asset_id?: string | null;
  element_global_id?: string | null;
}

export interface DocumentVersion {
  id: string;
  version: number;
  filename: string;
  size_bytes: number;
  comment: string | null;
  uploaded_at: string;
}

export interface DocumentSummary {
  id: string;
  title: string;
  doc_type: DocType;
  code: string | null;
  description: string | null;
  created_at: string;
  latest_version: DocumentVersion | null;
}

export interface DocumentDetail extends DocumentSummary {
  versions: DocumentVersion[];
  links: { id: string; asset_id: string; element_global_id: string | null }[];
}

export interface CrsInfo {
  input: string;
  name: string;
  code: string | null;
  proj4: string;
  is_projected: boolean;
  is_geographic: boolean;
  area_of_use: string | null;
}

export interface TwinProject {
  id: string;
  name: string;
  description: string | null;
  default_crs_epsg: number;
  crs: string | null;
  created_at: string;
}

export type TwinUploadCategory = 'bim' | 'point_cloud' | 'reality_mesh' | 'map_vector' | 'map_raster';

export interface TwinUploadOptions {
  name?: string;
  crs?: string;
  georef_mode?: 'auto' | 'absolute' | 'anchor';
  longitude?: number;
  latitude?: number;
  height?: number;
  heading?: number;
  height_offset?: number;
  up_axis?: 'y' | 'z';
  captured_at?: string;
  replaces_asset_id?: string;
}

export const DOC_TYPE_LABELS: Record<DocType, string> = {
  pd: 'ПД',
  rd: 'РД',
  other: 'Прочее',
};

export const KIND_LABELS: Record<AssetKind, string> = {
  bim: 'BIM-модели',
  point_cloud: 'Облака точек',
  mesh: 'Reality Capture',
};

export interface DeviationElement {
  global_id: string;
  ifc_type: string;
  name: string;
  points: number;
  mean: number;
  mean_abs: number;
  rms: number;
  max_abs: number;
  p95_abs: number;
  out_of_tolerance: number;
  longitude: number;
  latitude: number;
  height: number;
}

export interface Analysis {
  id: string;
  kind: 'deviation' | 'alignment';
  status: 'pending' | 'running' | 'ready' | 'error';
  params: { cloud_asset_id: string; bim_asset_id: string; tolerances?: number[]; max_distance?: number };
  error_message: string | null;
  result: {
    tolerances?: number[];
    histogram?: {
      bins: { label: string; color: string; count: number }[];
      related_points: number;
      unrelated_points: number;
      within_tolerance: number;
      mean: number | null;
      rms: number | null;
      p95_abs: number | null;
    };
    elements?: DeviationElement[];
    elements_total?: number;
    points_used?: number;
    points_total?: number;
    rmse_before?: number;
    rmse_after?: number;
    yaw_deg?: number;
    translation_enu?: number[];
    match_ratio?: number;
    cloud?: { id: string; name: string };
    bim?: { id: string; name: string; version: number };
  };
  result_asset_id: string | null;
  created_at: string;
  finished_at: string | null;
}
