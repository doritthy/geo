'use client';

import { useEffect, useState } from 'react';
import dynamic from 'next/dynamic';
import { useWorkspaceStore, type LayerVisibility } from '@/lib/store';
import { COLORMAP_NAMES, type ColormapName } from '@/lib/colormaps';
import { api } from '@/lib/api';
import CrossSectionControls from '@/components/viewer3d/CrossSectionControls';
import type { Project, WellSummary, GridDetail, SurfaceSummary, Formation } from '@/lib/types';
import type { SceneBounds } from '@/components/viewer3d/Viewer3D';

const MiniMap = dynamic(() => import('./MiniMap'), { ssr: false });

const LAYER_ITEMS: { key: keyof LayerVisibility; label: string }[] = [
  { key: 'wells', label: 'Wells' },
  { key: 'grids', label: 'Grids' },
  { key: 'surfaces', label: 'Surfaces' },
  { key: 'mapLayers', label: 'Map layers' },
];

function Section({ title, children, defaultOpen = true }: { title: string; children: React.ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-b border-bg-border">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-3 py-2.5 text-xs font-semibold uppercase tracking-wide text-text-secondary hover:text-text-primary"
      >
        {title}
        <span>{open ? '−' : '+'}</span>
      </button>
      {open && <div className="space-y-3 px-3 pb-3">{children}</div>}
    </div>
  );
}

function LayerTree() {
  const layerVisibility = useWorkspaceStore((s) => s.layerVisibility);
  const toggleLayer = useWorkspaceStore((s) => s.toggleLayer);
  return (
    <div className="space-y-1.5">
      {LAYER_ITEMS.map((item) => (
        <label key={item.key} className="flex cursor-pointer items-center gap-2 text-sm text-text-primary">
          <input
            type="checkbox"
            checked={layerVisibility[item.key]}
            onChange={() => toggleLayer(item.key)}
            className="accent-accent-teal"
          />
          {item.label}
        </label>
      ))}
    </div>
  );
}

