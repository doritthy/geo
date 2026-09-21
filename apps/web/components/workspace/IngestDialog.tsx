'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useWorkspaceStore } from '@/lib/store';
import { getToken } from '@/lib/auth';
import { api } from '@/lib/api';
import type { ColumnMapping, FileCategory, FileRecord } from '@/lib/types';

const CATEGORIES: { value: FileCategory; label: string; extensions: string }[] = [
  { value: 'well_trajectory', label: 'Well trajectory', extensions: '.csv, .txt' },
  { value: 'well_log', label: 'Well log (LAS)', extensions: '.las' },
  { value: 'grid', label: '3D grid (GRDECL)', extensions: '.grdecl, .data, .inc' },
  { value: 'surface', label: 'Surface (GeoTIFF / Surfer grid)', extensions: '.tif, .tiff, .grd' },
  { value: 'map_raster', label: 'Map raster', extensions: '.tif, .tiff' },
  { value: 'map_vector', label: 'Map vector (Shapefile)', extensions: '.shp (+ zip)' },
  { value: 'mesh', label: 'Mesh (OBJ / PLY / STL / XYZ)', extensions: '.obj, .ply, .stl, .xyz' },
];

const MAPPING_FIELDS: { key: keyof ColumnMapping; label: string }[] = [
  { key: 'md', label: 'MD' },
  { key: 'incl', label: 'Incl' },
  { key: 'azim', label: 'Azim' },
  { key: 'x', label: 'X' },
  { key: 'y', label: 'Y' },
  { key: 'tvd', label: 'TVD' },
];

function guessExtCategory(filename: string): FileCategory | null {
  const ext = filename.toLowerCase().split('.').pop() ?? '';
  if (['csv', 'txt'].includes(ext)) return 'well_trajectory';
  if (ext === 'las') return 'well_log';
  if (['grdecl', 'data', 'inc'].includes(ext)) return 'grid';
  if (['tif', 'tiff'].includes(ext)) return 'surface';
  if (ext === 'shp' || ext === 'zip') return 'map_vector';
  if (['obj', 'ply', 'stl', 'xyz', 'grd'].includes(ext)) return 'mesh';
  return null;
}

function readCsvHeaders(file: File): Promise<string[]> {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => {
      const text = String(reader.result ?? '');
      const firstLine = text.split(/\r?\n/, 1)[0] ?? '';
      const headers = firstLine.split(',').map((h) => h.trim().replace(/^"|"$/g, ''));
      resolve(headers.filter(Boolean));
    };
    reader.onerror = () => resolve([]);
    // Only need the header line; slicing keeps this cheap for large files.
    reader.readAsText(file.slice(0, 8192));
  });
}

interface UploadItem {
  id: string;
  file: File;
  category: FileCategory;
  crsEpsg: string;
  columnMapping: Partial<ColumnMapping>;
  csvHeaders: string[];
  progress: number;
  status: 'pending' | 'uploading' | 'processing' | 'ready' | 'error';
  errorMessage?: string;
  fileRecord?: FileRecord;
}

function uploadWithProgress(
  projectId: string,
  item: UploadItem,
  onProgress: (pct: number) => void
): Promise<FileRecord> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.set('file', item.file);
    form.set('category', item.category);
    if (item.crsEpsg) form.set('crs_epsg', item.crsEpsg);
    if (item.category === 'well_trajectory' && Object.keys(item.columnMapping).length === 6) {
      form.set('column_mapping', JSON.stringify(item.columnMapping));
    }

    const xhr = new XMLHttpRequest();
    const base = process.env.NEXT_PUBLIC_API_URL ?? '';
    xhr.open('POST', `${base}/api/projects/${projectId}/files`);
    const token = getToken();
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText));
        } catch {
          reject(new Error('Invalid server response'));
        }
      } else {
        let detail = xhr.statusText;
        try {
          detail = JSON.parse(xhr.responseText).detail ?? detail;
        } catch {
          /* ignore */
        }
        reject(new Error(detail));
      }
    };
    xhr.onerror = () => reject(new Error('Network error during upload'));
    xhr.send(form);
  });
}

