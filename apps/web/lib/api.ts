// Typed fetch client for every endpoint in docs/API_CONTRACT.md.
// Attaches the JWT bearer token from lib/auth.ts to every request.

import { getToken, setToken, setStoredUser, clearAuth } from './auth';
import type {
  User,
  Project,
  FileRecord,
  FileCategory,
  ColumnMapping,
  WellSummary,
  WellDetail,
  TrajectoryPoint,
  WellMarker,
  LogCurveSummary,
  GridSummary,
  GridDetail,
  GridSampleResult,
  SurfaceSummary,
  SurfaceDetail,
  MapLayerSummary,
  MapLayerDetail,
  Formation,
} from './types';

function baseUrl(): string {
  return process.env.NEXT_PUBLIC_API_URL ?? '';
}

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  opts: { binary?: boolean; skipAuth?: boolean } = {}
): Promise<T> {
  const headers = new Headers(init.headers);
  if (!opts.skipAuth) {
    const token = getToken();
    if (token) headers.set('Authorization', `Bearer ${token}`);
  }
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const res = await fetch(`${baseUrl()}${path}`, { ...init, headers });

  if (res.status === 401) {
    clearAuth();
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body && typeof body.detail === 'string') detail = body.detail;
    } catch {
      /* ignore non-JSON error bodies */
    }
    throw new ApiError(res.status, detail);
  }

  if (opts.binary) {
    return (await res.arrayBuffer()) as unknown as T;
  }

  if (res.status === 204) {
    return undefined as unknown as T;
  }

  return (await res.json()) as T;
}

// Helper to read a binary response along with a header we care about
// (used for the grids/cells endpoint's X-Cell-Count).
async function requestBinaryWithHeaders(
  path: string,
  init: RequestInit = {}
): Promise<{ buffer: ArrayBuffer; headers: Headers }> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);

  const res = await fetch(`${baseUrl()}${path}`, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body && typeof body.detail === 'string') detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  const buffer = await res.arrayBuffer();
  return { buffer, headers: res.headers };
}

function qs(params: Record<string, string | number | undefined>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined) as [string, string | number][];
  if (entries.length === 0) return '';
  const sp = new URLSearchParams();
  for (const [k, v] of entries) sp.set(k, String(v));
  return `?${sp.toString()}`;
}