function GridControls({ gridDetails }: { gridDetails: GridDetail[] }) {
  const activeGridId = useWorkspaceStore((s) => s.activeGridId);
  const setActiveGridId = useWorkspaceStore((s) => s.setActiveGridId);
  const activeProperty = useWorkspaceStore((s) => s.activeProperty);
  const setActiveProperty = useWorkspaceStore((s) => s.setActiveProperty);
  const colormap = useWorkspaceStore((s) => s.colormap);
  const setColormap = useWorkspaceStore((s) => s.setColormap);
  const valueRange = useWorkspaceStore((s) => s.valueRange);
  const threshold = useWorkspaceStore((s) => s.threshold);
  const setThreshold = useWorkspaceStore((s) => s.setThreshold);
  const lod = useWorkspaceStore((s) => s.lod);
  const setLod = useWorkspaceStore((s) => s.setLod);

  if (gridDetails.length === 0) {
    return <p className="text-sm text-text-muted">No grids uploaded yet.</p>;
  }

  const activeGrid = gridDetails.find((g) => g.id === activeGridId) ?? null;

  return (
    <div className="space-y-3">
      <div>
        <label className="mb-1 block text-[11px] text-text-muted">Active grid</label>
        <select
          value={activeGridId ?? ''}
          onChange={(e) => setActiveGridId(e.target.value || null)}
          className="w-full rounded-md border border-bg-border bg-bg-panel2 px-2 py-1.5 text-sm outline-none focus:border-accent-teal"
        >
          <option value="">None</option>
          {gridDetails.map((g) => (
            <option key={g.id} value={g.id}>
              {g.name} ({g.active_cell_count.toLocaleString()} cells)
            </option>
          ))}
        </select>
      </div>

      {activeGrid && (
        <>
          <div>
            <label className="mb-1 block text-[11px] text-text-muted">Property</label>
            <select
              value={activeProperty ?? ''}
              onChange={(e) => setActiveProperty(e.target.value || null)}
              className="w-full rounded-md border border-bg-border bg-bg-panel2 px-2 py-1.5 text-sm outline-none focus:border-accent-teal"
            >
              <option value="">None (uniform color)</option>
              {activeGrid.properties.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name}
                  {p.unit ? ` (${p.unit})` : ''}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="mb-1 block text-[11px] text-text-muted">Colormap</label>
            <div className="flex gap-1">
              {COLORMAP_NAMES.map((c) => (
                <button
                  key={c}
                  onClick={() => setColormap(c as ColormapName)}
                  className={`flex-1 rounded px-1.5 py-1 text-[10px] capitalize ${
                    colormap === c ? 'bg-accent-teal text-bg' : 'bg-bg-panel2 text-text-secondary hover:text-text-primary'
                  }`}
                >
                  {c}
                </button>
              ))}
            </div>
          </div>

          {activeProperty && valueRange && (
            <div>
              <label className="mb-1 block text-[11px] text-text-muted">
                Threshold filter ({valueRange.min.toPrecision(3)} – {valueRange.max.toPrecision(3)})
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  value={threshold?.min ?? valueRange.min}
                  onChange={(e) =>
                    setThreshold({ min: Number(e.target.value), max: threshold?.max ?? valueRange.max })
                  }
                  className="w-full rounded-md border border-bg-border bg-bg-panel2 px-2 py-1 text-xs outline-none focus:border-accent-teal"
                />
                <span className="text-text-muted">–</span>
                <input
                  type="number"
                  value={threshold?.max ?? valueRange.max}
                  onChange={(e) =>
                    setThreshold({ min: threshold?.min ?? valueRange.min, max: Number(e.target.value) })
                  }
                  className="w-full rounded-md border border-bg-border bg-bg-panel2 px-2 py-1 text-xs outline-none focus:border-accent-teal"
                />
              </div>
              {threshold && (
                <button onClick={() => setThreshold(null)} className="mt-1 text-[10px] text-accent-teal hover:underline">
                  Reset filter
                </button>
              )}
            </div>
          )}

          <div>
            <label className="mb-1 flex items-center justify-between text-[11px] text-text-muted">
              <span>LOD (subsampling)</span>
              <span>{lod}</span>
            </label>
            <input
              type="range"
              min={0}
              max={3}
              step={1}
              value={lod}
              onChange={(e) => setLod(Number(e.target.value))}
              className="w-full accent-accent-teal"
            />
            <div className="flex justify-between text-[9px] text-text-muted">
              <span>Full detail</span>
              <span>1/64 cells</span>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function FormationCards({ formations }: { formations: Formation[] }) {
  if (formations.length === 0) {
    return <p className="text-sm text-text-muted">No formations defined yet.</p>;
  }
  return (
    <div className="space-y-1.5">
      {formations.map((f) => (
        <div key={f.id} className="flex items-center gap-2 rounded-md border border-bg-border bg-bg-panel2 px-2.5 py-2">
          <span className="h-3 w-3 shrink-0 rounded-sm" style={{ backgroundColor: f.color || '#5B6B85' }} />
          <div className="min-w-0">
            <div className="truncate text-sm text-text-primary">{f.name}</div>
            {f.description && <div className="truncate text-[11px] text-text-muted">{f.description}</div>}
          </div>
        </div>
      ))}
    </div>
  );
}

export default function LeftPanel({
  project,
  wells,
  gridDetails,
  surfaces,
  bounds,
}: {
  project: Project;
  wells: WellSummary[];
  gridDetails: GridDetail[];
  surfaces: SurfaceSummary[];
  bounds: SceneBounds;
}) {
  const [formations, setFormations] = useState<Formation[]>([]);

  useEffect(() => {
    api
      .listFormations(project.id)
      .then(setFormations)
      .catch((err) => console.error('Failed to load formations', err));
  }, [project.id]);

  return (
    <aside className="panel-scroll flex w-72 shrink-0 flex-col overflow-y-auto border-r border-bg-border bg-bg-panel">
      <Section title="Layers">
        <LayerTree />
      </Section>

      <Section title="Grid & property">
        <GridControls gridDetails={gridDetails} />
      </Section>

      <Section title="Cross-sections" defaultOpen={false}>
        <CrossSectionControls bounds={bounds} />
      </Section>

      <Section title="Formations" defaultOpen={false}>
        <FormationCards formations={formations} />
      </Section>

      <Section title="Location" defaultOpen={false}>
        <div className="h-40 overflow-hidden rounded-md border border-bg-border">
          <MiniMap wells={wells} />
        </div>
        <p className="text-[10px] text-text-muted">
          {surfaces.length} surface{surfaces.length === 1 ? '' : 's'} · EPSG:{project.default_crs_epsg}
        </p>
      </Section>
    </aside>
  );
}
