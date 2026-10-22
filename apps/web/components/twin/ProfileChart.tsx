'use client';

import { useEffect, useMemo, useState } from 'react';
import { request, ApiError } from '@/lib/api';
import { useTwinStore } from '@/lib/twin/store';
import { Icons, Select } from './ui';

interface Profile {
  length: number;
  bim: [number, number, number, number][];
  scan: [number, number][];
}

const W = 900;
const H = 260;
const PAD = { l: 52, r: 14, t: 14, b: 30 };

function niceTicks(lo: number, hi: number, n = 5): number[] {
  const span = hi - lo || 1;
  const step0 = span / n;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= step0) ?? step0;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(v);
  return out;
}

/** Vertical section along the drawn line: BIM cut lines + scan points. */
export default function ProfileChart() {
  const line = useTwinStore((s) => s.profileLine);
  const setLine = useTwinStore((s) => s.setProfileLine);
  const assets = useTwinStore((s) => s.assets);
  const visible = useTwinStore((s) => s.visible);
  const projectId = assets[0]?.project_id;
  const models = assets.filter((a) => a.kind === 'bim');
  const clouds = assets.filter((a) => a.kind === 'point_cloud' && !a.stats.analysis_id);
  const [bimId, setBimId] = useState('');
  const [cloudId, setCloudId] = useState('');
  const [data, setData] = useState<Profile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hover, setHover] = useState<{ x: number; s: number; z: number } | null>(null);

  useEffect(() => {
    const vis = (id: string) => visible[id] ?? true;
    if (!bimId && models.length) setBimId((models.find((m) => vis(m.id)) ?? models[models.length - 1]).id);
    if (!cloudId && clouds.length) setCloudId(clouds[clouds.length - 1].id);
  }, [models, clouds, bimId, cloudId, visible]);

  useEffect(() => {
    if (!line || !projectId) return;
    setData(null);
    setError(null);
    request<Profile>(`/api/projects/${projectId}/profile`, {
      method: 'POST',
      body: JSON.stringify({ a: line.a, b: line.b, bim_asset_id: bimId || null, cloud_asset_id: cloudId || null, width: 0.4 }),
    })
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.detail : 'Не удалось построить разрез'));
  }, [line, projectId, bimId, cloudId]);

  const scale = useMemo(() => {
    if (!data) return null;
    const zs = [...data.bim.flatMap((s) => [s[1], s[3]]), ...data.scan.map((p) => p[1])];
    if (!zs.length) return null;
    let zlo = Math.min(...zs);
    let zhi = Math.max(...zs);
    const padZ = (zhi - zlo) * 0.08 || 1;
    zlo -= padZ;
    zhi += padZ;
    // Equal-ish aspect is not forced: sections are long and low.
    const x = (s: number) => PAD.l + (s / (data.length || 1)) * (W - PAD.l - PAD.r);
    const y = (z: number) => H - PAD.b - ((z - zlo) / (zhi - zlo)) * (H - PAD.t - PAD.b);
    return { x, y, zlo, zhi, sx: niceTicks(0, data.length), sz: niceTicks(zlo, zhi) };
  }, [data]);

  if (!line) return null;

  return (
    <div className="absolute bottom-10 left-3 right-3 z-20 rounded-xl border border-bg-border bg-bg-panel/95 p-3 backdrop-blur sm:left-16">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
        <span className="font-semibold text-text-primary">Профиль-разрез</span>
        {data && <span className="text-text-muted">длина {data.length.toFixed(1)} м · коридор скана 0,4 м</span>}
        <Select value={bimId} onChange={(e) => setBimId(e.target.value)} className="!w-auto !py-1 text-xs">
          <option value="">без модели</option>
          {models.map((m) => <option key={m.id} value={m.id}>{m.name} · v{m.version}</option>)}
        </Select>
        <Select value={cloudId} onChange={(e) => setCloudId(e.target.value)} className="!w-auto !py-1 text-xs">
          <option value="">без скана</option>
          {clouds.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </Select>
        <span className="ml-auto flex items-center gap-3 text-text-secondary">
          <span className="flex items-center gap-1"><span className="inline-block h-0.5 w-4 bg-text-primary" /> BIM</span>
          <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-full bg-accent-teal" /> Скан</span>
        </span>
        <button onClick={() => setLine(null)} className="text-text-secondary hover:text-text-primary" aria-label="Закрыть">{Icons.close}</button>
      </div>
      {error && <div className="text-xs text-red-300">{error}</div>}
      {!data && !error && <div className="h-40 animate-pulse rounded bg-bg-panel2" />}
      {data && !scale && <div className="py-6 text-center text-xs text-text-muted">Линия не пересекает модель и скан</div>}
      {data && scale && (
        <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full"
          onMouseMove={(e) => {
            const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
            const px = ((e.clientX - rect.left) / rect.width) * W;
            const py = ((e.clientY - rect.top) / rect.height) * H;
            if (px < PAD.l || px > W - PAD.r) return setHover(null);
            const s = ((px - PAD.l) / (W - PAD.l - PAD.r)) * data.length;
            const z = scale.zlo + ((H - PAD.b - py) / (H - PAD.t - PAD.b)) * (scale.zhi - scale.zlo);
            setHover({ x: px, s, z });
          }}
          onMouseLeave={() => setHover(null)}>
          {scale.sz.map((z) => (
            <g key={`z${z}`}>
              <line x1={PAD.l} x2={W - PAD.r} y1={scale.y(z)} y2={scale.y(z)} stroke="currentColor" className="text-bg-border" strokeWidth={1} />
              <text x={PAD.l - 6} y={scale.y(z) + 3} textAnchor="end" className="fill-text-muted" fontSize={10}>{z.toFixed(1)}</text>
            </g>
          ))}
          {scale.sx.map((s) => (
            <text key={`s${s}`} x={scale.x(s)} y={H - 10} textAnchor="middle" className="fill-text-muted" fontSize={10}>{s.toFixed(0)} м</text>
          ))}
          {data.scan.map(([s, z], i) => (
            <circle key={i} cx={scale.x(s)} cy={scale.y(z)} r={1.6} fill="#2DD4BF" opacity={0.75} />
          ))}
          {data.bim.map(([s0, z0, s1, z1], i) => (
            <line key={i} x1={scale.x(s0)} y1={scale.y(z0)} x2={scale.x(s1)} y2={scale.y(z1)} stroke="currentColor" className="text-text-primary" strokeWidth={1.5} />
          ))}
          {hover && (
            <g pointerEvents="none">
              <line x1={hover.x} x2={hover.x} y1={PAD.t} y2={H - PAD.b} stroke="currentColor" className="text-text-secondary" strokeDasharray="3 3" />
              <rect x={Math.min(hover.x + 6, W - 130)} y={PAD.t} width={124} height={34} rx={4} className="fill-bg-panel2" />
              <text x={Math.min(hover.x + 12, W - 124)} y={PAD.t + 14} fontSize={11} className="fill-text-primary">{hover.s.toFixed(2)} м</text>
              <text x={Math.min(hover.x + 12, W - 124)} y={PAD.t + 28} fontSize={11} className="fill-text-secondary">H {hover.z.toFixed(2)} м</text>
            </g>
          )}
          <text x={8} y={PAD.t + 4} fontSize={10} className="fill-text-muted">H, м</text>
        </svg>
      )}
    </div>
  );
}
