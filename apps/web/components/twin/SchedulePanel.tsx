'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTwinStore } from '@/lib/twin/store';
import { twinApi } from '@/lib/twin/api';
import { ApiError } from '@/lib/api';
import { TASK_STATUS, type Analysis, type ScheduleMetrics, type ScheduleTask } from '@/lib/twin/types';
import { Button, Empty, ErrorBox, Field, Input, Select } from './ui';
import { tr, locale } from '@/lib/i18n';

const fmtDate = (d?: string | null) => (d ? new Date(d).toLocaleDateString(locale()) : '—');
const pct = (v?: number | null) => (v === null || v === undefined ? '—' : `${v.toFixed(1)} %`);

function addDays(iso: string, days: number) {
  const d = new Date(iso);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

function TaskLinker({ task, onDone }: { task: ScheduleTask; onDone: () => void }) {
  const assets = useTwinStore((s) => s.assets);
  const selection = useTwinStore((s) => s.selection);
  const models = assets.filter((a) => a.kind === 'bim');
  const [assetId, setAssetId] = useState(models[models.length - 1]?.id ?? '');
  const [ifcType, setIfcType] = useState('');
  const [storey, setStorey] = useState('');
  const [msg, setMsg] = useState<string | null>(null);
  const asset = models.find((m) => m.id === assetId);

  async function link(byFilter: boolean) {
    setMsg(null);
    try {
      const body = byFilter
        ? { asset_id: assetId, ifc_type: ifcType || undefined, storey: storey || undefined }
        : { asset_id: selection!.assetId!, global_ids: [selection!.globalId!] };
      const r = await twinApi.linkTask(task.id, body);
      setMsg(tr('Привязано: +{n} (всего {t})', { n: r.linked, t: r.total }));
      onDone();
    } catch (err) {
      setMsg(err instanceof ApiError ? err.detail : tr('Ошибка'));
    }
  }

  if (!models.length) return <div className="text-xs text-text-muted">{tr('Нет BIM-модели для привязки')}</div>;
  return (
    <div className="space-y-2 rounded-md bg-bg/60 p-2">
      <Select value={assetId} onChange={(e) => setAssetId(e.target.value)}>
        {models.map((m) => <option key={m.id} value={m.id}>{m.name} · v{m.version}</option>)}
      </Select>
      <div className="grid grid-cols-2 gap-2">
        <Select value={ifcType} onChange={(e) => setIfcType(e.target.value)}>
          <option value="">{tr('Все классы')}</option>
          {Object.keys(asset?.stats.ifc_types ?? {}).map((t) => <option key={t} value={t}>{t.replace(/^Ifc/, '')}</option>)}
        </Select>
        <Select value={storey} onChange={(e) => setStorey(e.target.value)}>
          <option value="">{tr('Все этажи')}</option>
          {Object.keys(asset?.stats.storeys ?? {}).map((s) => <option key={s} value={s}>{s}</option>)}
        </Select>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" onClick={() => link(true)} disabled={!ifcType && !storey}>{tr('Привязать по фильтру')}</Button>
        {selection?.kind === 'element' && selection.assetId && <Button onClick={() => link(false)}>{tr('Выбранный элемент')}</Button>}
        {task.element_count > 0 && (
          <Button variant="danger" onClick={async () => { await twinApi.unlinkTask(task.id); setMsg(tr('Привязки удалены')); onDone(); }}>
            {tr('Отвязать все')}
          </Button>
        )}
      </div>
      {msg && <div className="text-[11px] text-text-secondary">{msg}</div>}
    </div>
  );
}

function TaskRow({ task, depth, onChanged }: { task: ScheduleTask; depth: number; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState(String(task.percent_complete));
  const s = TASK_STATUS[task.status];
  useEffect(() => setValue(String(task.percent_complete)), [task.percent_complete]);

  return (
    <div className={task.is_summary ? 'pt-1' : ''}>
      <button onClick={() => !task.is_summary && setOpen(!open)} className="block w-full rounded px-1.5 py-1 text-left hover:bg-bg-panel2"
        style={{ paddingLeft: 6 + depth * 12 }}>
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: s.color }} title={s.label} />
          <span className={`min-w-0 flex-1 truncate text-xs ${task.is_summary ? 'font-semibold text-text-primary' : ''}`}>{task.name}</span>
          <span className="text-[10px] text-text-muted">{task.percent_complete.toFixed(0)}%</span>
        </div>
        <div className="relative mt-0.5 h-1.5 rounded bg-bg-panel2" style={{ marginLeft: 16 }}>
          <div className="absolute inset-y-0 left-0 rounded bg-text-muted/40" style={{ width: `${task.planned_percent}%` }} />
          <div className="absolute inset-y-0 left-0 rounded" style={{ width: `${task.percent_complete}%`, background: s.color }} />
        </div>
      </button>
      {open && (
        <div className="space-y-2 py-2" style={{ paddingLeft: 22 + depth * 12 }}>
          <div className="text-[11px] text-text-muted">
            {fmtDate(task.start_date)} — {fmtDate(task.finish_date)} · {tr('план')} {task.planned_percent.toFixed(0)}% · {tr('элементов')} {task.element_count}
            {task.cost ? ` · ${task.cost.toLocaleString(locale())} ₸` : ''}
          </div>
          <div className="flex items-center gap-2">
            <Input value={value} onChange={(e) => setValue(e.target.value)} inputMode="decimal" className="w-20" />
            <span className="text-xs text-text-secondary">{tr('% факт')}</span>
            <Button onClick={async () => { await twinApi.updateTask(task.id, { percent_complete: Number(value.replace(',', '.')) }); onChanged(); }}>
              {tr('Сохранить')}
            </Button>
          </div>
          <TaskLinker task={task} onDone={onChanged} />
        </div>
      )}
    </div>
  );
}

