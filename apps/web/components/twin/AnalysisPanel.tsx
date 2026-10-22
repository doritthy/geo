'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTwinStore } from '@/lib/twin/store';
import { twinApi } from '@/lib/twin/api';
import { ApiError } from '@/lib/api';
import type { Analysis, DeviationElement } from '@/lib/twin/types';
import { Button, Empty, ErrorBox, Field, Input, Select } from './ui';
import { tr } from '@/lib/i18n';

const BIN_COLORS = ['#1e40af', '#3b82f6', '#93c5fd', '#22c55e', '#facc15', '#f97316', '#dc2626'];

/** Colour of an element by its 95th-percentile deviation (same bins as the map). */
function elementColor(e: DeviationElement, tol: number[]): string {
  const d = e.mean < 0 ? -e.p95_abs : e.p95_abs;
  const edges = [-tol[2], -tol[1], -tol[0], tol[0], tol[1], tol[2]];
  let i = 0;
  while (i < edges.length && d > edges[i]) i++;
  return BIN_COLORS[i];
}

function mm(v: number | null | undefined) {
  return v === null || v === undefined ? '—' : `${(v * 1000).toFixed(1)} мм`;
}

function DeviationResult({ a, onChanged }: { a: Analysis; onChanged: () => void }) {
  const assets = useTwinStore((s) => s.assets);
  const toggleVisible = useTwinStore((s) => s.toggleVisible);
  const visible = useTwinStore((s) => s.visible);
  const elementColors = useTwinStore((s) => s.elementColors);
  const setElementColors = useTwinStore((s) => s.setElementColors);
  const setSelection = useTwinStore((s) => s.setSelection);
  const requestFlyTo = useTwinStore((s) => s.requestFlyTo);
  const [full, setFull] = useState<Analysis | null>(null);
  const tol = a.result.tolerances ?? [0.01, 0.05, 0.1];
  const hist = a.result.histogram;
  const bimId = a.params.bim_asset_id;
  const coloured = elementColors?.assetId === bimId;

  useEffect(() => {
    twinApi.getAnalysis(a.id).then(setFull);
  }, [a.id]);

  const elements = full?.result.elements ?? [];
  const total = hist ? Math.max(hist.related_points, 1) : 1;
  const mapShown = a.result_asset_id ? visible[a.result_asset_id] ?? true : false;

  function showMap(show: boolean) {
    if (!a.result_asset_id) return;
    toggleVisible(a.result_asset_id, show);
    toggleVisible(a.params.cloud_asset_id, !show);
  }

  function colourModel() {
    if (coloured) return setElementColors(null);
    const colors: Record<string, string> = {};
    for (const e of elements) colors[e.global_id] = elementColor(e, tol);
    setElementColors({ assetId: bimId, colors });
    // Show exactly the analysed version of the model (others would overlap it).
    const group = assets.find((x) => x.id === bimId)?.version_group;
    for (const x of assets) if (x.version_group === group) toggleVisible(x.id, x.id === bimId);
  }

  return (
    <div className="space-y-3">
      {hist && (
        <>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
            <span className="text-text-secondary">В допуске ±{tol[1] * 100} см</span>
            <span className="text-right font-semibold text-text-primary">{(hist.within_tolerance * 100).toFixed(1)} %</span>
            <span className="text-text-secondary">{tr('Среднее / RMS')}</span>
            <span className="text-right">{mm(hist.mean)} / {mm(hist.rms)}</span>
            <span className="text-text-secondary">95% |d|</span>
            <span className="text-right">{mm(hist.p95_abs)}</span>
            <span className="text-text-secondary">{tr('Точек (модель / вне)')}</span>
            <span className="text-right">{hist.related_points.toLocaleString('ru-RU')} / {hist.unrelated_points.toLocaleString('ru-RU')}</span>
          </div>
          <div className="space-y-0.5">
            {hist.bins.map((b) => (
              <div key={b.label} className="flex items-center gap-2 text-[11px]">
                <span className="w-24 shrink-0 text-text-secondary">{b.label}</span>
                <div className="h-2.5 flex-1 rounded bg-bg-panel2">
                  <div className="h-full rounded" style={{ width: `${(b.count / total) * 100}%`, background: b.color }} />
                </div>
                <span className="w-10 text-right text-text-muted">{((b.count / total) * 100).toFixed(0)}%</span>
              </div>
            ))}
          </div>
        </>
      )}
      <div className="flex flex-wrap gap-2">
        {a.result_asset_id && assets.some((x) => x.id === a.result_asset_id) && (
          <Button variant={mapShown ? 'primary' : 'secondary'} onClick={() => showMap(!mapShown)}>
            {mapShown ? tr('Скрыть карту') : tr('Показать карту')}
          </Button>
        )}
        <Button variant={coloured ? 'primary' : 'secondary'} onClick={colourModel} disabled={!elements.length}>
          {coloured ? tr('Обычные цвета модели') : tr('Раскрасить модель')}
        </Button>
        <Button onClick={() => twinApi.downloadReport(a.id)}>{tr('PDF-отчёт')}</Button>
        <Button
          variant="danger"
          onClick={async () => {
            if (!confirm(tr('Удалить анализ и карту отклонений?'))) return;
            await twinApi.deleteAnalysis(a.id);
            onChanged();
          }}
        >
          {tr('Удалить')}
        </Button>
      </div>
      {elements.length > 0 && (
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-wide text-text-secondary">
            Элементы с наибольшими отклонениями ({full?.result.elements_total})
          </div>
          <div className="max-h-72 space-y-0.5 overflow-y-auto">
            {elements.slice(0, 100).map((e) => (
              <button
                key={e.global_id}
                onClick={() => {
                  setSelection({ kind: 'element', assetId: bimId, globalId: e.global_id, title: e.name });
                  requestFlyTo({ point: { longitude: e.longitude, latitude: e.latitude, height: e.height } });
                }}
                className="flex w-full items-center gap-2 rounded px-1.5 py-1 text-left text-xs hover:bg-bg-panel2"
              >
                <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: elementColor(e, tol) }} />
                <span className="min-w-0 flex-1 truncate">{e.name || e.global_id}</span>
                <span className="text-text-muted">{(e.mean < 0 ? '−' : '+') + (e.p95_abs * 1000).toFixed(0)} мм</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function AnalysisPanel({ projectId, onAssetsChanged }: { projectId: string; onAssetsChanged: () => void }) {
  const assets = useTwinStore((s) => s.assets);
  const clouds = useMemo(() => assets.filter((a) => a.kind === 'point_cloud' && !a.stats.analysis_id), [assets]);
  const models = useMemo(() => assets.filter((a) => a.kind === 'bim'), [assets]);
  const [cloudId, setCloudId] = useState('');
  const [bimId, setBimId] = useState('');
  const [t1, setT1] = useState('1');
  const [t2, setT2] = useState('5');
  const [t3, setT3] = useState('10');
  const [radius, setRadius] = useState('30');
  const [list, setList] = useState<Analysis[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!cloudId && clouds.length) setCloudId(clouds[clouds.length - 1].id);
    if (!bimId && models.length) setBimId(models[models.length - 1].id);
  }, [clouds, models, cloudId, bimId]);

  const load = useCallback(() => twinApi.listAnalyses(projectId).then(setList).catch(() => {}), [projectId]);
  useEffect(() => {
    load();
  }, [load]);

  const running = list.some((a) => a.status === 'pending' || a.status === 'running');
  useEffect(() => {
    if (!running) return;
    const t = setInterval(async () => {
      const next = await twinApi.listAnalyses(projectId);
      setList(next);
      if (!next.some((a) => a.status === 'pending' || a.status === 'running')) onAssetsChanged();
    }, 3000);
    return () => clearInterval(t);
  }, [running, projectId, onAssetsChanged]);

  async function run(kind: 'deviation' | 'alignment') {
    setError(null);
    try {
      const a =
        kind === 'deviation'
          ? await twinApi.runDeviation(projectId, {
              cloud_asset_id: cloudId,
              bim_asset_id: bimId,
              tolerances: [t1, t2, t3].map((v) => Number(v.replace(',', '.')) / 100),
              max_distance: Number(radius.replace(',', '.')) / 100,
            })
          : await twinApi.runAlignment(projectId, { cloud_asset_id: cloudId, bim_asset_id: bimId, apply: true });
      setOpen(a.id);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : tr('Не удалось запустить анализ'));
    }
  }

  async function resetAlignment() {
    await twinApi.updateAsset(cloudId, { reset_alignment: true });
    onAssetsChanged();
  }

  if (clouds.length === 0 || models.length === 0) {
    return <Empty>{tr('Для анализа «план — факт» нужны BIM-модель и облако точек (лазерный скан или фотограмметрия в облаке точек).')}</Empty>;
  }
  const cloud = clouds.find((c) => c.id === cloudId);

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Field label={tr('Съёмка (облако точек)')}>
          <Select value={cloudId} onChange={(e) => setCloudId(e.target.value)}>
            {clouds.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}{c.captured_at ? ` · ${new Date(c.captured_at).toLocaleDateString('ru-RU')}` : ''}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={tr('Проектная модель')}>
          <Select value={bimId} onChange={(e) => setBimId(e.target.value)}>
            {models.map((m) => <option key={m.id} value={m.id}>{m.name} · v{m.version}</option>)}
          </Select>
        </Field>
      </div>

      <div className="space-y-2 rounded-lg border border-bg-border p-3">
        <div className="text-sm font-semibold">{tr('Подгонка скана к модели')}</div>
        <p className="text-[11px] text-text-muted">
          {tr('ICP по поверхностям модели: поворот вокруг вертикали + смещение. Применяется к скану; исходная привязка не теряется.')}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => run('alignment')} disabled={running}>{tr('Подогнать')}</Button>
          {cloud?.georef.mode === 'absolute' && cloud.georef.alignment && (
            <Button variant="ghost" onClick={resetAlignment}>{tr('Сбросить подгонку')}</Button>
          )}
        </div>
      </div>

      <div className="space-y-2 rounded-lg border border-bg-border p-3">
        <div className="text-sm font-semibold">{tr('Карта отклонений')}</div>
        <div className="grid grid-cols-4 gap-2">
          <Field label={tr('±1, см')}><Input value={t1} onChange={(e) => setT1(e.target.value)} inputMode="decimal" /></Field>
          <Field label={tr('±2, см')}><Input value={t2} onChange={(e) => setT2(e.target.value)} inputMode="decimal" /></Field>
          <Field label={tr('±3, см')}><Input value={t3} onChange={(e) => setT3(e.target.value)} inputMode="decimal" /></Field>
          <Field label={tr('Радиус, см')}><Input value={radius} onChange={(e) => setRadius(e.target.value)} inputMode="decimal" /></Field>
        </div>
        <p className="text-[11px] text-text-muted">
          {tr('Точки дальше радиуса от модели (рельеф, леса, техника) считаются «вне модели» и окрашиваются серым.')}
        </p>
        <Button variant="primary" onClick={() => run('deviation')} disabled={running}>
          {running ? tr('Расчёт…') : tr('Рассчитать отклонения')}
        </Button>
      </div>

      {error && <ErrorBox>{error}</ErrorBox>}

      <div className="space-y-1.5">
        {list.map((a) => (
          <div key={a.id} className="rounded-md border border-bg-border">
            <button onClick={() => setOpen(open === a.id ? null : a.id)} className="block w-full px-2.5 py-2 text-left">
              <div className="flex items-center justify-between gap-2 text-sm">
                <span>{a.kind === 'deviation' ? tr('Отклонения') : tr('Подгонка ICP')}</span>
                <span className={`text-[11px] ${a.status === 'error' ? 'text-red-300' : a.status === 'ready' ? 'text-accent-teal' : 'text-accent-amber'}`}>
                  {{ pending: tr('в очереди'), running: tr('расчёт…'), ready: tr('готово'), error: tr('ошибка') }[a.status]}
                </span>
              </div>
              <div className="truncate text-[11px] text-text-muted">
                {a.result.cloud?.name ?? ''} ↔ {a.result.bim ? `${a.result.bim.name} v${a.result.bim.version}` : ''} ·{' '}
                {new Date(a.created_at).toLocaleString('ru-RU')}
              </div>
            </button>
            {open === a.id && (
              <div className="border-t border-bg-border px-2.5 py-2.5">
                {a.status === 'error' && <ErrorBox>{a.error_message}</ErrorBox>}
                {a.status === 'ready' && a.kind === 'deviation' && <DeviationResult a={a} onChanged={() => { load(); onAssetsChanged(); }} />}
                {a.status === 'ready' && a.kind === 'alignment' && (
                  <div className="space-y-1 text-xs">
                    <div>Смещение (В/С/Высота): {a.result.translation_enu?.map((v) => `${(v * 100).toFixed(1)} см`).join(' / ')}</div>
                    <div>Поворот: {a.result.yaw_deg?.toFixed(3)}°</div>
                    <div>Невязка до / после: {mm(a.result.rmse_before)} / {mm(a.result.rmse_after)}</div>
                    <div className="text-text-muted">{tr('Подгонка применена к скану. Пересчитайте карту отклонений.')}</div>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
