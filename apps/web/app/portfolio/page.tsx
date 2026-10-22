'use client';

// Portfolio analytics: the same key figures for every project, side by side
// (ТЗ Фаза 3: «сравнение 3+ проектов в одном интерфейсе»).

import { useEffect, useState } from 'react';
import Link from 'next/link';
import AuthGuard from '@/components/AuthGuard';
import { request, ApiError } from '@/lib/api';
import { SENSOR_STATE } from '@/components/twin/SensorsPanel';
import type { SensorState } from '@/lib/twin/types';
import { locale, tr } from '@/lib/i18n';

interface Row {
  id: string;
  name: string;
  schedule: {
    planned_percent: number | null;
    actual_percent: number | null;
    spi: number | null;
    finish: string | null;
    forecast_finish: string | null;
    delay_days: number | null;
    late_tasks: number | null;
    tasks: number | null;
  } | null;
  issues: { open: number; overdue: number };
  quality: { within_tolerance: number; tolerance_cm: number; date: string } | null;
  sensors: Partial<Record<SensorState, number>>;
  models: number;
  last_scan: string | null;
}

const d = (s?: string | null) => (s ? new Date(s).toLocaleDateString(locale()) : '—');
const BAD = 'text-red-400';
const GOOD = 'text-accent-teal';

/** Actual progress as a bar, planned progress as a tick on the same track. */
function ProgressBar({ actual, planned }: { actual: number; planned: number }) {
  const behind = actual + 0.5 < planned;
  return (
    <div className="relative h-2 w-full rounded-full bg-bg-panel2" title={`${tr('факт')} ${actual.toFixed(0)}% · ${tr('план')} ${planned.toFixed(0)}%`}>
      <div className={`h-full rounded-full ${behind ? 'bg-amber-500' : 'bg-accent-teal'}`} style={{ width: `${Math.min(100, actual)}%` }} />
      <div className="absolute -top-0.5 h-3 w-0.5 rounded bg-text-primary" style={{ left: `calc(${Math.min(100, planned)}% - 1px)` }} />
    </div>
  );
}