export const api = {
  // ---- Auth ----
  async register(input: {
    email: string;
    password: string;
    full_name: string;
    organization_name: string;
  }): Promise<{ access_token: string; token_type: string; user: User }> {
    const result = await request<{ access_token: string; token_type: string; user: User }>(
      '/api/auth/register',
      { method: 'POST', body: JSON.stringify(input) },
      { skipAuth: true }
    );
    setToken(result.access_token);
    setStoredUser(result.user);
    return result;
  },

  async login(input: {
    email: string;
    password: string;
  }): Promise<{ access_token: string; token_type: string; user: User }> {
    const result = await request<{ access_token: string; token_type: string; user: User }>(
      '/api/auth/login',
      { method: 'POST', body: JSON.stringify(input) },
      { skipAuth: true }
    );
    setToken(result.access_token);
    setStoredUser(result.user);
    return result;
  },

  async me(): Promise<User> {
    return request<User>('/api/auth/me');
  },

  async addProjectMember(projectId: string, input: { email: string; role: string }): Promise<void> {
    await request<void>(`/api/projects/${projectId}/members`, {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },

  // ---- Projects ----
  async listProjects(): Promise<Project[]> {
    return request<Project[]>('/api/projects');
  },

  async createProject(input: { name: string; description?: string; default_crs_epsg?: number }): Promise<Project> {
    return request<Project>('/api/projects', { method: 'POST', body: JSON.stringify(input) });
  },

  async getProject(id: string): Promise<Project> {
    return request<Project>(`/api/projects/${id}`);
  },

  async deleteProject(id: string): Promise<void> {
    await request<void>(`/api/projects/${id}`, { method: 'DELETE' });
  },

  // ---- Files ----
  async uploadFile(
    projectId: string,
    input: { file: File; category: FileCategory; crs_epsg?: number; column_mapping?: ColumnMapping }
  ): Promise<FileRecord> {
    const form = new FormData();
    form.set('file', input.file);
    form.set('category', input.category);
    if (input.crs_epsg !== undefined) form.set('crs_epsg', String(input.crs_epsg));
    if (input.column_mapping) form.set('column_mapping', JSON.stringify(input.column_mapping));
    return request<FileRecord>(`/api/projects/${projectId}/files`, { method: 'POST', body: form });
  },

  async listFiles(projectId: string): Promise<FileRecord[]> {
    return request<FileRecord[]>(`/api/projects/${projectId}/files`);
  },

  async getFile(id: string): Promise<FileRecord> {
    return request<FileRecord>(`/api/files/${id}`);
  },

  fileDownloadUrl(id: string): string {
    return `${baseUrl()}/api/files/${id}/download`;
  },

  // ---- Wells ----
  async listWells(projectId: string): Promise<WellSummary[]> {
    return request<WellSummary[]>(`/api/projects/${projectId}/wells`);
  },

  async getWell(id: string): Promise<WellDetail> {
    return request<WellDetail>(`/api/wells/${id}`);
  },

  async getWellTrajectory(id: string): Promise<TrajectoryPoint[]> {
    return request<TrajectoryPoint[]>(`/api/wells/${id}/trajectory`);
  },

  async getWellMarkers(id: string): Promise<WellMarker[]> {
    return request<WellMarker[]>(`/api/wells/${id}/markers`);
  },

  async getWellLogs(id: string): Promise<LogCurveSummary[]> {
    return request<LogCurveSummary[]>(`/api/wells/${id}/logs`);
  },

  async getWellLogData(wellId: string, logId: string): Promise<ArrayBuffer> {
    return request<ArrayBuffer>(`/api/wells/${wellId}/logs/${logId}/data`, {}, { binary: true });
  },

  // ---- Grids ----
  async listGrids(projectId: string): Promise<GridSummary[]> {
    return request<GridSummary[]>(`/api/projects/${projectId}/grids`);
  },

  async getGrid(id: string): Promise<GridDetail> {
    return request<GridDetail>(`/api/grids/${id}`);
  },

  async getGridCells(id: string, lod = 0): Promise<{ buffer: ArrayBuffer; cellCount?: number }> {
    const { buffer, headers } = await requestBinaryWithHeaders(`/api/grids/${id}/cells${qs({ lod })}`);
    const headerCount = headers.get('X-Cell-Count');
    return { buffer, cellCount: headerCount ? Number(headerCount) : undefined };
  },

  async getGridProperty(id: string, name: string, lod = 0): Promise<ArrayBuffer> {
    return request<ArrayBuffer>(
      `/api/grids/${id}/properties/${encodeURIComponent(name)}${qs({ lod })}`,
      {},
      { binary: true }
    );
  },

  async sampleGrid(
    id: string,
    input: { x: number; y: number; z: number; property: string }
  ): Promise<GridSampleResult> {
    return request<GridSampleResult>(`/api/grids/${id}/sample`, {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },

  // ---- Surfaces ----
  async listSurfaces(projectId: string): Promise<SurfaceSummary[]> {
    return request<SurfaceSummary[]>(`/api/projects/${projectId}/surfaces`);
  },

  async getSurface(id: string): Promise<SurfaceDetail> {
    return request<SurfaceDetail>(`/api/surfaces/${id}`);
  },

  async getSurfaceHeights(id: string): Promise<ArrayBuffer> {
    return request<ArrayBuffer>(`/api/surfaces/${id}/heights`, {}, { binary: true });
  },

  // ---- Map layers ----
  async listMapLayers(projectId: string): Promise<MapLayerSummary[]> {
    return request<MapLayerSummary[]>(`/api/projects/${projectId}/map-layers`);
  },

  async getMapLayer(id: string): Promise<MapLayerDetail> {
    return request<MapLayerDetail>(`/api/map-layers/${id}`);
  },

  // ---- Formations ----
  async listFormations(projectId: string): Promise<Formation[]> {
    return request<Formation[]>(`/api/projects/${projectId}/formations`);
  },

  async createFormation(
    projectId: string,
    input: { name: string; description?: string; color?: string; top_surface_id?: string; base_surface_id?: string }
  ): Promise<Formation> {
    return request<Formation>(`/api/projects/${projectId}/formations`, {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },
};
