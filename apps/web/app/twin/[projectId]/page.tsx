'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import AuthGuard from '@/components/AuthGuard';
import { ApiError } from '@/lib/api';
import { clearAuth, getStoredUser } from '@/lib/auth';
import { twinApi } from '@/lib/twin/api';
import { useProjectCrs } from '@/lib/twin/crs';
import { useTwinStore, type SidePanel } from '@/lib/twin/store';
import type { TwinProject } from '@/lib/twin/types';
import type { FileRecord, MapLayerSummary } from '@/lib/types';
import LayersPanel from '@/components/twin/LayersPanel';
import SearchPanel from '@/components/twin/SearchPanel';
import AnnotationsPanel from '@/components/twin/AnnotationsPanel';
import DocumentsPanel from '@/components/twin/DocumentsPanel';
import ComparePanel from '@/components/twin/ComparePanel';
import SettingsPanel from '@/components/twin/SettingsPanel';
import AutodeskPanel from '@/components/twin/AutodeskPanel';
import AnalysisPanel from '@/components/twin/AnalysisPanel';
import IssuesPanel from '@/components/twin/IssuesPanel';
import SchedulePanel from '@/components/twin/SchedulePanel';
import PropertiesPanel from '@/components/twin/PropertiesPanel';
import UploadDialog from '@/components/twin/UploadDialog';
import { ClipPanel, MeasurementCard, TimelineBar, ToolPalette } from '@/components/twin/ViewportOverlays';
import { Icons, IconButton } from '@/components/twin/ui';
import ProfileChart from '@/components/twin/ProfileChart';

const CesiumViewer = dynamic(() => import('@/components/twin/CesiumViewer'), {
  ssr: false,
  loading: () => <div className="flex h-full items-center justify-center text-sm text-text-secondary">Загрузка 3D-движка…</div>,
});

const PANELS: { key: SidePanel; title: string; icon: JSX.Element }[] = [
  { key: 'layers', title: 'Слои', icon: Icons.layers },
  { key: 'search', title: 'Поиск элементов', icon: Icons.search },
  { key: 'issues', title: 'Предписания и замечания', icon: Icons.issue },
  { key: 'annotations', title: 'Метки', icon: Icons.annotate },
  { key: 'documents', title: 'Документы ПД/РД', icon: Icons.docs },
  { key: 'compare', title: 'Сравнение версий', icon: Icons.compare },
  { key: 'analysis', title: 'План — факт: отклонения', icon: Icons.analysis },
  { key: 'schedule', title: '4D: график работ', icon: Icons.schedule },
  { key: 'autodesk', title: 'Autodesk ACC / BIM 360', icon: Icons.cloud },
  { key: 'settings', title: 'Настройки проекта', icon: Icons.settings },
];

