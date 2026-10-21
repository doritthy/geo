'use client';

import { useMemo, useState, type FormEvent } from 'react';
import { twinApi } from '@/lib/twin/api';
import { ApiError } from '@/lib/api';
import { useTwinStore } from '@/lib/twin/store';
import type { TwinProject, TwinUploadCategory, TwinUploadOptions } from '@/lib/twin/types';
import { Button, ErrorBox, Field, Icons, Input, Select, formatBytes } from './ui';

const CATEGORIES: { key: TwinUploadCategory; label: string; accept: string; hint: string }[] = [
  { key: 'bim', label: 'BIM-модель', accept: '.ifc', hint: 'IFC 2x3 / IFC 4 / 4.3. RVT — экспорт в IFC или через интеграцию Autodesk.' },
  { key: 'point_cloud', label: 'Облако точек', accept: '.las,.laz,.e57,.xyz,.pts,.txt,.csv', hint: 'LAS / LAZ / E57 / XYZ. Строится LOD-октодерево для потокового просмотра.' },
  { key: 'reality_mesh', label: 'Reality Capture (mesh)', accept: '.obj,.ply,.glb,.gltf,.stl,.zip', hint: 'OBJ (ZIP с MTL и текстурами), PLY, GLB/glTF или ZIP с готовым 3D Tiles (Metashape / Pix4D / ContextCapture).' },
  { key: 'map_vector', label: 'ГИС / CAD вектор', accept: '.geojson,.json,.kml,.kmz,.dxf,.gpkg,.zip,.shp', hint: 'GeoJSON, KML/KMZ, DXF, GeoPackage, Shapefile (ZIP).' },
  { key: 'map_raster', label: 'Растр / ортофото', accept: '.tif,.tiff', hint: 'GeoTIFF (ортофотоплан, подложка).' },
];

