'use client';

// Project dashboard for the client / back office: schedule progress and SPI,
// quality (latest deviation analysis), issues, scans and models.

import { useEffect, useState } from 'react';
import Link from 'next/link';
import AuthGuard from '@/components/AuthGuard';
import { request, ApiError } from '@/lib/api';
import { ISSUE_STATUS, type IssueStatus, type ScheduleMetrics } from '@/lib/twin/types';

interface Dashboard {
  project: { id: string; name: string; description: string | null };
  schedule: ScheduleMetrics | null;
  issues: {
    total: number;
    open: number;
    overdue: number;
    by_status: Record<string, number>;
    by_assignee: { name: string; count: number }[];
    created_30d: number;
    closed_30d: number;
    overdue_list: { id: string; number: number; title: string; due_date: string }[];
  };
  quality: {
    analysis_id: string;
    date: string;
    within_tolerance: number;
    tolerance_cm: number;
    p95_mm: number;
    worst: { name: string; p95_mm: number; mean_mm: number }[];
  } | null;
  models: { name: string; versions: number; elements: number }[];
  scans: { name: string; captured_at: string; kind: string }[];
  documents: number;
}

const n0 = (v: number) => (Math.round(v) === 0 ? '0' : v.toFixed(0)); // no "-0"
const d = (s?: string | null) => (s ? new Date(s).toLocaleDateString('ru-RU') : '—');