function TwinWorkspace({ projectId }: { projectId: string }) {
  const router = useRouter();
  const [project, setProject] = useState<TwinProject | null>(null);
  const [mapLayers, setMapLayers] = useState<MapLayerSummary[]>([]);
  const [files, setFiles] = useState<FileRecord[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [clipOpen, setClipOpen] = useState(false);
  const [cursor, setCursor] = useState<string | null>(null);
  const user = getStoredUser();

  const setAssets = useTwinStore((s) => s.setAssets);
  const assets = useTwinStore((s) => s.assets);
  const setAnnotations = useTwinStore((s) => s.setAnnotations);
  const panel = useTwinStore((s) => s.panel);
  const setPanel = useTwinStore((s) => s.setPanel);
  const panelOpen = useTwinStore((s) => s.panelOpen);
  const setPanelOpen = useTwinStore((s) => s.setPanelOpen);
  const planView = useTwinStore((s) => s.planView);
  const setPlanView = useTwinStore((s) => s.setPlanView);
  const crs = useProjectCrs(project?.crs);

  const loadAssets = useCallback(async () => {
    const [a, layers, f] = await Promise.all([
      twinApi.listAssets(projectId),
      twinApi.listMapLayers(projectId),
      twinApi.listFiles(projectId),
    ]);
    setAssets(a);
    setMapLayers(layers);
    setFiles(f);
  }, [projectId, setAssets]);

  const loadAnnotations = useCallback(() => twinApi.listAnnotations(projectId).then(setAnnotations), [projectId, setAnnotations]);

  useEffect(() => {
    useTwinStore.setState({ assets: [], selection: null, compare: null, highlight: null, annotations: [], issues: [], openIssueId: null });
    twinApi
      .getProject(projectId)
      .then(setProject)
      .catch((err) => setError(err instanceof ApiError ? err.detail : 'Не удалось загрузить проект'));
    loadAssets().catch(() => {});
    loadAnnotations().catch(() => {});
    twinApi.listIssues(projectId, { status: 'open,in_progress,review' }).then(useTwinStore.getState().setIssues).catch(() => {});
    const issueParam = new URLSearchParams(window.location.search).get('issue');
    if (issueParam) useTwinStore.getState().setOpenIssueId(issueParam);
  }, [projectId, loadAssets, loadAnnotations]);

  // Poll while conversions are running.
  const twinCategories = ['bim', 'point_cloud', 'reality_mesh', 'map_vector', 'map_raster'];
  const recentFiles = files.filter((f) => twinCategories.includes(f.category));
  const processing = recentFiles.filter((f) => f.status === 'uploaded' || f.status === 'processing');
  const failed = recentFiles.filter((f) => f.status === 'error').slice(0, 3);
  useEffect(() => {
    if (processing.length === 0) return;
    const t = setInterval(() => loadAssets().catch(() => {}), 3000);
    return () => clearInterval(t);
  }, [processing.length, loadAssets]);

  // Lowest point of the site across assets: used as the flat ground level
  // when no terrain service (Cesium ion) is configured.
  const groundHeight = useMemo<number | null>(() => {
    const hs: number[] = [];
    for (const a of assets) {
      const st = a.stats as Record<string, any>;
      if (a.georef.mode === 'anchor') hs.push(a.georef.height);
      else if (a.kind === 'point_cloud' && st.bounds_source) hs.push(st.bounds_source.min[2] + (a.georef.height_offset ?? 0));
      else if (st.center && st.bounds_model) hs.push(st.center.height - (st.bounds_model.max[2] - st.bounds_model.min[2]) / 2);
      else if (st.center) hs.push(st.center.height);
    }
    return hs.length ? Math.min(...hs) - 0.05 : null;
  }, [assets]);

  // Vertical extent of the scene for the horizontal section slider.
  const heightRange = useMemo<[number, number]>(() => {
    const tops: number[] = [];
    for (const a of assets) {
      const st = a.stats as Record<string, any>;
      if (st.center && st.bounds_model) tops.push(st.center.height + (st.bounds_model.max[2] - st.bounds_model.min[2]) / 2);
      else if (a.kind === 'point_cloud' && st.bounds_source) tops.push(st.bounds_source.max[2] + (a.georef.mode === 'absolute' ? a.georef.height_offset ?? 0 : 0));
      else if (st.center) tops.push(st.center.height + 10);
      else if (a.georef.mode === 'anchor') tops.push(a.georef.height + 30);
    }
    if (groundHeight === null || tops.length === 0) return [-50, 150];
    return [groundHeight - 5, Math.max(...tops) + 2];
  }, [assets, groundHeight]);

  if (error) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-3 bg-bg text-text-secondary">
        <p>{error}</p>
        <Link href="/projects" className="rounded-md border border-bg-border px-4 py-2 text-sm hover:text-text-primary">К проектам</Link>
      </div>
    );
  }
  if (!project) return <div className="flex h-screen items-center justify-center bg-bg text-text-secondary">Загрузка проекта…</div>;

  const panelTitle = PANELS.find((p) => p.key === panel)?.title;

  return (
    <div className="flex h-[100dvh] flex-col bg-bg">
      <link rel="stylesheet" href="/cesium/Widgets/widgets.css" />
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-bg-border bg-bg-panel px-2 sm:px-3">
        <button className="sm:hidden" onClick={() => setPanelOpen(!panelOpen)} aria-label="Меню">{Icons.menu}</button>
        <Link href="/projects" className="flex items-center gap-2">
          <div className="h-6 w-6 rounded bg-gradient-to-br from-accent-amber to-accent-teal" />
          <span className="hidden text-sm font-semibold lg:inline">Цифровой двойник</span>
        </Link>
        <span className="truncate text-sm text-text-secondary">/ {project.name}</span>
        <div className="ml-2 hidden rounded-md border border-bg-border bg-bg-panel2 p-0.5 sm:flex">
          <button onClick={() => setPlanView(false)} className={`flex items-center gap-1 rounded px-2.5 py-1 text-xs ${!planView ? 'bg-accent-teal text-bg' : 'text-text-secondary'}`}>
            {Icons.cube} 3D
          </button>
          <button onClick={() => setPlanView(true)} className={`flex items-center gap-1 rounded px-2.5 py-1 text-xs ${planView ? 'bg-accent-teal text-bg' : 'text-text-secondary'}`}>
            {Icons.plan} План 2D
          </button>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <button onClick={() => setUploadOpen(true)} className="flex items-center gap-1 rounded-md bg-accent-teal px-2.5 py-1.5 text-xs font-semibold text-bg hover:bg-accent-teal/90">
            {Icons.upload}<span className="hidden sm:inline">Загрузить</span>
          </button>
          <Link href={`/twin/${projectId}/dashboard`} className="rounded-md border border-bg-border px-2.5 py-1.5 text-xs text-text-secondary hover:text-text-primary">
            Дашборд
          </Link>
          <Link href={`/projects/${projectId}`} className="hidden rounded-md border border-bg-border px-2.5 py-1.5 text-xs text-text-secondary hover:text-text-primary md:inline">
            Геология
          </Link>
          <span className="hidden text-xs text-text-secondary lg:inline">{user?.full_name ?? user?.email}</span>
          <button
            onClick={() => { clearAuth(); router.push('/login'); }}
            className="rounded-md border border-bg-border px-2.5 py-1.5 text-xs text-text-secondary hover:text-text-primary"
          >
            Выйти
          </button>
        </div>
      </header>

      <div className="relative flex min-h-0 flex-1">
        {/* Panel switcher rail */}
        <nav className="z-30 hidden w-12 shrink-0 flex-col items-center gap-1 border-r border-bg-border bg-bg-panel py-2 sm:flex">
          {PANELS.map((p) => (
            <IconButton
              key={p.key}
              title={p.title}
              active={panelOpen && panel === p.key}
              onClick={() => (panelOpen && panel === p.key ? setPanelOpen(false) : setPanel(p.key))}
            >
              {p.icon}
            </IconButton>
          ))}
        </nav>

        {/* Side panel (drawer on mobile) */}
        {panelOpen && (
          <section className="absolute inset-y-0 left-0 z-30 flex w-[min(22rem,100%)] flex-col border-r border-bg-border bg-bg-panel sm:static sm:w-80">
            <div className="flex items-center gap-1 overflow-x-auto border-b border-bg-border px-2 py-1.5 sm:hidden">
              {PANELS.map((p) => (
                <IconButton key={p.key} title={p.title} active={panel === p.key} onClick={() => setPanel(p.key)}>
                  {p.icon}
                </IconButton>
              ))}
              <IconButton title="Закрыть" className="ml-auto" onClick={() => setPanelOpen(false)}>{Icons.close}</IconButton>
            </div>
            <div className="border-b border-bg-border px-3 py-2 text-sm font-semibold">{panelTitle}</div>
            <div className="min-h-0 flex-1 overflow-y-auto p-3">
              {panel === 'layers' && (
                <LayersPanel onChanged={() => loadAssets()} mapLayers={mapLayers} pendingFiles={[...processing, ...failed]} />
              )}
              {panel === 'search' && <SearchPanel />}
              {panel === 'annotations' && <AnnotationsPanel projectId={projectId} onChanged={() => loadAnnotations()} />}
              {panel === 'documents' && <DocumentsPanel projectId={projectId} />}
              {panel === 'compare' && <ComparePanel />}
              {panel === 'schedule' && <SchedulePanel projectId={projectId} />}
              {panel === 'issues' && <IssuesPanel projectId={projectId} />}
              {panel === 'analysis' && <AnalysisPanel projectId={projectId} onAssetsChanged={loadAssets} />}
              {panel === 'autodesk' && <AutodeskPanel projectId={projectId} onImported={loadAssets} />}
              {panel === 'settings' && <SettingsPanel project={project} onSaved={setProject} />}
            </div>
          </section>
        )}

        <main className="relative min-w-0 flex-1">
          <CesiumViewer mapLayers={mapLayers} crs={crs} groundHeight={groundHeight} onCursor={setCursor} />
          <ToolPalette clipOpen={clipOpen} onToggleClip={() => setClipOpen(!clipOpen)} />
          {clipOpen ? <ClipPanel heightRange={heightRange} /> : <MeasurementCard />}
          <TimelineBar />
          <ProfileChart />
          <PropertiesPanel />
          <div className="pointer-events-none absolute bottom-0 left-0 right-0 z-10 flex justify-between gap-2 bg-gradient-to-t from-bg/90 to-transparent px-3 pb-1.5 pt-4 text-[11px] text-text-secondary">
            <span className="truncate">{cursor ?? ' '}</span>
            <span className="hidden shrink-0 sm:inline">СК проекта: {crs.label}</span>
          </div>
        </main>
      </div>

      {uploadOpen && <UploadDialog project={project} onClose={() => setUploadOpen(false)} onUploaded={() => loadAssets()} />}
    </div>
  );
}

export default function TwinPage({ params }: { params: { projectId: string } }) {
  return (
    <AuthGuard>
      <TwinWorkspace projectId={params.projectId} />
    </AuthGuard>
  );
}