export default function UploadDialog({
  project,
  onClose,
  onUploaded,
}: {
  project: TwinProject;
  onClose: () => void;
  onUploaded: () => void;
}) {
  const assets = useTwinStore((s) => s.assets);
  const [category, setCategory] = useState<TwinUploadCategory>('bim');
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState('');
  const [capturedAt, setCapturedAt] = useState('');
  const [georefMode, setGeorefMode] = useState<'auto' | 'absolute' | 'anchor'>('auto');
  const [crs, setCrs] = useState(project.crs ?? '');
  const [lat, setLat] = useState('');
  const [lon, setLon] = useState('');
  const [height, setHeight] = useState('');
  const [heading, setHeading] = useState('');
  const [heightOffset, setHeightOffset] = useState('');
  const [upAxis, setUpAxis] = useState<'' | 'y' | 'z'>('');
  const [replaces, setReplaces] = useState('');
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const cat = CATEGORIES.find((c) => c.key === category)!;
  const is3d = category === 'bim' || category === 'point_cloud' || category === 'reality_mesh';
  const bimGroups = useMemo(() => {
    const latest = new Map<string, (typeof assets)[number]>();
    for (const a of assets.filter((x) => x.kind === 'bim')) {
      const cur = latest.get(a.version_group);
      if (!cur || cur.version < a.version) latest.set(a.version_group, a);
    }
    return [...latest.values()];
  }, [assets]);

  const num = (v: string) => (v.trim() === '' ? undefined : Number(v.replace(',', '.')));

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setError(null);
    const options: TwinUploadOptions = {
      name: name || undefined,
      captured_at: capturedAt || undefined,
      crs: crs.trim() || undefined,
    };
    if (is3d) {
      options.georef_mode = georefMode;
      options.latitude = num(lat);
      options.longitude = num(lon);
      options.height = num(height);
      options.heading = num(heading);
      options.height_offset = num(heightOffset);
      if (upAxis) options.up_axis = upAxis;
      if (replaces) options.replaces_asset_id = replaces;
    }
    try {
      setProgress(0);
      await twinApi.uploadFile(project.id, file, category, options, setProgress);
      onUploaded();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Ошибка загрузки');
      setProgress(null);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 sm:items-center sm:px-4" onClick={onClose}>
      <form
        onSubmit={submit}
        onClick={(e) => e.stopPropagation()}
        className="max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-t-2xl border border-bg-border bg-bg-panel p-5 shadow-2xl sm:rounded-2xl"
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold">Загрузка данных</h2>
          <button type="button" onClick={onClose} className="text-text-secondary hover:text-text-primary">{Icons.close}</button>
        </div>

        <div className="mb-3 grid grid-cols-2 gap-1.5 sm:grid-cols-3">
          {CATEGORIES.map((c) => (
            <button
              type="button"
              key={c.key}
              onClick={() => { setCategory(c.key); setFile(null); }}
              className={`rounded-md border px-2 py-2 text-xs ${category === c.key ? 'border-accent-teal bg-accent-teal/10 text-text-primary' : 'border-bg-border text-text-secondary hover:text-text-primary'}`}
            >
              {c.label}
            </button>
          ))}
        </div>
        <p className="mb-3 text-[11px] text-text-muted">{cat.hint}</p>

        <label className="mb-3 flex cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed border-bg-border px-4 py-6 text-center hover:border-accent-teal/60">
          <span className="text-text-secondary">{Icons.upload}</span>
          <span className="mt-1 text-sm">{file ? file.name : 'Выберите файл'}</span>
          {file && <span className="text-[11px] text-text-muted">{formatBytes(file.size)}</span>}
          <input type="file" accept={cat.accept} className="hidden" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>

        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <Field label="Название слоя">
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={file?.name.replace(/\.[^.]+$/, '') ?? ''} />
            </Field>
            {is3d && (
              <Field label="Дата съёмки / выпуска">
                <Input type="date" value={capturedAt} onChange={(e) => setCapturedAt(e.target.value)} />
              </Field>
            )}
          </div>

          {category === 'bim' && bimGroups.length > 0 && (
            <Field label="Версионирование">
              <Select value={replaces} onChange={(e) => setReplaces(e.target.value)}>
                <option value="">Новая модель</option>
                {bimGroups.map((a) => (
                  <option key={a.id} value={a.id}>Новая версия: {a.name} (сейчас v{a.version})</option>
                ))}
              </Select>
            </Field>
          )}

          <Field label="Система координат исходных данных" hint={is3d ? 'Пусто — СК проекта или из файла (IfcMapConversion, LAS).' : 'Для DXF и файлов без .prj.'}>
            <Input value={crs} onChange={(e) => setCrs(e.target.value)} placeholder="EPSG:32642" />
          </Field>

          {is3d && (
            <details className="rounded-md border border-bg-border px-3 py-2">
              <summary className="cursor-pointer text-xs text-text-secondary">Привязка и параметры</summary>
              <div className="mt-3 space-y-3">
                <Field label="Режим привязки">
                  <Select value={georefMode} onChange={(e) => setGeorefMode(e.target.value as typeof georefMode)}>
                    <option value="auto">Авто (по файлу / СК)</option>
                    <option value="absolute">Координаты модели в указанной СК</option>
                    <option value="anchor">Локальная модель + точка привязки</option>
                  </Select>
                </Field>
                <div className="grid grid-cols-2 gap-2">
                  <Field label="Широта"><Input value={lat} onChange={(e) => setLat(e.target.value)} inputMode="decimal" placeholder="51.128" /></Field>
                  <Field label="Долгота"><Input value={lon} onChange={(e) => setLon(e.target.value)} inputMode="decimal" placeholder="71.430" /></Field>
                  <Field label="Высота, м"><Input value={height} onChange={(e) => setHeight(e.target.value)} inputMode="decimal" /></Field>
                  <Field label="Азимут оси Y, °"><Input value={heading} onChange={(e) => setHeading(e.target.value)} inputMode="decimal" /></Field>
                </div>
                <Field label="Поправка высоты (геоид), м" hint="Нормальные высоты → эллипсоидальные: добавляется к Z.">
                  <Input value={heightOffset} onChange={(e) => setHeightOffset(e.target.value)} inputMode="decimal" placeholder="0" />
                </Field>
                {category === 'reality_mesh' && (
                  <Field label="Вертикальная ось">
                    <Select value={upAxis} onChange={(e) => setUpAxis(e.target.value as typeof upAxis)}>
                      <option value="">Авто (glTF — Y, остальные — Z)</option>
                      <option value="z">Z вверх</option>
                      <option value="y">Y вверх</option>
                    </Select>
                  </Field>
                )}
              </div>
            </details>
          )}

          {progress !== null && (
            <div>
              <div className="h-1.5 overflow-hidden rounded bg-bg-panel2">
                <div className="h-full bg-accent-teal transition-all" style={{ width: `${Math.round(progress * 100)}%` }} />
              </div>
              <div className="mt-1 text-[11px] text-text-muted">
                {progress < 1 ? `Передача ${Math.round(progress * 100)}%` : 'Файл получен, запускается обработка…'}
              </div>
            </div>
          )}
          {error && <ErrorBox>{error}</ErrorBox>}
          <div className="flex justify-end gap-2 pt-1">
            <Button type="button" onClick={onClose}>Отмена</Button>
            <Button type="submit" variant="primary" disabled={!file || progress !== null}>Загрузить</Button>
          </div>
        </div>
      </form>
    </div>
  );
}