export default function IngestDialog({ projectId, onIngested }: { projectId: string; onIngested: () => void }) {
  const open = useWorkspaceStore((s) => s.ingestDialogOpen);
  const setOpen = useWorkspaceStore((s) => s.setIngestDialogOpen);
  const [items, setItems] = useState<UploadItem[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const pollTimers = useRef<Record<string, ReturnType<typeof setInterval>>>({});

  useEffect(() => {
    return () => {
      Object.values(pollTimers.current).forEach(clearInterval);
    };
  }, []);

  const addFiles = useCallback(async (files: FileList | File[]) => {
    const newItems: UploadItem[] = [];
    for (const file of Array.from(files)) {
      const category = guessExtCategory(file.name) ?? 'well_trajectory';
      const csvHeaders = category === 'well_trajectory' ? await readCsvHeaders(file) : [];
      newItems.push({
        id: `${file.name}-${file.size}-${Date.now()}-${Math.random().toString(36).slice(2)}`,
        file,
        category,
        crsEpsg: '',
        columnMapping: {},
        csvHeaders,
        progress: 0,
        status: 'pending',
      });
    }
    setItems((prev) => [...prev, ...newItems]);
  }, []);

  function updateItem(id: string, patch: Partial<UploadItem>) {
    setItems((prev) => prev.map((it) => (it.id === id ? { ...it, ...patch } : it)));
  }

  function pollStatus(itemId: string, fileId: string) {
    const timer = setInterval(async () => {
      try {
        const record = await api.getFile(fileId);
        if (record.status === 'ready' || record.status === 'error') {
          clearInterval(timer);
          delete pollTimers.current[itemId];
          updateItem(itemId, {
            status: record.status,
            fileRecord: record,
            errorMessage: record.error_message ?? undefined,
          });
          if (record.status === 'ready') onIngested();
        } else {
          updateItem(itemId, { status: 'processing', fileRecord: record });
        }
      } catch (err) {
        clearInterval(timer);
        delete pollTimers.current[itemId];
        updateItem(itemId, { status: 'error', errorMessage: err instanceof Error ? err.message : 'Polling failed' });
      }
    }, 1500);
    pollTimers.current[itemId] = timer;
  }

  async function startUpload(item: UploadItem) {
    updateItem(item.id, { status: 'uploading', progress: 0, errorMessage: undefined });
    try {
      const record = await uploadWithProgress(projectId, item, (pct) => updateItem(item.id, { progress: pct }));
      updateItem(item.id, { status: 'processing', fileRecord: record, progress: 100 });
      pollStatus(item.id, record.id);
    } catch (err) {
      updateItem(item.id, { status: 'error', errorMessage: err instanceof Error ? err.message : 'Upload failed' });
    }
  }

  function close() {
    setOpen(false);
    setItems((prev) => prev.filter((it) => it.status === 'uploading' || it.status === 'processing'));
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
      <div className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-xl border border-bg-border bg-bg-panel shadow-2xl">
        <div className="flex items-center justify-between border-b border-bg-border px-5 py-3.5">
          <h2 className="text-base font-semibold">Upload data</h2>
          <button onClick={close} className="text-text-secondary hover:text-text-primary">
            ✕
          </button>
        </div>

        <div className="panel-scroll flex-1 overflow-y-auto px-5 py-4">
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
            }}
            onClick={() => inputRef.current?.click()}
            className={`cursor-pointer rounded-lg border-2 border-dashed p-8 text-center transition ${
              dragOver ? 'border-accent-teal bg-accent-teal/5' : 'border-bg-border hover:border-accent-teal/50'
            }`}
          >
            <p className="text-sm text-text-primary">Drag & drop files here, or click to browse</p>
            <p className="mt-1 text-xs text-text-muted">
              LAS well logs · CSV trajectories · GRDECL grids · GeoTIFF / Surfer surfaces · Shapefiles · OBJ/PLY/STL/XYZ meshes
            </p>
            <input
              ref={inputRef}
              type="file"
              multiple
              className="hidden"
              onChange={(e) => e.target.files && addFiles(e.target.files)}
            />
          </div>

          <div className="mt-4 space-y-3">
            {items.map((item) => (
              <div key={item.id} className="rounded-lg border border-bg-border bg-bg-panel2 p-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-text-primary">{item.file.name}</div>
                    <div className="text-[11px] text-text-muted">{(item.file.size / 1024).toFixed(1)} KB</div>
                  </div>
                  <StatusBadge item={item} />
                </div>

                {item.status === 'pending' && (
                  <div className="mt-3 space-y-2.5">
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="mb-1 block text-[11px] text-text-muted">Category</label>
                        <select
                          value={item.category}
                          onChange={(e) => updateItem(item.id, { category: e.target.value as FileCategory })}
                          className="w-full rounded-md border border-bg-border bg-bg-panel px-2 py-1.5 text-xs outline-none focus:border-accent-teal"
                        >
                          {CATEGORIES.map((c) => (
                            <option key={c.value} value={c.value}>
                              {c.label}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="mb-1 block text-[11px] text-text-muted">Source CRS (EPSG, optional)</label>
                        <input
                          type="number"
                          value={item.crsEpsg}
                          onChange={(e) => updateItem(item.id, { crsEpsg: e.target.value })}
                          placeholder="32639"
                          className="w-full rounded-md border border-bg-border bg-bg-panel px-2 py-1.5 text-xs outline-none focus:border-accent-teal"
                        />
                      </div>
                    </div>

                    {item.category === 'well_trajectory' && (
                      <div>
                        <label className="mb-1 block text-[11px] text-text-muted">
                          Column mapping {item.csvHeaders.length === 0 && '(no header row detected — type header names manually)'}
                        </label>
                        <div className="grid grid-cols-3 gap-2">
                          {MAPPING_FIELDS.map((f) => (
                            <div key={f.key}>
                              <label className="mb-0.5 block text-[10px] text-text-muted">{f.label}</label>
                              {item.csvHeaders.length > 0 ? (
                                <select
                                  value={item.columnMapping[f.key] ?? ''}
                                  onChange={(e) =>
                                    updateItem(item.id, { columnMapping: { ...item.columnMapping, [f.key]: e.target.value } })
                                  }
                                  className="w-full rounded-md border border-bg-border bg-bg-panel px-1.5 py-1 text-[11px] outline-none focus:border-accent-teal"
                                >
                                  <option value="">—</option>
                                  {item.csvHeaders.map((h) => (
                                    <option key={h} value={h}>
                                      {h}
                                    </option>
                                  ))}
                                </select>
                              ) : (
                                <input
                                  value={item.columnMapping[f.key] ?? ''}
                                  onChange={(e) =>
                                    updateItem(item.id, { columnMapping: { ...item.columnMapping, [f.key]: e.target.value } })
                                  }
                                  className="w-full rounded-md border border-bg-border bg-bg-panel px-1.5 py-1 text-[11px] outline-none focus:border-accent-teal"
                                />
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    <button
                      onClick={() => startUpload(item)}
                      className="w-full rounded-md bg-accent-teal px-3 py-1.5 text-xs font-semibold text-bg hover:bg-accent-teal/90"
                    >
                      Upload
                    </button>
                  </div>
                )}

                {item.status === 'uploading' && (
                  <div className="mt-2.5">
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-bg-border">
                      <div className="h-full bg-accent-teal transition-all" style={{ width: `${item.progress}%` }} />
                    </div>
                  </div>
                )}

                {item.status === 'error' && item.errorMessage && (
                  <p className="mt-2 text-xs text-red-300">{item.errorMessage}</p>
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="flex justify-end border-t border-bg-border px-5 py-3">
          <button onClick={close} className="rounded-md border border-bg-border px-4 py-1.5 text-sm text-text-secondary hover:text-text-primary">
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

function StatusBadge({ item }: { item: UploadItem }) {
  const map: Record<UploadItem['status'], { label: string; className: string }> = {
    pending: { label: 'Ready to upload', className: 'text-text-muted' },
    uploading: { label: `Uploading ${item.progress}%`, className: 'text-accent-blue' },
    processing: { label: 'Processing…', className: 'text-accent-amber' },
    ready: { label: 'Ready', className: 'text-accent-teal' },
    error: { label: 'Error', className: 'text-red-400' },
  };
  const s = map[item.status];
  return <span className={`shrink-0 text-[11px] font-medium ${s.className}`}>{s.label}</span>;
}