function PortfolioInner() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<'name' | 'spi' | 'issues' | 'quality'>('spi');

  useEffect(() => {
    request<{ projects: Row[] }>('/api/portfolio')
      .then((r) => setRows(r.projects))
      .catch((err) => setError(err instanceof ApiError ? err.detail : tr('Не удалось загрузить')));
  }, []);

  if (error) return <div className="p-8 text-text-secondary">{error}</div>;
  if (!rows) return <div className="p-8 text-text-secondary">{tr('Загрузка…')}</div>;

  const sorted = [...rows].sort((a, b) => {
    if (sort === 'name') return a.name.localeCompare(b.name);
    if (sort === 'issues') return b.issues.overdue - a.issues.overdue || b.issues.open - a.issues.open;
    if (sort === 'quality') return (a.quality?.within_tolerance ?? 2) - (b.quality?.within_tolerance ?? 2);
    return (a.schedule?.spi ?? 9) - (b.schedule?.spi ?? 9); // worst schedule first
  });
  const withSchedule = rows.filter((r) => r.schedule?.spi != null);
  const late = withSchedule.filter((r) => (r.schedule!.spi ?? 1) < 0.95).length;
  const overdue = rows.reduce((n, r) => n + r.issues.overdue, 0);
  const alarms = rows.reduce((n, r) => n + (r.sensors.alarm ?? 0) + (r.sensors.warn ?? 0), 0);
  const th = (key: typeof sort, label: string) => (
    <th className="px-3 py-2 text-left font-medium">
      <button onClick={() => setSort(key)} className={sort === key ? 'text-text-primary' : 'hover:text-text-primary'}>
        {label}{sort === key ? ' ↓' : ''}
      </button>
    </th>
  );

  return (
    <div className="min-h-screen bg-bg">
      <header className="flex items-center gap-3 border-b border-bg-border px-4 py-3">
        <Link href="/projects" className="text-sm text-accent-teal hover:underline">{tr('← К проектам')}</Link>
        <h1 className="text-base font-semibold">{tr('Портфель проектов')}</h1>
        <span className="ml-auto text-xs text-text-muted">{tr('на {d}', { d: d(new Date().toISOString()) })}</span>
      </header>
      <main className="mx-auto max-w-7xl space-y-4 p-4">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {[
            [tr('Проектов'), String(rows.length), ''],
            [tr('Отстают от графика'), `${late} / ${withSchedule.length}`, late ? BAD : GOOD],
            [tr('Просроченные предписания'), String(overdue), overdue ? BAD : GOOD],
            [tr('Датчики вне нормы'), String(alarms), alarms ? BAD : GOOD],
          ].map(([label, value, tone]) => (
            <div key={label} className="rounded-xl border border-bg-border bg-bg-panel p-4">
              <div className="text-xs text-text-secondary">{label}</div>
              <div className={`mt-1 text-2xl font-semibold ${tone}`}>{value}</div>
            </div>
          ))}
        </div>

        <div className="overflow-x-auto rounded-xl border border-bg-border bg-bg-panel">
          <table className="w-full min-w-[900px] text-sm">
            <thead className="border-b border-bg-border text-xs text-text-secondary">
              <tr>
                {th('name', tr('Проект'))}
                <th className="px-3 py-2 text-left font-medium">{tr('Выполнение (факт / план)')}</th>
                {th('spi', 'SPI')}
                <th className="px-3 py-2 text-left font-medium">{tr('Прогноз завершения')}</th>
                {th('issues', tr('Предписания'))}
                {th('quality', tr('Качество'))}
                <th className="px-3 py-2 text-left font-medium">{tr('Датчики')}</th>
                <th className="px-3 py-2 text-left font-medium">{tr('Съёмка')}</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => {
                const s = r.schedule;
                return (
                  <tr key={r.id} className="border-b border-bg-border/60 last:border-0 hover:bg-bg-panel2/40">
                    <td className="px-3 py-2.5">
                      <Link href={`/twin/${r.id}/dashboard`} className="font-medium hover:text-accent-teal">{r.name}</Link>
                      <div className="text-[11px] text-text-muted">{tr('моделей {n}', { n: r.models })}</div>
                    </td>
                    <td className="w-56 px-3 py-2.5">
                      {s && s.actual_percent != null && s.planned_percent != null ? (
                        <>
                          <ProgressBar actual={s.actual_percent} planned={s.planned_percent} />
                          <div className="mt-1 text-[11px] text-text-muted">
                            {s.actual_percent.toFixed(0)}% / {s.planned_percent.toFixed(0)}% · {tr('с отставанием {l} из {n}', { l: s.late_tasks ?? 0, n: s.tasks ?? 0 })}
                          </div>
                        </>
                      ) : <span className="text-xs text-text-muted">{tr('график не загружен')}</span>}
                    </td>
                    <td className={`px-3 py-2.5 tabular-nums ${s?.spi == null ? 'text-text-muted' : s.spi < 0.95 ? BAD : GOOD}`}>{s?.spi?.toFixed(2) ?? '—'}</td>
                    <td className="px-3 py-2.5 text-xs">
                      <div>{d(s?.forecast_finish)}</div>
                      {s?.delay_days ? <div className={s.delay_days > 0 ? BAD : GOOD}>{s.delay_days > 0 ? '+' : ''}{s.delay_days} {tr('дн.')}</div> : null}
                    </td>
                    <td className="px-3 py-2.5 text-xs">
                      <div>{tr('открыто {n}', { n: r.issues.open })}</div>
                      <div className={r.issues.overdue ? BAD : 'text-text-muted'}>{tr('просрочено')} {r.issues.overdue}</div>
                    </td>
                    <td className="px-3 py-2.5 text-xs">
                      {r.quality ? (
                        <>
                          <div className={r.quality.within_tolerance < 0.9 ? BAD : ''}>{(r.quality.within_tolerance * 100).toFixed(1)}% ±{r.quality.tolerance_cm} см</div>
                          <div className="text-text-muted">{d(r.quality.date)}</div>
                        </>
                      ) : <span className="text-text-muted">—</span>}
                    </td>
                    <td className="px-3 py-2.5 text-xs">
                      {Object.keys(r.sensors).length === 0 ? <span className="text-text-muted">—</span> : (
                        <div className="flex flex-wrap gap-2">
                          {(['alarm', 'warn', 'stale', 'ok', 'none'] as SensorState[]).filter((st) => r.sensors[st]).map((st) => (
                            <span key={st} className="flex items-center gap-1" title={SENSOR_STATE[st].label}>
                              <span className="h-2 w-2 rounded-full" style={{ background: SENSOR_STATE[st].color }} />
                              {r.sensors[st]}
                            </span>
                          ))}
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-xs text-text-muted">{d(r.last_scan)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="text-[11px] text-text-muted">
          {tr('Полоса — фактическое выполнение, вертикальная риска — план на сегодня. SPI < 0,95 — отставание.')}
        </p>
      </main>
    </div>
  );
}

export default function PortfolioPage() {
  return (
    <AuthGuard>
      <PortfolioInner />
    </AuthGuard>
  );
}
