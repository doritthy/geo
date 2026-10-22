'use client';

import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import { useTwinStore } from '@/lib/twin/store';
import { absoluteUrl, twinApi } from '@/lib/twin/api';
import { ApiError } from '@/lib/api';
import type { Sensor, SensorAlert, SensorKind, SensorSeries, SensorState } from '@/lib/twin/types';
import { Button, Empty, ErrorBox, Field, Input, Select } from './ui';
import { locale, tr } from '@/lib/i18n';

export const SENSOR_STATE: Record<SensorState, { label: string; color: string }> = {
  alarm: { label: tr('Авария'), color: '#EF4444' },
  warn: { label: tr('Предупреждение'), color: '#F59E0B' },
  ok: { label: tr('Норма'), color: '#22C55E' },
  stale: { label: tr('Нет данных'), color: '#64748B' },
  none: { label: tr('Ожидает данных'), color: '#64748B' },
};

const KINDS: Record<SensorKind, { label: string; unit: string }> = {
  temperature: { label: tr('Температура бетона'), unit: '°C' },
  strain: { label: tr('Деформация'), unit: 'мкм/м' },
  tilt: { label: tr('Крен'), unit: 'мм/м' },
  displacement: { label: tr('Смещение'), unit: 'мм' },
  humidity: { label: tr('Влажность'), unit: '%' },
  other: { label: tr('Другое'), unit: '' },
};

const ORDER: SensorState[] = ['alarm', 'warn', 'stale', 'ok', 'none'];

function ago(ts: string | null): string {
  if (!ts) return '—';
  const min = Math.round((Date.now() - new Date(ts).getTime()) / 60000);
  if (min < 1) return tr('только что');
  if (min < 60) return tr('{n} мин назад', { n: min });
  if (min < 48 * 60) return tr('{n} ч назад', { n: Math.round(min / 60) });
  return new Date(ts).toLocaleDateString(locale());
}

const fmt = (v: number | null | undefined, unit = '') => (v === null || v === undefined ? '—' : `${Number(v.toFixed(2))} ${unit}`.trim());

function StateBadge({ state }: { state: SensorState }) {
  const s = SENSOR_STATE[state];
  return (
    <span className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold" style={{ background: `${s.color}22`, color: s.color }}>
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: s.color }} />
      {s.label}
    </span>
  );
}

/** Time series: bucket averages as a line, bucket min/max as a band (short
 * spikes stay visible), warning/alarm thresholds as dashed lines. */
