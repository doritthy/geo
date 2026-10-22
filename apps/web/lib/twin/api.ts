// Client for the construction digital twin endpoints. Reuses the shared
// authenticated `request` from lib/api.ts.

import { ApiError, baseUrl, request } from '@/lib/api';
import { getToken } from '@/lib/auth';
import type { FileRecord, MapLayerDetail, MapLayerSummary } from '@/lib/types';
import type {
  Annotation,
  AnnotationCreate,
  BimElementDetail,
  CompareResult,
  CrsInfo,
  DocType,
  DocumentDetail,
  DocumentSummary,
  ElementPage,
  Analysis,
  Issue,
  IssueDetail,
  Member,
  SceneAsset,
  SceneAssetUpdate,
  TwinProject,
  TwinUploadCategory,
  TwinUploadOptions,
} from './types';

function qs(params: Record<string, string | number | undefined | null>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') sp.set(k, String(v));
  const s = sp.toString();
  return s ? `?${s}` : '';
}

export function absoluteUrl(path: string): string {
  return `${baseUrl()}${path}`;
}

export function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Upload with progress (fetch has no upload progress events). */
function xhrUpload<T>(path: string, form: FormData, onProgress?: (fraction: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', absoluteUrl(path));
    const token = getToken();
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* non-JSON */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as T);
      else {
        const detail = body && typeof (body as { detail?: unknown }).detail === 'string'
          ? (body as { detail: string }).detail
          : xhr.statusText || 'Ошибка загрузки';
        reject(new ApiError(xhr.status, detail));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, 'Сеть недоступна'));
    xhr.send(form);
  });
}

