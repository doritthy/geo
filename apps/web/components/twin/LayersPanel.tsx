'use client';

import { useState } from 'react';
import { useTwinStore } from '@/lib/twin/store';
import { twinApi } from '@/lib/twin/api';
import { ApiError } from '@/lib/api';
import { KIND_LABELS, type AssetKind, type SceneAsset } from '@/lib/twin/types';
import type { FileRecord, MapLayerSummary } from '@/lib/types';
import { Button, Empty, ErrorBox, Icons, Input, formatBytes, formatNumber } from './ui';
import { tr, locale } from '@/lib/i18n';

function PlacementEditor({ asset, onSaved }: { asset: SceneAsset; onSaved: () => void }) {
  const g = asset.georef;
  const [lon, setLon] = useState(g.mode === 'anchor' ? String(g.longitude) : '');
  const [lat, setLat] = useState(g.mode === 'anchor' ? String(g.latitude) : '');
  const [h, setH] = useState(g.mode === 'anchor' ? String(g.height) : '');
  const [heading, setHeading] = useState(g.mode === 'anchor' ? String(g.heading) : '');
  const off = g.mode === 'absolute' ? g.offset_enu ?? [0, 0, 0] : [0, 0, 0];
  const [e, setE] = useState(String(off[0]));
  const [n, setN] = useState(String(off[1]));
  const [u, setU] = useState(String(off[2]));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      if (g.mode === 'anchor') {
        await twinApi.updateAsset(asset.id, {
          longitude: Number(lon), latitude: Number(lat), height: Number(h), heading: Number(heading),
        });
      } else {
        await twinApi.updateAsset(asset.id, { offset_enu: [Number(e), Number(n), Number(u)] });
      }
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : tr('Не удалось сохранить'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-2 rounded-md bg-bg/60 p-2">
      {g.mode === 'anchor' ? (
        <>
          <p className="text-[11px] text-text-muted">
            Локальная модель — задайте точку привязки (WGS 84), высоту и азимут оси +Y.
            {g.source === 'unplaced' && tr(' Модель ещё не размещена.')}
          </p>
          <div className="grid grid-cols-2 gap-2">
            <Input value={lat} onChange={(ev) => setLat(ev.target.value)} placeholder={tr('Широта')} inputMode="decimal" />
            <Input value={lon} onChange={(ev) => setLon(ev.target.value)} placeholder={tr('Долгота')} inputMode="decimal" />
            <Input value={h} onChange={(ev) => setH(ev.target.value)} placeholder={tr('Высота, м')} inputMode="decimal" />
            <Input value={heading} onChange={(ev) => setHeading(ev.target.value)} placeholder={tr('Азимут, °')} inputMode="decimal" />
          </div>
        </>
      ) : (
        <>
          <p className="text-[11px] text-text-muted">
            Привязано по СК {g.crs ?? ''}. Точная подгонка смещением (м): восток / север / высота.
          </p>
          <div className="grid grid-cols-3 gap-2">
            <Input value={e} onChange={(ev) => setE(ev.target.value)} inputMode="decimal" />
            <Input value={n} onChange={(ev) => setN(ev.target.value)} inputMode="decimal" />
            <Input value={u} onChange={(ev) => setU(ev.target.value)} inputMode="decimal" />
          </div>
        </>
      )}
      {error && <ErrorBox>{error}</ErrorBox>}
      <Button variant="primary" onClick={save} disabled={saving}>
        {saving ? tr('Сохранение…') : tr('Применить')}
      </Button>
    </div>
  );
}

