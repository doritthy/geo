'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useWorkspaceStore, type ViewMode } from '@/lib/store';
import { api } from '@/lib/api';
import { clearAuth, getStoredUser } from '@/lib/auth';
import type { Project, WellSummary } from '@/lib/types';

const MODES: { key: ViewMode; label: string }[] = [
  { key: '3d', label: '3D' },
  { key: '2d', label: '2D Map' },
  { key: 'map', label: 'GIS' },
];

function downloadBlob(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function exportWellsCsv(project: Project, wells: WellSummary[]) {
  const header = ['id', 'name', 'well_type', 'surface_x', 'surface_y', 'total_depth_m'];
  const rows = wells.map((w) => [w.id, w.name, w.well_type, w.surface_x, w.surface_y, w.total_depth ?? '']);
  const csv = [header, ...rows].map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(',')).join('\n');
  downloadBlob(`${project.name.replace(/\s+/g, '_')}_wells.csv`, csv, 'text/csv');
}

export default function TopNav({ project, wells }: { project: Project; wells: WellSummary[] }) {
  const router = useRouter();
  const viewMode = useWorkspaceStore((s) => s.viewMode);
  const setViewMode = useWorkspaceStore((s) => s.setViewMode);
  const setIngestDialogOpen = useWorkspaceStore((s) => s.setIngestDialogOpen);
  const user = getStoredUser();

  const [projects, setProjects] = useState<Project[]>([]);
  useEffect(() => {
    api.listProjects().then(setProjects).catch(() => {});
  }, []);

  function onLogout() {
    clearAuth();
    router.push('/login');
  }

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-bg-border bg-bg-panel px-4">
      <div className="flex items-center gap-4">
        <Link href="/projects" className="flex items-center gap-2">
          <div className="h-6 w-6 rounded bg-gradient-to-br from-accent-teal to-accent-blue" />
          <span className="hidden text-sm font-semibold sm:inline">Subsurface 3D</span>
        </Link>

        <select
          value={project.id}
          onChange={(e) => router.push(`/projects/${e.target.value}`)}
          className="rounded-md border border-bg-border bg-bg-panel2 px-2 py-1.5 text-sm text-text-primary outline-none focus:border-accent-teal"
        >
          {projects.length === 0 && <option value={project.id}>{project.name}</option>}
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>

        <div className="flex rounded-md border border-bg-border bg-bg-panel2 p-0.5">
          {MODES.map((m) => (
            <button
              key={m.key}
              onClick={() => setViewMode(m.key)}
              className={`rounded px-3 py-1 text-xs font-medium transition ${
                viewMode === m.key ? 'bg-accent-teal text-bg' : 'text-text-secondary hover:text-text-primary'
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={() => setIngestDialogOpen(true)}
          className="rounded-md bg-accent-teal px-3 py-1.5 text-xs font-semibold text-bg hover:bg-accent-teal/90"
        >
          Upload data
        </button>
        <button
          onClick={() => exportWellsCsv(project, wells)}
          title="Export the visible well list as CSV"
          className="rounded-md border border-bg-border px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary"
        >
          Export CSV
        </button>
        <button
          onClick={() => window.print()}
          title="Print / save as PDF (browser print dialog — a minimal export)"
          className="rounded-md border border-bg-border px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary"
        >
          Export PDF
        </button>
        <div className="mx-1 h-6 w-px bg-bg-border" />
        <span className="hidden text-xs text-text-secondary md:inline">{user?.full_name ?? user?.email}</span>
        <button onClick={onLogout} className="rounded-md border border-bg-border px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary">
          Sign out
        </button>
      </div>
    </header>
  );
}
