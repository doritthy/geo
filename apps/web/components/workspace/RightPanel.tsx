'use client';

import { useEffect, useState } from 'react';
import { useWorkspaceStore } from '@/lib/store';
import { api } from '@/lib/api';
import type { WellDetail, LogCurveSummary } from '@/lib/types';

// Property names that, when present on a grid, are surfaced as dedicated
// reservoir-engineering fields in the inspector (fuzzy-matched by common
// naming conventions since the contract doesn't fix property name strings).
const RESERVOIR_FIELD_PATTERNS: { key: string; label: string; patterns: RegExp[] }[] = [
  { key: 'sw', label: 'Sw (water saturation)', patterns: [/^sw$/i, /water.?sat/i] },
  { key: 'so', label: 'So (oil saturation)', patterns: [/^so$/i, /oil.?sat/i] },
  { key: 'poro', label: 'Porosity', patterns: [/^poro/i, /^phi$/i] },
  { key: 'perm', label: 'Permeability', patterns: [/^perm/i, /^k$/i] },
  { key: 'ntg', label: 'NTG', patterns: [/ntg/i, /net.?to.?gross/i] },
];

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between border-b border-bg-border/60 py-1.5 text-sm">
      <span className="text-text-secondary">{label}</span>
      <span className="font-mono text-text-primary">{value}</span>
    </div>
  );
}

function GridSampleSection() {
  const inspection = useWorkspaceStore((s) => s.pointInspection);
  if (!inspection || !inspection.gridId) return null;

  return (
    <div className="space-y-1">
      <Row label="Grid" value={inspection.gridName ?? inspection.gridId} />
      <Row label="X" value={inspection.x.toFixed(2)} />
      <Row label="Y" value={inspection.y.toFixed(2)} />
      <Row label="Z / TVD" value={inspection.z.toFixed(2)} />
      {inspection.propertyName && (
        <Row
          label={inspection.propertyName}
          value={
            inspection.sample?.value != null
              ? inspection.sample.value.toPrecision(5)
              : inspection.sample === undefined
              ? 'sampling…'
              : '—'
          }
        />
      )}
      {inspection.sample && (
        <>
          <Row label="Cell (i, j, k)" value={`${inspection.sample.i}, ${inspection.sample.j}, ${inspection.sample.k}`} />
          <Row label="Interpolation" value={inspection.sample.interpolation} />
        </>
      )}
      {inspection.extraValues &&
        Object.entries(inspection.extraValues).map(([k, v]) => (
          <Row key={k} label={k} value={v != null ? v.toPrecision(5) : '—'} />
        ))}

      {inspection.sample &&
        RESERVOIR_FIELD_PATTERNS.filter((f) => f.patterns.some((re) => re.test(inspection.propertyName ?? ''))).map(
          (f) => (
            <div key={f.key} className="mt-2 rounded-md border border-accent-teal/30 bg-accent-teal/5 px-2.5 py-1.5 text-xs text-accent-teal">
              Recognized as: {f.label}
            </div>
          )
        )}
    </div>
  );
}

function WellSection() {
  const inspection = useWorkspaceStore((s) => s.pointInspection);
  const [detail, setDetail] = useState<WellDetail | null>(null);
  const [logs, setLogs] = useState<LogCurveSummary[]>([]);

  useEffect(() => {
    if (!inspection?.wellId) {
      setDetail(null);
      setLogs([]);
      return;
    }
    let cancelled = false;
    api.getWell(inspection.wellId).then((d) => !cancelled && setDetail(d)).catch(() => {});
    api.getWellLogs(inspection.wellId).then((l) => !cancelled && setLogs(l)).catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [inspection?.wellId]);

  if (!inspection?.wellId) return null;

  return (
    <div className="space-y-1">
      <Row label="Well" value={inspection.wellName ?? inspection.wellId} />
      {detail && (
        <>
          <Row label="Type" value={detail.well_type} />
          <Row label="Surface X, Y" value={`${detail.surface_x.toFixed(1)}, ${detail.surface_y.toFixed(1)}`} />
          {detail.total_depth != null && <Row label="Total depth" value={`${detail.total_depth.toFixed(1)} m`} />}
          {detail.kb_elevation != null && <Row label="KB elevation" value={`${detail.kb_elevation.toFixed(1)} m`} />}
          <Row label="CRS" value={`EPSG:${detail.crs_epsg}`} />
        </>
      )}
      {logs.length > 0 && (
        <div className="pt-2">
          <div className="mb-1 text-[11px] uppercase tracking-wide text-text-muted">Log curves</div>
          {logs.map((l) => (
            <Row key={l.id} label={`${l.curve_name}${l.unit ? ` (${l.unit})` : ''}`} value={`${l.min_value.toPrecision(3)} – ${l.max_value.toPrecision(3)}`} />
          ))}
        </div>
      )}
    </div>
  );
}

export default function RightPanel() {
  const inspection = useWorkspaceStore((s) => s.pointInspection);

  return (
    <aside className="panel-scroll flex w-80 shrink-0 flex-col overflow-y-auto border-l border-bg-border bg-bg-panel px-3.5 py-3">
      <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-text-secondary">Reservoir sample</h2>

      {!inspection && (
        <p className="text-sm text-text-muted">
          Click a grid cell, well, or surface in the 3D viewer to inspect its position and property values here.
        </p>
      )}

      {inspection && (
        <div className="space-y-4">
          <GridSampleSection />
          <WellSection />
          {!inspection.gridId && !inspection.wellId && (
            <div className="space-y-1">
              <Row label="X" value={inspection.x.toFixed(2)} />
              <Row label="Y" value={inspection.y.toFixed(2)} />
              <Row label="Z / TVD" value={inspection.z.toFixed(2)} />
            </div>
          )}
        </div>
      )}
    </aside>
  );
}
