'use client';

import { useEffect, useState } from 'react';
import { twinApi } from '@/lib/twin/api';
import { ApiError } from '@/lib/api';
import type { CrsInfo, TwinProject } from '@/lib/twin/types';
import { Button, ErrorBox, Field, Input, Select } from './ui';
import MembersSection from './MembersSection';

/** Project settings: name/description and the project CRS (EPSG / СК-42 /
 * custom PROJ string for МСК), used for coordinate readouts and as the
 * default CRS when uploading data. */
export default function SettingsPanel({ project, onSaved }: { project: TwinProject; onSaved: (p: TwinProject) => void }) {
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description ?? '');
  const [crs, setCrs] = useState(project.crs ?? '');
  const [presets, setPresets] = useState<{ value: string; label: string }[]>([]);
  const [info, setInfo] = useState<CrsInfo | null>(null);
  const [crsError, setCrsError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    twinApi.crsPresets().then(setPresets).catch(() => {});
  }, []);

  useEffect(() => {
    setInfo(null);
    setCrsError(null);
    if (!crs.trim()) return;
    const t = setTimeout(() => {
      twinApi
        .resolveCrs(crs.trim())
        .then(setInfo)
        .catch((err) => setCrsError(err instanceof ApiError ? err.detail : 'СК не распознана'));
    }, 400);
    return () => clearTimeout(t);
  }, [crs]);

  async function save() {
    setError(null);
    setSaved(false);
    try {
      const p = await twinApi.updateProject(project.id, { name, description: description || null, crs: crs.trim() || null });
      onSaved(p);
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось сохранить');
    }
  }

  return (
    <div className="space-y-3">
      <Field label="Название проекта">
        <Input value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="Описание">
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={2}
          className="w-full rounded-md border border-bg-border bg-bg-panel2 px-2.5 py-1.5 text-sm outline-none focus:border-accent-teal"
        />
      </Field>
      <Field label="Система координат проекта" hint="EPSG-код, PROJ-строка (для МСК) или WKT. Используется для отображения координат и по умолчанию при загрузке.">
        <Select value={presets.some((p) => p.value === crs) ? crs : ''} onChange={(e) => e.target.value && setCrs(e.target.value)}>
          <option value="">— выбрать из списка —</option>
          {presets.map((p) => (
            <option key={p.value} value={p.value}>{p.label} ({p.value})</option>
          ))}
        </Select>
        <textarea
          value={crs}
          onChange={(e) => setCrs(e.target.value)}
          rows={2}
          placeholder="EPSG:32642 или +proj=tmerc +lat_0=0 +lon_0=71.03 +k=1 +x_0=2300000 +y_0=-5300000 +ellps=krass +towgs84=… +units=m"
          className="mt-2 w-full rounded-md border border-bg-border bg-bg-panel2 px-2.5 py-1.5 font-mono text-xs outline-none focus:border-accent-teal"
        />
      </Field>
      {info && (
        <div className="rounded-md bg-bg-panel2/60 px-2.5 py-2 text-xs text-text-secondary">
          <div className="text-text-primary">{info.name}</div>
          {info.code && <div>{info.code}</div>}
          {info.area_of_use && <div>Область: {info.area_of_use}</div>}
        </div>
      )}
      {crsError && <ErrorBox>{crsError}</ErrorBox>}
      {error && <ErrorBox>{error}</ErrorBox>}
      <div className="flex items-center gap-3">
        <Button variant="primary" onClick={save} disabled={!!crsError}>Сохранить</Button>
        {saved && <span className="text-xs text-accent-teal">Сохранено</span>}
      </div>
      <MembersSection projectId={project.id} />
    </div>
  );
}