function SensorChart({ series }: { series: SensorSeries }) {
  const W = 320;
  const H = 150;
  const P = { l: 36, r: 6, t: 8, b: 18 };
  const [hover, setHover] = useState<number | null>(null);
  const pts = series.points;
  const scale = useMemo(() => {
    if (!pts.length) return null;
    const th = Object.values(series.thresholds).filter((v): v is number => v !== null);
    const lo = Math.min(...pts.map((p) => p.min));
    const hi = Math.max(...pts.map((p) => p.max));
    // Show thresholds only when they are near the data, so they don't flatten it.
    const span = hi - lo || 1;
    const near = th.filter((v) => v > lo - span && v < hi + span);
    const zlo = Math.min(lo, ...near);
    const zhi = Math.max(hi, ...near);
    const pad = (zhi - zlo) * 0.08 || 1;
    const t0 = new Date(pts[0].ts).getTime();
    const t1 = new Date(pts[pts.length - 1].ts).getTime() || t0 + 1;
    return {
      x: (ts: string) => P.l + ((new Date(ts).getTime() - t0) / Math.max(t1 - t0, 1)) * (W - P.l - P.r),
      y: (v: number) => H - P.b - ((v - (zlo - pad)) / (zhi - zlo + 2 * pad)) * (H - P.t - P.b),
      zlo: zlo - pad,
      zhi: zhi + pad,
      t0,
      t1,
      near,
    };
  }, [pts, series.thresholds]);

  if (!scale) return <div className="py-6 text-center text-xs text-text-muted">{tr('Нет показаний за период')}</div>;
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${scale.x(p.ts).toFixed(1)},${scale.y(p.value).toFixed(1)}`).join('');
  const band =
    pts.map((p, i) => `${i ? 'L' : 'M'}${scale.x(p.ts).toFixed(1)},${scale.y(p.max).toFixed(1)}`).join('') +
    [...pts].reverse().map((p) => `L${scale.x(p.ts).toFixed(1)},${scale.y(p.min).toFixed(1)}`).join('') + 'Z';
  const ticks = [scale.zlo + (scale.zhi - scale.zlo) * 0.15, (scale.zlo + scale.zhi) / 2, scale.zhi - (scale.zhi - scale.zlo) * 0.15];
  const short = (t: number) => {
    const d = new Date(t);
    return scale.t1 - scale.t0 > 36 * 3600e3
      ? d.toLocaleDateString(locale(), { day: '2-digit', month: '2-digit' })
      : d.toLocaleTimeString(locale(), { hour: '2-digit', minute: '2-digit' });
  };
  const thColor = (k: string) => (k.startsWith('alarm') ? '#EF4444' : '#F59E0B');
  const hp = hover !== null ? pts[hover] : null;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="h-auto w-full select-none"
      onMouseMove={(e) => {
        const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
        const x = ((e.clientX - r.left) / r.width) * W;
        let best = 0;
        for (let i = 1; i < pts.length; i++) if (Math.abs(scale.x(pts[i].ts) - x) < Math.abs(scale.x(pts[best].ts) - x)) best = i;
        setHover(best);
      }}
      onMouseLeave={() => setHover(null)}
    >
      {ticks.map((v) => (
        <g key={v}>
          <line x1={P.l} x2={W - P.r} y1={scale.y(v)} y2={scale.y(v)} stroke="currentColor" className="text-bg-border" strokeWidth={0.6} />
          <text x={P.l - 4} y={scale.y(v) + 3} textAnchor="end" fontSize={8} className="fill-text-muted">{Number(v.toPrecision(3))}</text>
        </g>
      ))}
      {Object.entries(series.thresholds).map(([k, v]) =>
        v !== null && scale.near.includes(v) ? (
          <line key={k} x1={P.l} x2={W - P.r} y1={scale.y(v)} y2={scale.y(v)} stroke={thColor(k)} strokeDasharray="4 3" strokeWidth={1} />
        ) : null
      )}
      <path d={band} fill="#2DD4BF" opacity={0.18} />
      <path d={line} fill="none" stroke="#2DD4BF" strokeWidth={1.6} strokeLinejoin="round" />
      <text x={P.l} y={H - 4} fontSize={8} className="fill-text-muted">{short(scale.t0)}</text>
      <text x={W - P.r} y={H - 4} fontSize={8} textAnchor="end" className="fill-text-muted">{short(scale.t1)}</text>
      {hp && (
        <g pointerEvents="none">
          <line x1={scale.x(hp.ts)} x2={scale.x(hp.ts)} y1={P.t} y2={H - P.b} stroke="currentColor" className="text-text-secondary" strokeDasharray="2 2" />
          <circle cx={scale.x(hp.ts)} cy={scale.y(hp.value)} r={3} fill="#2DD4BF" stroke="#0B0F19" strokeWidth={1.5} />
          <rect x={Math.min(scale.x(hp.ts) + 6, W - 112)} y={P.t} width={106} height={30} rx={3} className="fill-bg-panel2" />
          <text x={Math.min(scale.x(hp.ts) + 11, W - 107)} y={P.t + 12} fontSize={9} className="fill-text-primary">
            {fmt(hp.value, series.unit)}
          </text>
          <text x={Math.min(scale.x(hp.ts) + 11, W - 107)} y={P.t + 24} fontSize={8} className="fill-text-muted">
            {new Date(hp.ts).toLocaleString(locale(), { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}
          </text>
        </g>
      )}
    </svg>
  );
}

function SensorCard({ id, onChanged, onClose }: { id: string; onChanged: () => void; onClose: () => void }) {
  const requestFlyTo = useTwinStore((s) => s.requestFlyTo);
  const [sensor, setSensor] = useState<Sensor | null>(null);
  const [hours, setHours] = useState(24);
  const [series, setSeries] = useState<SensorSeries | null>(null);
  const [edit, setEdit] = useState(false);
  const [th, setTh] = useState({ warn_min: '', warn_max: '', alarm_min: '', alarm_max: '' });
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    twinApi.getSensor(id).then((s) => {
      setSensor(s);
      setTh({
        warn_min: s.warn_min?.toString() ?? '', warn_max: s.warn_max?.toString() ?? '',
        alarm_min: s.alarm_min?.toString() ?? '', alarm_max: s.alarm_max?.toString() ?? '',
      });
    }).catch((e) => setError(e instanceof ApiError ? e.detail : tr('Ошибка')));
  }, [id]);
  useEffect(load, [load]);
  useEffect(() => {
    setSeries(null);
    twinApi.sensorReadings(id, hours).then(setSeries).catch(() => {});
    const t = setInterval(() => twinApi.sensorReadings(id, hours).then(setSeries).catch(() => {}), 30000);
    return () => clearInterval(t);
  }, [id, hours]);

  if (!sensor) return error ? <ErrorBox>{error}</ErrorBox> : <div className="h-40 animate-pulse rounded bg-bg-panel2" />;
  const canEdit = !!sensor.ingest_token;
  const num = (v: string) => (v.trim() === '' ? null : Number(v.replace(',', '.')));

  async function saveThresholds(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await twinApi.updateSensor(id, { warn_min: num(th.warn_min), warn_max: num(th.warn_max), alarm_min: num(th.alarm_min), alarm_max: num(th.alarm_max) });
      setEdit(false);
      load();
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : tr('Не удалось сохранить'));
    }
  }

  const ingestUrl = absoluteUrl('/api/iot/ingest');
  return (
    <div className="space-y-3">
      <button onClick={onClose} className="text-xs text-text-secondary hover:text-text-primary">{tr('← К списку')}</button>
      <div>
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-semibold">{sensor.name}</span>
          <StateBadge state={sensor.state} />
        </div>
        <div className="text-[11px] text-text-muted">{sensor.code} · {KINDS[sensor.kind]?.label ?? sensor.kind}</div>
      </div>
      <div className="flex items-end justify-between">
        <div>
          <div className="text-2xl font-semibold tabular-nums" style={{ color: SENSOR_STATE[sensor.state].color }}>{fmt(sensor.last_value, sensor.unit)}</div>
          <div className="text-[11px] text-text-muted">{ago(sensor.last_at)}</div>
        </div>
        {sensor.longitude !== null && sensor.latitude !== null && (
          <Button variant="ghost" onClick={() => requestFlyTo({ sensorId: sensor.id })}>{tr('Показать на сцене')}</Button>
        )}
      </div>
      <div className="flex gap-1">
        {[[24, tr('24 ч')], [24 * 7, tr('7 дн.')], [24 * 30, tr('30 дн.')]].map(([h, l]) => (
          <button key={h} onClick={() => setHours(Number(h))}
            className={`rounded px-2 py-0.5 text-[11px] ${hours === h ? 'bg-accent-teal text-bg' : 'text-text-secondary hover:text-text-primary'}`}>{l}</button>
        ))}
      </div>
      {series ? <SensorChart series={series} /> : <div className="h-32 animate-pulse rounded bg-bg-panel2" />}
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px] text-text-secondary">
        <span>{tr('Предупреждение')}: <span className="text-text-primary">{fmt(sensor.warn_min)} … {fmt(sensor.warn_max)}</span></span>
        <span>{tr('Авария')}: <span className="text-text-primary">{fmt(sensor.alarm_min)} … {fmt(sensor.alarm_max)}</span></span>
      </div>

      {canEdit && (
        <>
          {edit ? (
            <form onSubmit={saveThresholds} className="space-y-2 rounded-md bg-bg-panel2/50 p-2">
              <div className="grid grid-cols-2 gap-2">
                <Field label={tr('Предупр. мин')}><Input value={th.warn_min} onChange={(e) => setTh({ ...th, warn_min: e.target.value })} inputMode="decimal" /></Field>
                <Field label={tr('Предупр. макс')}><Input value={th.warn_max} onChange={(e) => setTh({ ...th, warn_max: e.target.value })} inputMode="decimal" /></Field>
                <Field label={tr('Авария мин')}><Input value={th.alarm_min} onChange={(e) => setTh({ ...th, alarm_min: e.target.value })} inputMode="decimal" /></Field>
                <Field label={tr('Авария макс')}><Input value={th.alarm_max} onChange={(e) => setTh({ ...th, alarm_max: e.target.value })} inputMode="decimal" /></Field>
              </div>
              <div className="flex justify-end gap-2">
                <Button type="button" onClick={() => setEdit(false)}>{tr('Отмена')}</Button>
                <Button type="submit" variant="primary">{tr('Сохранить')}</Button>
              </div>
            </form>
          ) : (
            <Button onClick={() => setEdit(true)}>{tr('Изменить пороги')}</Button>
          )}
          <details className="rounded-md border border-bg-border px-2.5 py-2 text-[11px]">
            <summary className="cursor-pointer text-text-secondary">{tr('Подключение шлюза')}</summary>
            <div className="mt-2 space-y-2 text-text-secondary">
              <div>{tr('Токен датчика')}: <code className="break-all text-text-primary">{sensor.ingest_token}</code></div>
              <div>HTTP:</div>
              <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded bg-bg p-2 text-[10px] text-text-primary">{`curl -X POST ${ingestUrl} \\
  -H 'X-Sensor-Token: ${sensor.ingest_token}' \\
  -H 'Content-Type: application/json' \\
  -d '{"value": 21.5}'`}</pre>
              <div>MQTT: <code className="break-all text-text-primary">twin/sensors/{sensor.id}</code></div>
              <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded bg-bg p-2 text-[10px] text-text-primary">{`{"token": "${sensor.ingest_token}", "value": 21.5, "ts": "2026-05-20T10:00:00Z"}`}</pre>
              <div className="flex gap-2">
                <Button onClick={async () => { if (confirm(tr('Старый токен перестанет работать. Продолжить?'))) { await twinApi.rotateSensorToken(id); load(); } }}>
                  {tr('Новый токен')}
                </Button>
                <Button variant="danger" onClick={async () => { if (confirm(tr('Удалить датчик и все его показания?'))) { await twinApi.deleteSensor(id); onChanged(); onClose(); } }}>
                  {tr('Удалить')}
                </Button>
              </div>
            </div>
          </details>
        </>
      )}
      {error && <ErrorBox>{error}</ErrorBox>}
    </div>
  );
}

function NewSensorForm({ projectId, onCreated }: { projectId: string; onCreated: (s: Sensor) => void }) {
  const point = useTwinStore((s) => s.pendingSensorPoint);
  const setPoint = useTwinStore((s) => s.setPendingSensorPoint);
  const [f, setF] = useState({ code: '', name: '', kind: 'temperature' as SensorKind, unit: '°C', warn_min: '', warn_max: '', alarm_min: '', alarm_max: '' });
  const [error, setError] = useState<string | null>(null);
  if (!point) return null;
  const num = (v: string) => (v.trim() === '' ? null : Number(v.replace(',', '.')));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const s = await twinApi.createSensor(projectId, {
        code: f.code, name: f.name, kind: f.kind, unit: f.unit,
        longitude: point!.longitude, latitude: point!.latitude, height: point!.height,
        asset_id: point!.assetId ?? null, element_global_id: point!.globalId ?? null,
        warn_min: num(f.warn_min), warn_max: num(f.warn_max), alarm_min: num(f.alarm_min), alarm_max: num(f.alarm_max),
      });
      setPoint(null);
      onCreated(s);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : tr('Не удалось создать'));
    }
  }

  return (
    <form onSubmit={submit} className="space-y-2 rounded-md border border-accent-teal/40 bg-accent-teal/5 p-2.5">
      <div className="text-xs font-semibold">{tr('Новый датчик')}</div>
      <div className="grid grid-cols-2 gap-2">
        <Field label={tr('Код устройства')}><Input value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} placeholder="T-301" required /></Field>
        <Field label={tr('Тип')}>
          <Select value={f.kind} onChange={(e) => { const k = e.target.value as SensorKind; setF({ ...f, kind: k, unit: KINDS[k].unit }); }}>
            {Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </Select>
        </Field>
      </div>
      <Field label={tr('Название / место')}><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder={tr('Плита 3 эт., ось Б-2')} required /></Field>
      <div className="grid grid-cols-3 gap-2">
        <Field label={tr('Ед. изм.')}><Input value={f.unit} onChange={(e) => setF({ ...f, unit: e.target.value })} /></Field>
        <Field label={tr('Предупр. макс')}><Input value={f.warn_max} onChange={(e) => setF({ ...f, warn_max: e.target.value })} inputMode="decimal" /></Field>
        <Field label={tr('Авария макс')}><Input value={f.alarm_max} onChange={(e) => setF({ ...f, alarm_max: e.target.value })} inputMode="decimal" /></Field>
        <div />
        <Field label={tr('Предупр. мин')}><Input value={f.warn_min} onChange={(e) => setF({ ...f, warn_min: e.target.value })} inputMode="decimal" /></Field>
        <Field label={tr('Авария мин')}><Input value={f.alarm_min} onChange={(e) => setF({ ...f, alarm_min: e.target.value })} inputMode="decimal" /></Field>
      </div>
      {error && <ErrorBox>{error}</ErrorBox>}
      <div className="flex justify-end gap-2">
        <Button type="button" onClick={() => setPoint(null)}>{tr('Отмена')}</Button>
        <Button type="submit" variant="primary">{tr('Создать')}</Button>
      </div>
    </form>
  );
}

/** IoT sensors: state overview, per-sensor chart and thresholds, alerts feed. */
export default function SensorsPanel({ projectId, canEdit }: { projectId: string; canEdit: boolean }) {
  const sensors = useTwinStore((s) => s.sensors);
  const setSensors = useTwinStore((s) => s.setSensors);
  const openId = useTwinStore((s) => s.openSensorId);
  const setOpenId = useTwinStore((s) => s.setOpenSensorId);
  const tool = useTwinStore((s) => s.tool);
  const setTool = useTwinStore((s) => s.setTool);
  const pending = useTwinStore((s) => s.pendingSensorPoint);
  const [alerts, setAlerts] = useState<SensorAlert[]>([]);

  const reload = useCallback(() => {
    twinApi.listSensors(projectId).then(setSensors).catch(() => {});
    twinApi.sensorAlerts(projectId).then(setAlerts).catch(() => {});
  }, [projectId, setSensors]);
  useEffect(reload, [reload]);

  if (openId) return <SensorCard id={openId} onChanged={reload} onClose={() => setOpenId(null)} />;

  const sorted = [...sensors].sort((a, b) => ORDER.indexOf(a.state) - ORDER.indexOf(b.state) || a.name.localeCompare(b.name));
  const counts = ORDER.map((st) => [st, sensors.filter((s) => s.state === st).length] as const).filter(([, n]) => n);

  return (
    <div className="space-y-3">
      {canEdit && !pending && (
        tool === 'sensor' ? (
          <div className="rounded-md border border-dashed border-accent-teal/60 px-2.5 py-2 text-xs text-accent-teal">
            {tr('Кликните место установки датчика на модели')}{' '}
            <button className="ml-1 underline" onClick={() => setTool('select')}>{tr('Отмена')}</button>
          </div>
        ) : (
          <Button onClick={() => setTool('sensor')}>{tr('+ Датчик')}</Button>
        )
      )}
      <NewSensorForm projectId={projectId} onCreated={(s) => { reload(); setOpenId(s.id); }} />

      {sensors.length === 0 ? (
        <Empty>{tr('Датчиков пока нет. Добавьте датчик и подключите шлюз по HTTP или MQTT.')}</Empty>
      ) : (
        <>
          <div className="flex flex-wrap gap-1.5">
            {counts.map(([st, n]) => (
              <span key={st} className="flex items-center gap-1 text-[11px] text-text-secondary">
                <span className="h-2 w-2 rounded-full" style={{ background: SENSOR_STATE[st].color }} />
                {SENSOR_STATE[st].label} {n}
              </span>
            ))}
          </div>
          <div className="space-y-1">
            {sorted.map((s) => (
              <button key={s.id} onClick={() => setOpenId(s.id)}
                className="flex w-full items-center gap-2 rounded-md border border-bg-border px-2.5 py-1.5 text-left hover:border-accent-teal/60">
                <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: SENSOR_STATE[s.state].color }} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm">{s.name}</span>
                  <span className="block text-[11px] text-text-muted">{s.code} · {ago(s.last_at)}</span>
                </span>
                <span className="shrink-0 text-sm tabular-nums" style={{ color: s.state === 'ok' || s.state === 'none' ? undefined : SENSOR_STATE[s.state].color }}>
                  {fmt(s.last_value, s.unit)}
                </span>
              </button>
            ))}
          </div>
        </>
      )}

      {alerts.length > 0 && (
        <div>
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-text-secondary">{tr('События')}</div>
          <div className="space-y-1">
            {alerts.slice(0, 12).map((a) => (
              <button key={a.id} onClick={() => setOpenId(a.sensor_id)} className="flex w-full gap-2 text-left text-[11px] hover:text-text-primary">
                <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: SENSOR_STATE[a.level].color }} />
                <span className="text-text-muted">{new Date(a.ts).toLocaleString(locale(), { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>
                <span className="min-w-0 flex-1 truncate text-text-secondary">{a.message}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