function AssetRow({ asset, onChanged }: { asset: SceneAsset; onChanged: () => void }) {
  const visible = useTwinStore((s) => s.visible[asset.id] ?? true);
  const toggleVisible = useTwinStore((s) => s.toggleVisible);
  const opacity = useTwinStore((s) => s.opacity[asset.id] ?? 1);
  const setOpacity = useTwinStore((s) => s.setOpacity);
  const hidden = useTwinStore((s) => s.hiddenTypes[asset.id]);
  const toggleType = useTwinStore((s) => s.toggleType);
  const requestFlyTo = useTwinStore((s) => s.requestFlyTo);
  const [open, setOpen] = useState(false);
  const [placing, setPlacing] = useState(false);

  const summary =
    asset.kind === 'bim'
      ? `${formatNumber(asset.stats.element_count)} ${tr('эл.')}`
      : asset.kind === 'point_cloud'
        ? `${formatNumber(asset.stats.point_count)} ${tr('точек')}`
        : `${formatNumber(asset.stats.triangle_count)} ${tr('треуг.')}`;

  async function remove() {
    if (!confirm(tr('Удалить «{n}» (версия {v})?', { n: asset.name, v: asset.version }))) return;
    await twinApi.deleteAsset(asset.id);
    onChanged();
  }

  return (
    <div className="rounded-md border border-bg-border bg-bg-panel2/60">
      <div className="flex items-center gap-1 px-1.5 py-1">
        <button
          onClick={() => toggleVisible(asset.id)}
          title={visible ? tr('Скрыть') : tr('Показать')}
          className="flex h-7 w-7 shrink-0 items-center justify-center text-text-secondary hover:text-text-primary"
        >
          {visible ? Icons.eye : Icons.eyeOff}
        </button>
        <button onClick={() => setOpen(!open)} className="min-w-0 flex-1 text-left">
          <div className="truncate text-sm text-text-primary">{asset.name}</div>
          <div className="flex gap-2 text-[11px] text-text-muted">
            <span>v{asset.version}</span>
            <span>{summary}</span>
            {asset.captured_at && <span>{new Date(asset.captured_at).toLocaleDateString(locale())}</span>}
            {asset.georef.mode === 'anchor' && asset.georef.source === 'unplaced' && (
              <span className="text-accent-amber">{tr('не размещена')}</span>
            )}
          </div>
        </button>
        <button
          onClick={() => requestFlyTo({ assetId: asset.id })}
          title={tr('Показать на сцене')}
          className="flex h-7 w-7 shrink-0 items-center justify-center text-text-secondary hover:text-accent-teal"
        >
          {Icons.target}
        </button>
      </div>
      {open && (
        <div className="space-y-3 border-t border-bg-border px-2.5 py-2.5">
          <label className="flex items-center gap-2 text-xs text-text-secondary">
            {tr('Прозрачность')}
            <input
              type="range"
              min={0.1}
              max={1}
              step={0.05}
              value={opacity}
              onChange={(e) => setOpacity(asset.id, Number(e.target.value))}
              className="flex-1 accent-teal-400"
            />
          </label>
          {asset.kind === 'bim' && asset.stats.ifc_types && (
            <div>
              <div className="mb-1 text-[11px] uppercase tracking-wide text-text-secondary">{tr('Классы IFC')}</div>
              <div className="max-h-48 space-y-0.5 overflow-y-auto pr-1">
                {Object.entries(asset.stats.ifc_types).map(([type, count]) => {
                  const on = !(hidden ?? []).includes(type);
                  return (
                    <label key={type} className="flex cursor-pointer items-center gap-2 text-xs">
                      <input type="checkbox" checked={on} onChange={() => toggleType(asset.id, type)} />
                      <span className={on ? 'text-text-primary' : 'text-text-muted'}>{type.replace(/^Ifc/, '')}</span>
                      <span className="ml-auto text-text-muted">{count}</span>
                    </label>
                  );
                })}
              </div>
            </div>
          )}
          <div className="text-[11px] text-text-muted">
            {tr('Привязка')}: {asset.georef.mode === 'absolute' ? `${tr('СК')} ${asset.georef.crs ?? '3D Tiles'}` : `${tr('точка')} (${asset.georef.source})`}
            {asset.stats.ifc_schema ? ` · ${String(asset.stats.ifc_schema)}` : ''}
            {asset.stats.tile_count ? ` · ${tr('тайлов')}: ${asset.stats.tile_count}` : ''}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => setPlacing(!placing)}>{placing ? tr('Скрыть привязку') : tr('Привязка')}</Button>
            <Button variant="danger" onClick={remove}>{tr('Удалить')}</Button>
          </div>
          {placing && <PlacementEditor asset={asset} onSaved={onChanged} />}
        </div>
      )}
    </div>
  );
}

