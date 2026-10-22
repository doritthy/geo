'use client';

// Floating controls over the Cesium viewport: tool palette, measurement
// result card, section (clipping) controls and the monitoring timeline.

import { useMemo, useState } from 'react';
import { useTwinStore, type ToolMode } from '@/lib/twin/store';
import { Icons, IconButton } from './ui';
import { tr } from '@/lib/i18n';

const TOOLS: { key: ToolMode; title: string; icon: JSX.Element }[] = [
  { key: 'select', title: tr('Выбор элемента'), icon: Icons.select },
  { key: 'point', title: tr('Координаты и отметка точки'), icon: Icons.point },
  { key: 'distance', title: tr('Расстояние (двойной клик / ПКМ — завершить)'), icon: Icons.distance },
  { key: 'area', title: tr('Площадь'), icon: Icons.area },
  { key: 'height', title: tr('Перепад высот'), icon: Icons.height },
  { key: 'angle', title: tr('Угол (3 точки)'), icon: Icons.angle },
  { key: 'volume', title: tr('Объём (насыпь / выемка)'), icon: Icons.volume },
  { key: 'profile', title: tr('Профиль-разрез: BIM против скана'), icon: Icons.profile },
  { key: 'annotate', title: tr('Добавить метку'), icon: Icons.annotate },
  { key: 'issue', title: tr('Новое предписание в точке'), icon: Icons.issue },
];

export function ToolPalette({ onToggleClip, clipOpen }: { onToggleClip: () => void; clipOpen: boolean }) {
  const tool = useTwinStore((s) => s.tool);
  const setTool = useTwinStore((s) => s.setTool);
  const clearMeasurements = useTwinStore((s) => s.clearMeasurements);
  const globeTranslucent = useTwinStore((s) => s.globeTranslucent);
  const setGlobeTranslucent = useTwinStore((s) => s.setGlobeTranslucent);

  return (
    <div className="absolute left-3 top-3 z-10 flex flex-col gap-1 rounded-xl border border-bg-border bg-bg-panel/90 p-1 backdrop-blur">
      {TOOLS.map((t) => (
        <IconButton key={t.key} title={t.title} active={tool === t.key} onClick={() => setTool(t.key)}>
          {t.icon}
        </IconButton>
      ))}
      <div className="my-0.5 h-px bg-bg-border" />
      <IconButton title={tr('Сечение')} active={clipOpen} onClick={onToggleClip}>{Icons.section}</IconButton>
      <IconButton title={tr('Прозрачная земля (подземная часть)')} active={globeTranslucent} onClick={() => setGlobeTranslucent(!globeTranslucent)}>
        {Icons.globe}
      </IconButton>
      <IconButton title={tr('Очистить измерения (Esc)')} onClick={clearMeasurements}>{Icons.clear}</IconButton>
    </div>
  );
}

const TOOL_HINTS: Partial<Record<ToolMode, string>> = {
  point: tr('Кликните по модели или местности'),
  distance: tr('Кликайте точки; двойной клик или ПКМ — завершить'),
  area: tr('Обведите контур; двойной клик или ПКМ — завершить'),
  height: tr('Укажите две точки'),
  angle: tr('Укажите три точки: начало, вершину, конец'),
  volume: tr('Обведите контур объёма; база — средняя отметка контура'),
  annotate: tr('Кликните место для метки'),
  issue: tr('Кликните место нарушения на модели'),
  profile: tr('Укажите начало и конец линии разреза'),
};

export function MeasurementCard() {
  const tool = useTwinStore((s) => s.tool);
  const measurement = useTwinStore((s) => s.measurement);
  if (tool === 'select') return null;
  return (
    <div className="absolute bottom-16 left-3 z-10 w-72 max-w-[calc(100%-1.5rem)] rounded-xl border border-bg-border bg-bg-panel/95 p-3 text-xs backdrop-blur sm:left-16 sm:top-3 sm:bottom-auto">
      <div className="mb-1 text-text-secondary">{TOOL_HINTS[tool]}</div>
      {measurement?.lines.map((l) => (
        <div key={l.label} className="flex justify-between gap-3 border-t border-bg-border/60 py-1">
          <span className="text-text-secondary">{l.label}</span>
          <span className="text-right font-medium text-text-primary">{l.value}</span>
        </div>
      ))}
    </div>
  );
}

