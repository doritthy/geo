// Types for the construction digital twin API (apps/api/app/schemas.py,
// "Construction digital twin" section).

export type AssetKind = 'bim' | 'point_cloud' | 'mesh';
import { tr } from '@/lib/i18n';
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
  pd: tr('ПД'),
  rd: tr('РД'),
  other: tr('Прочее'),
};

export const KIND_LABELS: Record<AssetKind, string> = {
  bim: tr('BIM-модели'),
  point_cloud: tr('Облака точек'),
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

export type IssueStatus = 'open' | 'in_progress' | 'review' | 'closed';
export type IssuePriority = 'low' | 'normal' | 'high' | 'critical';
export type IssueKind = 'remark' | 'prescription';

export interface Issue {
  id: string;
  number: number;
  kind: IssueKind;
  title: string;
  description: string | null;
  status: IssueStatus;
  priority: IssuePriority;
  assignee_id: string | null;
  assignee_name: string | null;
  due_date: string | null;
  overdue: boolean;
  longitude: number | null;
  latitude: number | null;
  height: number | null;
  asset_id: string | null;
  element_global_id: string | null;
  created_by: string | null;
  author_name: string | null;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
  attachments_count: number;
}

export interface IssueDetail extends Issue {
  attachments: {
    id: string;
    filename: string;
    content_type: string | null;
    size_bytes: number;
    longitude: number | null;
    latitude: number | null;
    taken_at: string | null;
    created_at: string;
  }[];
  events: { id: number; kind: string; data: Record<string, unknown>; user_name: string | null; created_at: string }[];
}

export interface Member {
  id: string;
  name: string;
  email: string;
  role: string;
}

export const ISSUE_STATUS: Record<IssueStatus, { label: string; color: string }> = {
  open: { label: tr('Открыто'), color: '#EF4444' },
  in_progress: { label: tr('В работе'), color: '#F59E0B' },
  review: { label: tr('На проверке'), color: '#3B82F6' },
  closed: { label: tr('Закрыто'), color: '#22C55E' },
};

export const ISSUE_NEXT: Record<IssueStatus, { to: IssueStatus; label: string }[]> = {
  open: [{ to: 'in_progress', label: tr('Взять в работу') }, { to: 'closed', label: tr('Закрыть') }],
  in_progress: [{ to: 'review', label: tr('На проверку') }, { to: 'open', label: tr('Вернуть') }],
  review: [{ to: 'closed', label: tr('Принять и закрыть') }, { to: 'in_progress', label: tr('Вернуть в работу') }],
  closed: [{ to: 'open', label: tr('Переоткрыть') }],
};

export const PRIORITY_LABELS: Record<IssuePriority, string> = {
  low: tr('Низкий'),
  normal: tr('Обычный'),
  high: tr('Высокий'),
  critical: tr('Критический'),
};

export type TaskStatus = 'done' | 'in_progress' | 'late' | 'not_started' | 'future';

export interface ScheduleTask {
  id: string;
  external_id: string | null;
  wbs: string | null;
  name: string;
  parent_id: string | null;
  is_summary: boolean;
  start_date: string;
  finish_date: string;
  percent_complete: number;
  planned_percent: number;
  cost: number | null;
  status: TaskStatus;
  element_count: number;
}

export interface ScheduleMetrics {
  status_date: string;
  weight?: 'cost' | 'duration';
  planned_percent?: number;
  actual_percent?: number;
  spi?: number | null;
  start?: string;
  finish?: string;
  forecast_finish?: string | null;
  delay_days?: number | null;
  late_tasks?: number;
  tasks?: number;
}

export const TASK_STATUS: Record<TaskStatus, { label: string; color: string }> = {
  done: { label: tr('Выполнено'), color: '#22C55E' },
  in_progress: { label: tr('В работе'), color: '#FACC15' },
  late: { label: tr('С отставанием'), color: '#EF4444' },
  not_started: { label: tr('Не начато'), color: '#94A3B8' },
  future: { label: tr('По плану позже'), color: 'rgba(148,163,184,0.18)' },
};
