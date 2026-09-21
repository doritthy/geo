'use client';

import { useEffect, useMemo } from 'react';
import dynamic from 'next/dynamic';
import { useWorkspaceStore } from '@/lib/store';
import type { Project, WellSummary, GridDetail, SurfaceDetail, MapLayerSummary } from '@/lib/types';
import type { SceneBounds } from '@/components/viewer3d/Viewer3D';
import GridInstancedMesh from '@/components/viewer3d/GridInstancedMesh';
import SurfaceMesh from '@/components/viewer3d/SurfaceMesh';
import WellTrajectory3D from '@/components/viewer3d/WellTrajectory3D';
import ColorLegend from '@/components/viewer3d/ColorLegend';

// three.js/leaflet touch `window` at import time, so both heavy viewport
// implementations are loaded client-side only.
const Viewer3D = dynamic(() => import('@/components/viewer3d/Viewer3D'), { ssr: false });
const Map2D = dynamic(() => import('@/components/map2d/Map2D'), { ssr: false });

function unionBounds(candidates: (SceneBounds | null)[]): SceneBounds {
  const valid = candidates.filter((b): b is SceneBounds => !!b);
  if (valid.length === 0) return { minX: -500, minY: -500, minZ: -500, maxX: 500, maxY: 500, maxZ: 0 };
  return valid.reduce((acc, b) => ({
    minX: Math.min(acc.minX, b.minX),
    minY: Math.min(acc.minY, b.minY),
    minZ: Math.min(acc.minZ, b.minZ),
    maxX: Math.max(acc.maxX, b.maxX),
    maxY: Math.max(acc.maxY, b.maxY),
    maxZ: Math.max(acc.maxZ, b.maxZ),
  }));
}

export default function ViewportContainer({
  project,
  wells,
  gridDetails,
  surfaceDetails,
  mapLayers,
}: {
  project: Project;
  wells: WellSummary[];
  gridDetails: GridDetail[];
  surfaceDetails: SurfaceDetail[];
  mapLayers: MapLayerSummary[];
}) {
  const viewMode = useWorkspaceStore((s) => s.viewMode);
  const layerVisibility = useWorkspaceStore((s) => s.layerVisibility);
  const setProjectionMode = useWorkspaceStore((s) => s.setProjectionMode);
  const setCameraPreset = useWorkspaceStore((s) => s.setCameraPreset);

  useEffect(() => {
    if (viewMode === '2d') {
      setProjectionMode('orthographic');
      setCameraPreset('top');
    } else if (viewMode === '3d') {
      setProjectionMode('perspective');
    }
  }, [viewMode, setProjectionMode, setCameraPreset]);

  const bounds = useMemo<SceneBounds>(() => {
    const gridBounds = gridDetails.map((g) => g.bounds);
    const surfaceBoundsList: SceneBounds[] = surfaceDetails.map((s) => ({
      minX: s.origin_x,
      minY: s.origin_y,
      minZ: s.min_z,
      maxX: s.origin_x + s.cols * s.cell_size_x,
      maxY: s.origin_y + s.rows * s.cell_size_y,
      maxZ: s.max_z,
    }));
    const wellBounds: SceneBounds | null =
      wells.length > 0
        ? {
            minX: Math.min(...wells.map((w) => w.surface_x)),
            minY: Math.min(...wells.map((w) => w.surface_y)),
            minZ: -Math.max(...wells.map((w) => w.total_depth ?? 0), 100),
            maxX: Math.max(...wells.map((w) => w.surface_x)),
            maxY: Math.max(...wells.map((w) => w.surface_y)),
            maxZ: 0,
          }
        : null;
    return unionBounds([...gridBounds, ...surfaceBoundsList, wellBounds]);
  }, [gridDetails, surfaceDetails, wells]);

  const sceneRadius = Math.max(bounds.maxX - bounds.minX, bounds.maxY - bounds.minY, 100);

  if (viewMode === 'map') {
    return <Map2D project={project} wells={wells} mapLayers={mapLayers} />;
  }

  return (
    <div className="relative h-full w-full">
      <Viewer3D bounds={bounds}>
        {layerVisibility.grids &&
          gridDetails.map((g) => <GridInstancedMesh key={g.id} gridId={g.id} gridDetail={g} visible />)}
        {layerVisibility.surfaces &&
          surfaceDetails.map((s) => <SurfaceMesh key={s.id} surfaceId={s.id} surfaceDetail={s} visible />)}
        {layerVisibility.wells &&
          wells.map((w) => (
            <WellTrajectory3D key={w.id} well={w} visible sceneRadius={sceneRadius} showLogCurve={viewMode === '3d'} />
          ))}
      </Viewer3D>
      <ColorLegend />
    </div>
  );
}
