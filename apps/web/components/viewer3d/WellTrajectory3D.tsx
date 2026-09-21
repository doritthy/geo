'use client';

import { useEffect, useMemo, useState } from 'react';
import * as THREE from 'three';
import { Html } from '@react-three/drei';
import { useWorkspaceStore } from '@/lib/store';
import { api } from '@/lib/api';
import { decodeLogData } from '@/lib/binary';
import { makeColorScale } from '@/lib/colormaps';
import { buildClippingPlanes } from './clipPlanes';
import { handleWellClick } from './PointInspector';
import type { TrajectoryPoint, WellMarker, WellSummary } from '@/lib/types';

const ROLE_COLORS: Record<string, string> = {
  producer: '#2DD4BF', // teal
  injector: '#3B82F6', // blue
  observation: '#F5A524', // amber
  exploration: '#A78BFA', // violet
};

const MARKER_LABELS: Record<string, string> = {
  KOP: 'KOP',
  RESERVOIR_ENTRY: 'Reservoir Entry',
  LANDING: 'Landing',
  TD: 'TD',
  CUSTOM: 'Marker',
};

function tubeRadiusForScene(radiusHint: number): number {
  return Math.max(radiusHint * 0.004, 1);
}

export default function WellTrajectory3D({
  well,
  visible,
  sceneRadius,
  showLogCurve = true,
}: {
  well: WellSummary;
  visible: boolean;
  sceneRadius: number;
  showLogCurve?: boolean;
}) {
  const clipPlanes = useWorkspaceStore((s) => s.clipPlanes);
  const zExaggeration = useWorkspaceStore((s) => s.zExaggeration);
  const selectedWellId = useWorkspaceStore((s) => s.selectedWellId);

  const [trajectory, setTrajectory] = useState<TrajectoryPoint[] | null>(null);
  const [markers, setMarkers] = useState<WellMarker[]>([]);
  const [logCurve, setLogCurve] = useState<{ depth: Float32Array; value: Float32Array; min: number; max: number; unit: string | null; name: string } | null>(
    null
  );

  useEffect(() => {
    let cancelled = false;
    api
      .getWellTrajectory(well.id)
      .then((pts) => !cancelled && setTrajectory(pts))
      .catch((err) => console.error('Failed to load well trajectory', err));
    api
      .getWellMarkers(well.id)
      .then((m) => !cancelled && setMarkers(m))
      .catch((err) => console.error('Failed to load well markers', err));
    return () => {
      cancelled = true;
    };
  }, [well.id]);

  useEffect(() => {
    if (!showLogCurve) return;
    let cancelled = false;
    api
      .getWellLogs(well.id)
      .then(async (logs) => {
        if (cancelled || logs.length === 0) return;
        const preferred = logs.find((l) => l.curve_name.toUpperCase() === 'GR') ?? logs[0];
        const buf = await api.getWellLogData(well.id, preferred.id);
        if (cancelled) return;
        const decoded = decodeLogData(buf, preferred.sample_count);
        setLogCurve({
          depth: decoded.depth,
          value: decoded.value,
          min: preferred.min_value,
          max: preferred.max_value,
          unit: preferred.unit,
          name: preferred.curve_name,
        });
      })
      .catch((err) => console.error('Failed to load well log data', err));
    return () => {
      cancelled = true;
    };
  }, [well.id, showLogCurve]);

  const points = useMemo(
    () => (trajectory ?? []).map((p) => new THREE.Vector3(p.x, p.y, p.z)),
    [trajectory]
  );

  const clippingPlanes = useMemo(() => buildClippingPlanes(clipPlanes), [clipPlanes]);
  const isSelected = selectedWellId === well.id;
  const baseColor = ROLE_COLORS[well.well_type] ?? '#94A3B8';

  const tubeGeometry = useMemo(() => {
    if (points.length < 2) return null;
    const curve = new THREE.CatmullRomCurve3(points, false, 'catmullrom', 0.15);
    const segments = Math.min(400, Math.max(points.length * 2, 8));
    const radius = tubeRadiusForScene(sceneRadius);
    return new THREE.TubeGeometry(curve, segments, radius, 8, false);
  }, [points, sceneRadius]);

  const material = useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        color: baseColor,
        emissive: isSelected ? new THREE.Color(baseColor).multiplyScalar(0.4) : new THREE.Color(0x000000),
        metalness: 0.2,
        roughness: 0.5,
      }),
    [baseColor, isSelected]
  );

  useEffect(() => {
    material.clippingPlanes = clippingPlanes;
    material.needsUpdate = true;
  }, [clippingPlanes, material]);
  useEffect(() => () => material.dispose(), [material]);
  useEffect(() => () => tubeGeometry?.dispose(), [tubeGeometry]);

  // Small offset "ribbon" (line) rendering a log curve alongside the wellbore,
  // colored by value. Offset perpendicular to the trajectory's local tangent
  // by a small, scene-scaled distance so it reads as a ribbon without
  // occluding the trajectory tube itself.
  const logLine = useMemo(() => {
    if (!logCurve || !trajectory || trajectory.length < 2) return null;
    const offset = tubeRadiusForScene(sceneRadius) * 6;
    const colorScale = makeColorScale('jet', logCurve.min, logCurve.max);
    const positions: number[] = [];
    const colors: number[] = [];

    // Trajectory is ordered by seq/md; find the bracketing trajectory points
    // for each log sample's depth (measured depth) and interpolate x,y,z.
    let segIdx = 0;
    for (let s = 0; s < logCurve.depth.length; s++) {
      const md = logCurve.depth[s];
      while (segIdx < trajectory.length - 2 && trajectory[segIdx + 1].md < md) segIdx++;
      const p0 = trajectory[segIdx];
      const p1 = trajectory[Math.min(segIdx + 1, trajectory.length - 1)];
      const span = p1.md - p0.md || 1;
      const t = Math.min(1, Math.max(0, (md - p0.md) / span));
      const x = p0.x + (p1.x - p0.x) * t;
      const y = p0.y + (p1.y - p0.y) * t;
      const z = p0.z + (p1.z - p0.z) * t;
      positions.push(x + offset, y, z);
      const [r, g, b] = colorScale(logCurve.value[s]);
      colors.push(r, g, b);
    }

    const geom = new THREE.BufferGeometry();
    geom.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geom.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
    return geom;
  }, [logCurve, trajectory, sceneRadius]);

  if (!visible || points.length < 2) return null;

  return (
    <group
      onClick={(e) => {
        e.stopPropagation();
        const intersectPoint = e.point;
        handleWellClick({
          wellId: well.id,
          wellName: well.name,
          x: intersectPoint.x,
          y: intersectPoint.y,
          z: zExaggeration !== 0 ? intersectPoint.z / zExaggeration : intersectPoint.z,
        });
      }}
    >
      {tubeGeometry && <mesh geometry={tubeGeometry} material={material} />}

      {logLine && (
        <lineSegments>
          <primitive object={logLine} attach="geometry" />
          <lineBasicMaterial vertexColors linewidth={1} clippingPlanes={clippingPlanes} />
        </lineSegments>
      )}

      {markers.map((m) =>
        m.x !== null && m.y !== null && m.z !== null ? (
          <group key={m.id} position={[m.x, m.y, m.z]}>
            <mesh>
              <sphereGeometry args={[tubeRadiusForScene(sceneRadius) * 2, 12, 12]} />
              <meshBasicMaterial color="#F5A524" />
            </mesh>
            <Html distanceFactor={sceneRadius * 0.6} style={{ pointerEvents: 'none' }}>
              <div className="whitespace-nowrap rounded bg-bg-panel/90 px-1.5 py-0.5 text-[10px] font-medium text-text-primary shadow">
                {m.label || MARKER_LABELS[m.marker_type] || m.marker_type}
              </div>
            </Html>
          </group>
        ) : null
      )}

      <Html
        position={[points[0].x, points[0].y, points[0].z]}
        distanceFactor={sceneRadius * 0.6}
        style={{ pointerEvents: 'none' }}
      >
        <div className="whitespace-nowrap rounded border border-bg-border bg-bg-panel/90 px-1.5 py-0.5 text-[10px] font-semibold text-text-primary shadow">
          {well.name}
        </div>
      </Html>
    </group>
  );
}
