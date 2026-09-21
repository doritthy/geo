'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import AuthGuard from '@/components/AuthGuard';
import TopNav from '@/components/workspace/TopNav';
import LeftPanel from '@/components/workspace/LeftPanel';
import RightPanel from '@/components/workspace/RightPanel';
import ViewportContainer from '@/components/workspace/ViewportContainer';
import IngestDialog from '@/components/workspace/IngestDialog';
import { api, ApiError } from '@/lib/api';
import { useWorkspaceStore } from '@/lib/store';
import type { Project, WellSummary, GridDetail, SurfaceDetail, MapLayerSummary } from '@/lib/types';

function WorkspaceInner({ projectId }: { projectId: string }) {
  const router = useRouter();
  const setActiveProjectId = useWorkspaceStore((s) => s.setActiveProjectId);

  const [project, setProject] = useState<Project | null>(null);
  const [wells, setWells] = useState<WellSummary[]>([]);
  const [gridDetails, setGridDetails] = useState<GridDetail[]>([]);
  const [surfaceDetails, setSurfaceDetails] = useState<SurfaceDetail[]>([]);
  const [mapLayers, setMapLayers] = useState<MapLayerSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const loadAll = useCallback(async () => {
    try {
      const [proj, wellList, gridSummaries, surfaceSummaries, layers] = await Promise.all([
        api.getProject(projectId),
        api.listWells(projectId),
        api.listGrids(projectId),
        api.listSurfaces(projectId),
        api.listMapLayers(projectId),
      ]);
      setProject(proj);
      setWells(wellList);
      setMapLayers(layers);

      const [grids, surfaces] = await Promise.all([
        Promise.all(gridSummaries.map((g) => api.getGrid(g.id))),
        Promise.all(surfaceSummaries.map((s) => api.getSurface(s.id))),
      ]);
      setGridDetails(grids);
      setSurfaceDetails(surfaces);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to load project data.');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    setActiveProjectId(projectId);
    loadAll();
    return () => setActiveProjectId(null);
  }, [projectId, setActiveProjectId, loadAll]);

  if (error) {
    return (
      <div className="flex h-screen w-screen flex-col items-center justify-center gap-3 bg-bg text-text-secondary">
        <p>{error}</p>
        <button onClick={() => router.push('/projects')} className="rounded-md border border-bg-border px-4 py-2 text-sm hover:text-text-primary">
          Back to projects
        </button>
      </div>
    );
  }

  if (loading || !project) {
    return <div className="flex h-screen w-screen items-center justify-center bg-bg text-text-secondary">Loading workspace…</div>;
  }

  const bounds =
    gridDetails.length > 0
      ? gridDetails[0].bounds
      : { minX: -500, minY: -500, minZ: -500, maxX: 500, maxY: 500, maxZ: 0 };

  return (
    <div className="flex h-screen flex-col bg-bg">
      <TopNav project={project} wells={wells} />
      <div className="flex min-h-0 flex-1">
        <LeftPanel project={project} wells={wells} gridDetails={gridDetails} surfaces={surfaceDetails} bounds={bounds} />
        <main className="min-w-0 flex-1">
          <ViewportContainer project={project} wells={wells} gridDetails={gridDetails} surfaceDetails={surfaceDetails} mapLayers={mapLayers} />
        </main>
        <RightPanel />
      </div>
      <IngestDialog projectId={projectId} onIngested={loadAll} />
    </div>
  );
}

export default function ProjectWorkspacePage({ params }: { params: { projectId: string } }) {
  return (
    <AuthGuard>
      <WorkspaceInner projectId={params.projectId} />
    </AuthGuard>
  );
}