export function ClipPanel({ heightRange }: { heightRange: [number, number] }) {
  const clip = useTwinStore((s) => s.clip);
  const setClip = useTwinStore((s) => s.setClip);
  const [lo, hi] = heightRange;
  return (
    <div className="absolute left-16 top-3 z-10 w-72 max-w-[calc(100%-5rem)] space-y-3 rounded-xl border border-bg-border bg-bg-panel/95 p-3 text-xs backdrop-blur">
      <div className="font-semibold">{tr('Сечения')}</div>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={clip.horizontal} onChange={(e) => setClip({ horizontal: e.target.checked, height: clip.height || (lo + hi) / 2 })} />
        {tr('Горизонтальное (по отметке)')}
      </label>
      {clip.horizontal && (
        <div>
          <input
            type="range"
            min={lo}
            max={hi}
            step={0.05}
            value={clip.height}
            onChange={(e) => setClip({ height: Number(e.target.value) })}
            className="w-full"
          />
          <div className="text-text-muted">Отметка: {clip.height.toFixed(2)} м</div>
        </div>
      )}
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={clip.vertical} onChange={(e) => setClip({ vertical: e.target.checked })} />
        {tr('Вертикальное (разрез)')}
      </label>
      {clip.vertical && (
        <div className="space-y-2">
          <div>
            <input type="range" min={0} max={359} value={clip.heading} onChange={(e) => setClip({ heading: Number(e.target.value) })} className="w-full" />
            <div className="text-text-muted">Направление: {clip.heading}°</div>
          </div>
          <div>
            <input
              type="range"
              min={-(hi - lo)}
              max={hi - lo}
              step={0.1}
              value={clip.offset}
              onChange={(e) => setClip({ offset: Number(e.target.value) })}
              className="w-full"
            />
            <div className="text-text-muted">Смещение: {clip.offset.toFixed(1)} м</div>
          </div>
        </div>
      )}
    </div>
  );
}

export function TimelineBar() {
  const assets = useTwinStore((s) => s.assets);
  const enabled = useTwinStore((s) => s.timelineEnabled);
  const date = useTwinStore((s) => s.timelineDate);
  const setTimeline = useTwinStore((s) => s.setTimeline);
  const dates = useMemo(
    () =>
      [...new Set(assets.filter((a) => a.kind !== 'bim' && a.captured_at).map((a) => a.captured_at as string))].sort(),
    [assets]
  );
  if (dates.length === 0) return null;
  const idx = Math.max(0, date ? dates.indexOf(date) : dates.length - 1);

  return (
    <div className="absolute bottom-10 left-1/2 z-10 w-[min(36rem,calc(100%-1.5rem))] -translate-x-1/2 rounded-xl border border-bg-border bg-bg-panel/90 px-3 py-2 text-xs backdrop-blur">
      <div className="flex items-center gap-3">
        <button
          onClick={() => setTimeline(!enabled, date ?? dates[dates.length - 1])}
          className={`flex items-center gap-1 ${enabled ? 'text-accent-teal' : 'text-text-secondary hover:text-text-primary'}`}
          title={tr('Временная шкала мониторинга')}
        >
          {Icons.clock}
          <span className="hidden sm:inline">{tr('Мониторинг')}</span>
        </button>
        <input
          type="range"
          min={0}
          max={dates.length - 1}
          value={idx}
          disabled={!enabled}
          onChange={(e) => setTimeline(true, dates[Number(e.target.value)])}
          className="flex-1"
        />
        <span className="w-24 text-right text-text-primary">
          {enabled ? new Date(dates[idx]).toLocaleDateString('ru-RU') : tr('все съёмки')}
        </span>
      </div>
      {enabled && (
        <div className="mt-1 flex justify-between text-[10px] text-text-muted">
          {dates.map((d) => (
            <span key={d}>{new Date(d).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })}</span>
          ))}
        </div>
      )}
    </div>
  );
}