function Tile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: 'bad' | 'good' }) {
  return (
    <div className="rounded-xl border border-bg-border bg-bg-panel p-4">
      <div className="text-xs text-text-secondary">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${tone === 'bad' ? 'text-red-400' : tone === 'good' ? 'text-accent-teal' : 'text-text-primary'}`}>
        {value}
      </div>
      {sub && <div className="mt-0.5 text-xs text-text-muted">{sub}</div>}
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-bg-border bg-bg-panel p-4">
      <h2 className="mb-3 text-sm font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function DashboardInner({ projectId }: { projectId: string }) {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    request<Dashboard>(`/api/projects/${projectId}/dashboard`)
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.detail : 'Не удалось загрузить'));
  }, [projectId]);

  if (error) return <div className="p-8 text-text-secondary">{error}</div>;
  if (!data) return <div className="p-8 text-text-secondary">Загрузка…</div>;
  const s = data.schedule;
  const q = data.quality;
  const statuses = (['open', 'in_progress', 'review', 'closed'] as IssueStatus[]).map((k) => ({ k, n: data.issues.by_status[k] ?? 0 }));
  const maxAssignee = Math.max(1, ...data.issues.by_assignee.map((a) => a.count));

  return (
    <div className="min-h-screen bg-bg">
      <header className="flex items-center gap-3 border-b border-bg-border bg-bg-panel px-4 py-3">
        <Link href={`/twin/${projectId}`} className="text-sm text-accent-teal hover:underline">← К 3D-сцене</Link>
        <h1 className="truncate text-base font-semibold">{data.project.name} — дашборд</h1>
        <button onClick={() => window.print()} className="ml-auto rounded-md border border-bg-border px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary">
          Печать / PDF
        </button>
      </header>
      <main className="mx-auto max-w-6xl space-y-4 p-4">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Tile label="Выполнение (факт / план)" value={s ? `${s.actual_percent?.toFixed(0)}%` : '—'} sub={s ? `план ${s.planned_percent?.toFixed(0)}%` : 'график не загружен'} />
          <Tile label="Индекс сроков SPI" value={s?.spi ? s.spi.toFixed(2) : '—'} sub={s?.spi ? (s.spi < 0.95 ? 'отставание от графика' : 'в графике') : undefined}
            tone={s?.spi ? (s.spi < 0.95 ? 'bad' : 'good') : undefined} />
          <Tile label="Прогноз завершения" value={d(s?.forecast_finish)}
            sub={s ? `план ${d(s.finish)}${s.delay_days ? `, ${s.delay_days > 0 ? '+' : ''}${s.delay_days} дн.` : ''}` : undefined}
            tone={s?.delay_days && s.delay_days > 0 ? 'bad' : undefined} />
          <Tile label="Открытые предписания" value={String(data.issues.open)} sub={`просрочено ${data.issues.overdue}`} tone={data.issues.overdue ? 'bad' : undefined} />
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <Card title="Прогресс работ">
            {s ? (
              <div className="space-y-3">
                {[{ label: 'План на сегодня', v: s.planned_percent ?? 0, c: '#94A3B8' }, { label: 'Факт', v: s.actual_percent ?? 0, c: '#2DD4BF' }].map((r) => (
                  <div key={r.label} title={`${r.label}: ${r.v.toFixed(1)}%`}>
                    <div className="mb-1 flex justify-between text-xs"><span className="text-text-secondary">{r.label}</span><span>{r.v.toFixed(1)}%</span></div>
                    <div className="h-3 rounded bg-bg-panel2"><div className="h-full rounded" style={{ width: `${r.v}%`, background: r.c }} /></div>
                  </div>
                ))}
                <div className="text-xs text-text-muted">
                  {d(s.start)} — {d(s.finish)} · задач {s.tasks}, с отставанием {s.late_tasks} · вес: {s.weight === 'cost' ? 'стоимость' : 'длительность'}
                </div>
              </div>
            ) : (
              <div className="text-sm text-text-muted">Загрузите график работ на 3D-сцене (панель «4D»).</div>
            )}
          </Card>

          <Card title="Качество: факт против проекта">
            {q ? (
              <div className="space-y-2">
                <div className="flex items-baseline gap-2">
                  <span className="text-2xl font-semibold">{(q.within_tolerance * 100).toFixed(1)}%</span>
                  <span className="text-xs text-text-secondary">точек скана в допуске ±{q.tolerance_cm} см · 95% |d| = {q.p95_mm.toFixed(0)} мм · {d(q.date)}</span>
                </div>
                <table className="w-full text-xs">
                  <thead><tr className="text-left text-text-muted"><th className="py-1 font-normal">Элемент</th><th className="font-normal">95%, мм</th><th className="font-normal">ср., мм</th></tr></thead>
                  <tbody>
                    {q.worst.map((w) => (
                      <tr key={w.name} className="border-t border-bg-border/60"><td className="py-1">{w.name}</td><td>{n0(w.p95_mm)}</td><td>{n0(w.mean_mm)}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="text-sm text-text-muted">Анализ отклонений ещё не выполнялся.</div>
            )}
          </Card>

          <Card title="Предписания по статусам">
            <div className="flex h-4 gap-0.5 overflow-hidden rounded">
              {statuses.filter((x) => x.n).map((x) => (
                <div key={x.k} title={`${ISSUE_STATUS[x.k].label}: ${x.n}`} style={{ flex: x.n, background: ISSUE_STATUS[x.k].color }} />
              ))}
              {data.issues.total === 0 && <div className="flex-1 bg-bg-panel2" />}
            </div>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
              {statuses.map((x) => (
                <span key={x.k} className="flex items-center gap-1 text-text-secondary">
                  <span className="h-2 w-2 rounded-full" style={{ background: ISSUE_STATUS[x.k].color }} />
                  {ISSUE_STATUS[x.k].label} <span className="text-text-primary">{x.n}</span>
                </span>
              ))}
            </div>
            <div className="mt-2 text-xs text-text-muted">За 30 дней: создано {data.issues.created_30d}, закрыто {data.issues.closed_30d}</div>
            {data.issues.overdue_list.length > 0 && (
              <div className="mt-3">
                <div className="mb-1 text-xs text-red-400">Просроченные</div>
                {data.issues.overdue_list.map((i) => (
                  <Link key={i.id} href={`/twin/${projectId}?issue=${i.id}`} className="block truncate py-0.5 text-xs hover:text-accent-teal">
                    №{i.number} {i.title} <span className="text-text-muted">· срок {d(i.due_date)}</span>
                  </Link>
                ))}
              </div>
            )}
          </Card>

          <Card title="Открытые предписания по исполнителям">
            {data.issues.by_assignee.length === 0 ? (
              <div className="text-sm text-text-muted">Нет открытых предписаний.</div>
            ) : (
              <div className="space-y-1.5">
                {data.issues.by_assignee.map((a) => (
                  <div key={a.name} className="flex items-center gap-2 text-xs" title={`${a.name}: ${a.count}`}>
                    <span className="w-36 shrink-0 truncate text-text-secondary">{a.name}</span>
                    <div className="h-2.5 flex-1 rounded bg-bg-panel2"><div className="h-full rounded bg-accent-blue" style={{ width: `${(a.count / maxAssignee) * 100}%` }} /></div>
                    <span className="w-6 text-right">{a.count}</span>
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card title="Съёмки">
            {data.scans.length === 0 ? <div className="text-sm text-text-muted">Нет съёмок с датой.</div> : (
              <ul className="space-y-1 text-xs">
                {data.scans.map((sc) => (
                  <li key={sc.name + sc.captured_at} className="flex justify-between"><span>{sc.name}</span><span className="text-text-muted">{d(sc.captured_at)}</span></li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="Модели и документы">
            <ul className="space-y-1 text-xs">
              {data.models.map((m) => (
                <li key={m.name} className="flex justify-between"><span>{m.name}</span><span className="text-text-muted">версий {m.versions} · элементов {m.elements}</span></li>
              ))}
              <li className="flex justify-between border-t border-bg-border/60 pt-1"><span>Документов ПД/РД</span><span>{data.documents}</span></li>
            </ul>
          </Card>
        </div>
      </main>
    </div>
  );
}

export default function DashboardPage({ params }: { params: { projectId: string } }) {
  return (
    <AuthGuard>
      <DashboardInner projectId={params.projectId} />
    </AuthGuard>
  );
}