export default function SchedulePanel({ projectId }: { projectId: string }) {
  const assets = useTwinStore((s) => s.assets);
  const setElementColors = useTwinStore((s) => s.setElementColors);
  const elementColors = useTwinStore((s) => s.elementColors);
  const toggleVisible = useTwinStore((s) => s.toggleVisible);
  const models = useMemo(() => assets.filter((a) => a.kind === 'bim'), [assets]);
  const [tasks, setTasks] = useState<ScheduleTask[]>([]);
  const [metrics, setMetrics] = useState<ScheduleMetrics | null>(null);
  const [on, setOn] = useState(new Date().toISOString().slice(0, 10));
  const [mode4d, setMode4d] = useState(false);
  const [modelId, setModelId] = useState('');
  const [analyses, setAnalyses] = useState<Analysis[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!modelId && models.length) setModelId(models[models.length - 1].id);
  }, [models, modelId]);

  const load = useCallback(async () => {
    const r = await twinApi.getSchedule(projectId, on);
    setTasks(r.tasks);
    setMetrics(r.metrics);
  }, [projectId, on]);

  useEffect(() => {
    load().catch(() => {});
    twinApi.listAnalyses(projectId).then((a) => setAnalyses(a.filter((x) => x.kind === 'deviation' && x.status === 'ready'))).catch(() => {});
  }, [load, projectId]);

  // 4D colouring of the chosen model at the status date.
  useEffect(() => {
    if (!mode4d || !modelId) return;
    let cancelled = false;
    twinApi.elementStatus(projectId, modelId, on).then((r) => {
      if (cancelled) return;
      const colors: Record<string, string> = {};
      for (const [gid, st] of Object.entries(r.statuses)) colors[gid] = TASK_STATUS[st as keyof typeof TASK_STATUS]?.color ?? '#94A3B8';
      setElementColors({ assetId: modelId, colors });
      const group = models.find((m) => m.id === modelId)?.version_group;
      for (const m of models) if (m.version_group === group) toggleVisible(m.id, m.id === modelId);
    });
    return () => {
      cancelled = true;
    };
  }, [mode4d, modelId, on, projectId, tasks, models, setElementColors, toggleVisible]);

  useEffect(() => {
    if (!mode4d && elementColors && elementColors.assetId === modelId) setElementColors(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode4d]);

  async function importFile(file: File) {
    setError(null);
    try {
      const r = await twinApi.importSchedule(projectId, file);
      setTasks(r.tasks);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : tr('Импорт не удался'));
    }
  }

  const depth = useMemo(() => {
    const parent = new Map(tasks.map((t) => [t.id, t.parent_id]));
    const d = new Map<string, number>();
    for (const t of tasks) {
      let n = 0;
      let p = t.parent_id;
      while (p && n < 10) {
        n++;
        p = parent.get(p) ?? null;
      }
      d.set(t.id, n);
    }
    return d;
  }, [tasks]);

  const span = metrics?.start && metrics.finish
    ? { min: addDays(metrics.start, -7), max: addDays(metrics.forecast_finish && metrics.forecast_finish > metrics.finish ? metrics.forecast_finish : metrics.finish, 7) }
    : null;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <label className="cursor-pointer rounded-md bg-accent-teal px-3 py-1.5 text-xs font-semibold text-bg hover:bg-accent-teal/90">
          {tasks.length ? tr('Обновить график') : tr('Загрузить график')}
          <input type="file" accept=".xml,.xlsx,.csv" className="hidden" onChange={(e) => e.target.files?.[0] && importFile(e.target.files[0])} />
        </label>
        <span className="text-[11px] text-text-muted">MS Project XML, Excel, CSV</span>
      </div>
      {error && <ErrorBox>{error}</ErrorBox>}
      {!tasks.length ? (
        <Empty>
          {tr('Загрузите график работ. Из MS Project: «Файл → Сохранить как → XML». В Excel нужны колонки «Наименование», «Начало», «Окончание» и при желании «% выполнения», «Стоимость».')}
        </Empty>
      ) : (
        <>
          <Field label={tr('Отчётная дата')}>
            <Input type="date" value={on} onChange={(e) => setOn(e.target.value)} />
          </Field>
          {span && (
            <input type="range" className="w-full" min={0}
              max={Math.round((new Date(span.max).getTime() - new Date(span.min).getTime()) / 86400000)}
              value={Math.round((new Date(on).getTime() - new Date(span.min).getTime()) / 86400000)}
              onChange={(e) => setOn(addDays(span.min, Number(e.target.value)))} />
          )}
          {metrics && (
            <div className="grid grid-cols-2 gap-x-3 gap-y-1 rounded-lg border border-bg-border p-2.5 text-xs">
              <span className="text-text-secondary">{tr('План / факт')}</span>
              <span className="text-right">{pct(metrics.planned_percent)} / <b>{pct(metrics.actual_percent)}</b></span>
              <span className="text-text-secondary">SPI</span>
              <span className={`text-right font-semibold ${metrics.spi && metrics.spi < 0.95 ? 'text-red-400' : 'text-accent-teal'}`}>
                {metrics.spi ? metrics.spi.toFixed(2) : '—'}
              </span>
              <span className="text-text-secondary">{tr('Окончание по плану')}</span>
              <span className="text-right">{fmtDate(metrics.finish)}</span>
              <span className="text-text-secondary">{tr('Прогноз (по темпу)')}</span>
              <span className={`text-right ${metrics.delay_days && metrics.delay_days > 0 ? 'text-red-400' : ''}`}>
                {fmtDate(metrics.forecast_finish)}
                {metrics.delay_days ? ` (${metrics.delay_days > 0 ? '+' : ''}${metrics.delay_days} ${tr('дн.')})` : ''}
              </span>
              <span className="text-text-secondary">{tr('Задач с отставанием')}</span>
              <span className="text-right">{tr('{a} из {b}', { a: metrics.late_tasks ?? 0, b: metrics.tasks ?? 0 })}</span>
              <span className="col-span-2 text-[10px] text-text-muted">
                Вес задач: {metrics.weight === 'cost' ? tr('стоимость') : tr('длительность')}. Прогноз — линейная экстраполяция по SPI.
              </span>
            </div>
          )}
          <div className="space-y-2 rounded-lg border border-bg-border p-2.5">
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={mode4d} onChange={(e) => setMode4d(e.target.checked)} />
              {tr('4D: раскрасить модель на отчётную дату')}
            </label>
            {models.length > 1 && (
              <Select value={modelId} onChange={(e) => setModelId(e.target.value)}>
                {models.map((m) => <option key={m.id} value={m.id}>{m.name} · v{m.version}</option>)}
              </Select>
            )}
            <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px]">
              {Object.entries(TASK_STATUS).map(([k, v]) => (
                <span key={k} className="flex items-center gap-1 text-text-secondary">
                  <span className="h-2 w-2 rounded-full" style={{ background: v.color }} /> {v.label}
                </span>
              ))}
            </div>
            {analyses.length > 0 && (
              <Button onClick={async () => { const r = await twinApi.progressFromAnalysis(projectId, analyses[0].id); setTasks(r.tasks); load(); }}>
                {tr('Факт по последнему скану')}
              </Button>
            )}
          </div>
          <div className="space-y-0.5">
            {tasks.map((t) => <TaskRow key={t.id} task={t} depth={depth.get(t.id) ?? 0} onChanged={load} />)}
          </div>
        </>
      )}
    </div>
  );
}