export const twinApi = {
  getProject: (id: string) => request<TwinProject>(`/api/projects/${id}`),
  updateProject: (id: string, body: { name?: string; description?: string | null; crs?: string | null }) =>
    request<TwinProject>(`/api/projects/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),

  listAssets: (projectId: string) => request<SceneAsset[]>(`/api/projects/${projectId}/assets`),
  updateAsset: (id: string, body: SceneAssetUpdate) =>
    request<SceneAsset>(`/api/assets/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteAsset: (id: string) => request<void>(`/api/assets/${id}`, { method: 'DELETE' }),

  listElements: (assetId: string, p: { q?: string; ifc_type?: string; storey?: string; limit?: number; offset?: number }) =>
    request<ElementPage>(`/api/assets/${assetId}/elements${qs(p)}`),
  getElement: (assetId: string, globalId: string) =>
    request<BimElementDetail>(`/api/assets/${assetId}/elements/${encodeURIComponent(globalId)}`),
  compare: (baseId: string, otherId: string) =>
    request<CompareResult>(`/api/assets/${baseId}/compare${qs({ other: otherId })}`),

  listAnnotations: (projectId: string) => request<Annotation[]>(`/api/projects/${projectId}/annotations`),
  createAnnotation: (projectId: string, body: AnnotationCreate) =>
    request<Annotation>(`/api/projects/${projectId}/annotations`, { method: 'POST', body: JSON.stringify(body) }),
  deleteAnnotation: (id: string) => request<void>(`/api/annotations/${id}`, { method: 'DELETE' }),

  listDocuments: (projectId: string, p: { q?: string; doc_type?: DocType; global_id?: string; asset_id?: string } = {}) =>
    request<DocumentSummary[]>(`/api/projects/${projectId}/documents${qs(p)}`),
  getDocument: (id: string) => request<DocumentDetail>(`/api/documents/${id}`),
  createDocument: (projectId: string, form: FormData) =>
    request<DocumentDetail>(`/api/projects/${projectId}/documents`, { method: 'POST', body: form }),
  addDocumentVersion: (id: string, form: FormData) =>
    request<DocumentDetail>(`/api/documents/${id}/versions`, { method: 'POST', body: form }),
  linkDocument: (id: string, assetId: string, globalId: string | null) =>
    request(`/api/documents/${id}/links`, {
      method: 'POST',
      body: JSON.stringify({ asset_id: assetId, element_global_id: globalId }),
    }),
  deleteDocument: (id: string) => request<void>(`/api/documents/${id}`, { method: 'DELETE' }),
  async downloadDocumentVersion(versionId: string, filename: string) {
    const res = await fetch(absoluteUrl(`/api/document-versions/${versionId}/download`), { headers: authHeaders() });
    if (!res.ok) throw new ApiError(res.status, 'Не удалось скачать файл');
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },

  uploadFile(
    projectId: string,
    file: File,
    category: TwinUploadCategory,
    options: TwinUploadOptions,
    onProgress?: (fraction: number) => void
  ) {
    const form = new FormData();
    form.append('category', category);
    form.append('options', JSON.stringify(options));
    form.append('file', file);
    return xhrUpload<FileRecord>(`/api/projects/${projectId}/files`, form, onProgress);
  },
  getFile: (id: string) => request<FileRecord>(`/api/files/${id}`),
  listFiles: (projectId: string) => request<FileRecord[]>(`/api/projects/${projectId}/files`),

  listMapLayers: (projectId: string) => request<MapLayerSummary[]>(`/api/projects/${projectId}/map-layers`),
  getMapLayer: (id: string) => request<MapLayerDetail>(`/api/map-layers/${id}`),
  async mapLayerImage(id: string): Promise<string> {
    const res = await fetch(absoluteUrl(`/api/map-layers/${id}/image`), { headers: authHeaders() });
    if (!res.ok) throw new ApiError(res.status, 'Растр недоступен');
    return URL.createObjectURL(await res.blob());
  },

  listAnalyses: (projectId: string) => request<Analysis[]>(`/api/projects/${projectId}/analyses`),
  getAnalysis: (id: string) => request<Analysis>(`/api/analyses/${id}`),
  runDeviation: (projectId: string, body: { cloud_asset_id: string; bim_asset_id: string; tolerances: number[]; max_distance: number }) =>
    request<Analysis>(`/api/projects/${projectId}/analyses/deviation`, { method: 'POST', body: JSON.stringify(body) }),
  runAlignment: (projectId: string, body: { cloud_asset_id: string; bim_asset_id: string; apply: boolean }) =>
    request<Analysis>(`/api/projects/${projectId}/analyses/alignment`, { method: 'POST', body: JSON.stringify(body) }),
  deleteAnalysis: (id: string) => request<void>(`/api/analyses/${id}`, { method: 'DELETE' }),
  async downloadReport(id: string) {
    const res = await fetch(absoluteUrl(`/api/analyses/${id}/report.pdf`), { headers: authHeaders() });
    if (!res.ok) throw new ApiError(res.status, 'Не удалось сформировать отчёт');
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement('a');
    a.href = url;
    a.download = 'Отчёт_отклонения.pdf';
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },

  members: (projectId: string) => request<Member[]>(`/api/projects/${projectId}/members`),
  listIssues: (projectId: string, p: { status?: string; assignee?: string; kind?: string; overdue?: boolean; q?: string } = {}) =>
    request<Issue[]>(`/api/projects/${projectId}/issues${qs({ ...p, overdue: p.overdue ? 'true' : undefined })}`),
  getIssue: (id: string) => request<IssueDetail>(`/api/issues/${id}`),
  createIssue: (projectId: string, body: Record<string, unknown>) =>
    request<IssueDetail>(`/api/projects/${projectId}/issues`, { method: 'POST', body: JSON.stringify(body) }),
  updateIssue: (id: string, body: Record<string, unknown>) =>
    request<IssueDetail>(`/api/issues/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  commentIssue: (id: string, text: string) =>
    request<IssueDetail>(`/api/issues/${id}/comments`, { method: 'POST', body: JSON.stringify({ text }) }),
  attachToIssue: (id: string, file: File) => {
    const form = new FormData();
    form.append('file', file);
    return request<IssueDetail>(`/api/issues/${id}/attachments`, { method: 'POST', body: form });
  },
  deleteIssue: (id: string) => request<void>(`/api/issues/${id}`, { method: 'DELETE' }),
  async attachmentUrl(id: string): Promise<string> {
    const res = await fetch(absoluteUrl(`/api/issue-attachments/${id}`), { headers: authHeaders() });
    if (!res.ok) throw new ApiError(res.status, 'Файл недоступен');
    return URL.createObjectURL(await res.blob());
  },
  async downloadIssues(projectId: string, format: 'xlsx' | 'pdf', p: Record<string, string | undefined>) {
    const res = await fetch(absoluteUrl(`/api/projects/${projectId}/issues/export.${format}${qs(p)}`), { headers: authHeaders() });
    if (!res.ok) throw new ApiError(res.status, 'Экспорт не удался');
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement('a');
    a.href = url;
    a.download = `Предписания.${format}`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },

  resolveCrs: (value: string) => request<CrsInfo>(`/api/crs/resolve${qs({ value })}`),
  crsPresets: () => request<{ value: string; label: string }[]>('/api/crs/presets'),
};