export default function LayersPanel({
  onChanged,
  mapLayers,
  pendingFiles,
}: {
  onChanged: () => void;
  mapLayers: MapLayerSummary[];
  pendingFiles: FileRecord[];
}) {
  const assets = useTwinStore((s) => s.assets);
  const pointSize = useTwinStore((s) => s.pointSize);
  const setPointSize = useTwinStore((s) => s.setPointSize);
  const mapVisible = useTwinStore((s) => s.mapLayerVisible);
  const toggleMapLayer = useTwinStore((s) => s.toggleMapLayer);

  const groups: AssetKind[] = ['bim', 'point_cloud', 'mesh'];

  return (
    <div className="space-y-4">
      {pendingFiles.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-text-secondary">{tr('Обработка')}</div>
          {pendingFiles.map((f) => (
            <div key={f.id} className="rounded-md border border-bg-border px-2.5 py-2 text-xs">
              <div className="flex justify-between gap-2">
                <span className="truncate text-text-primary">{f.filename}</span>
                <span className="shrink-0 text-text-muted">{formatBytes(f.size_bytes)}</span>
              </div>
              {f.status === 'error' ? (
                <div className="mt-1 text-red-300">{f.error_message}</div>
              ) : (
                <FileProgress f={f} />
              )}
            </div>
          ))}
        </div>
      )}

      {assets.length === 0 && mapLayers.length === 0 && pendingFiles.length === 0 && (
        <Empty>
          {tr('Загрузите BIM-модель (IFC), облако точек (LAS/LAZ/E57), фотограмметрию (OBJ/GLB/3D Tiles) или ГИС-слои.')}
        </Empty>
      )}

      {groups.map((kind) => {
        const items = assets.filter((a) => a.kind === kind);
        if (items.length === 0) return null;
        return (
          <div key={kind} className="space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-text-secondary">{KIND_LABELS[kind]}</span>
              {kind === 'point_cloud' && (
                <label className="flex items-center gap-1 text-[11px] text-text-muted">
                  {tr('точка')}
                  <input type="range" min={1} max={8} step={1} value={pointSize} onChange={(e) => setPointSize(Number(e.target.value))} />
                </label>
              )}
            </div>
            {items.map((a) => (
              <AssetRow key={a.id} asset={a} onChanged={onChanged} />
            ))}
          </div>
        );
      })}

      {mapLayers.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-text-secondary">{tr('ГИС / 2D-слои')}</div>
          {mapLayers.map((l) => {
            const on = mapVisible[l.id] ?? true;
            return (
              <button
                key={l.id}
                onClick={() => toggleMapLayer(l.id)}
                className="flex w-full items-center gap-2 rounded-md border border-bg-border bg-bg-panel2/60 px-2 py-1.5 text-left text-sm"
              >
                <span className="text-text-secondary">{on ? Icons.eye : Icons.eyeOff}</span>
                <span className="truncate">{l.name}</span>
                <span className="ml-auto text-[11px] text-text-muted">{l.layer_kind === 'raster' ? tr('растр') : tr('вектор')}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}


/** Stage + bar from `files.metadata.progress`, written by the converter. */
function FileProgress({ f }: { f: FileRecord }) {
  const p = f.metadata.progress as { stage: string; fraction: number | null } | undefined;
  const label = f.status === 'uploaded' ? tr('в очереди') : p ? tr(p.stage) : tr('конвертация в 3D Tiles…');
  const pct = f.status === 'processing' && p?.fraction != null ? Math.round(p.fraction * 100) : null;
  return (
    <div className="mt-1 space-y-1">
      <div className="flex items-center gap-2 text-accent-amber">
        <span className="h-2 w-2 animate-pulse rounded-full bg-accent-amber" />
        <span className="flex-1">{label}</span>
        {pct !== null && <span className="tabular-nums">{pct}%</span>}
      </div>
      {pct !== null && (
        <div className="h-1 overflow-hidden rounded bg-bg-panel2">
          <div className="h-full bg-accent-amber transition-all" style={{ width: `${pct}%` }} />
        </div>
      )}
    </div>
  );
}
