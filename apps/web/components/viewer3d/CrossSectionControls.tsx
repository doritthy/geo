'use client';

import { useState } from 'react';
import { useWorkspaceStore, type ClipPlaneState } from '@/lib/store';

interface Bounds {
  minX: number;
  minY: number;
  minZ: number;
  maxX: number;
  maxY: number;
  maxZ: number;
}

const AXES: Array<{ key: 'x' | 'y' | 'z'; label: string }> = [
  { key: 'x', label: 'X' },
  { key: 'y', label: 'Y' },
  { key: 'z', label: 'Z' },
];

function AxisSlider({ axisKey, bounds }: { axisKey: 'x' | 'y' | 'z'; bounds: Bounds }) {
  const clip = useWorkspaceStore((s) => s.clipPlanes[axisKey]);
  const setClipPlane = useWorkspaceStore((s) => s.setClipPlane);

  const min = bounds[`min${axisKey.toUpperCase()}` as keyof Bounds];
  const max = bounds[`max${axisKey.toUpperCase()}` as keyof Bounds];
  const step = (max - min) / 200 || 1;

  return (
    <div className="rounded-md border border-bg-border bg-bg-panel2 p-2.5">
      <div className="mb-1.5 flex items-center justify-between">
        <label className="flex items-center gap-1.5 text-xs font-medium text-text-primary">
          <input
            type="checkbox"
            checked={clip.enabled}
            onChange={(e) => setClipPlane(axisKey, { enabled: e.target.checked })}
            className="accent-accent-teal"
          />
          {axisKey.toUpperCase()} slice
        </label>
        <button
          disabled={!clip.enabled}
          onClick={() => setClipPlane(axisKey, { flipped: !clip.flipped })}
          className="rounded border border-bg-border px-1.5 py-0.5 text-[10px] text-text-secondary hover:text-text-primary disabled:opacity-40"
          title="Flip clipped side"
        >
          flip
        </button>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={clip.value}
        disabled={!clip.enabled}
        onChange={(e) => setClipPlane(axisKey, { value: Number(e.target.value) })}
        className="w-full accent-accent-teal disabled:opacity-40"
      />
      <div className="mt-0.5 text-right text-[10px] text-text-muted">{clip.value.toFixed(1)}</div>
    </div>
  );
}

export default function CrossSectionControls({ bounds }: { bounds: Bounds }) {
  const [expanded, setExpanded] = useState(true);

  return (
    <div className="rounded-lg border border-bg-border bg-bg-panel p-3">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="mb-2 flex w-full items-center justify-between text-xs font-semibold uppercase tracking-wide text-text-secondary"
      >
        Cross-sections
        <span>{expanded ? '−' : '+'}</span>
      </button>
      {expanded && (
        <div className="space-y-2">
          {AXES.map((a) => (
            <AxisSlider key={a.key} axisKey={a.key} bounds={bounds} />
          ))}
          <p className="pt-1 text-[10px] leading-snug text-text-muted">
            Enable an axis to slice the grid/surfaces/wells with a live clipping plane. Use &quot;flip&quot; to
            keep the other half.
          </p>
        </div>
      )}
    </div>
  );
}

export type { ClipPlaneState };
