'use client';

import { useWorkspaceStore } from '@/lib/store';
import { colormapToCssGradient } from '@/lib/colormaps';

export default function ColorLegend() {
  const activeProperty = useWorkspaceStore((s) => s.activeProperty);
  const colormap = useWorkspaceStore((s) => s.colormap);
  const valueRange = useWorkspaceStore((s) => s.valueRange);

  if (!activeProperty || !valueRange) return null;

  const gradient = colormapToCssGradient(colormap);

  return (
    <div className="pointer-events-none absolute bottom-4 left-4 z-10 w-64 rounded-lg border border-bg-border bg-bg-panel/90 p-3 backdrop-blur">
      <div className="mb-1.5 flex items-center justify-between text-xs">
        <span className="font-medium text-text-primary">{activeProperty}</span>
        <span className="text-text-muted">{colormap}</span>
      </div>
      <div className="h-3 w-full rounded-sm" style={{ background: gradient }} />
      <div className="mt-1 flex justify-between text-[11px] text-text-secondary">
        <span>{valueRange.min.toPrecision(4)}</span>
        <span>{valueRange.max.toPrecision(4)}</span>
      </div>
    </div>
  );
}
