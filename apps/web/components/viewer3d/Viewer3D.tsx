'use client';

import { Canvas, useThree } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import { useEffect, useMemo, useRef } from 'react';
import * as THREE from 'three';
import { useWorkspaceStore, type CameraPreset } from '@/lib/store';

export interface SceneBounds {
  minX: number;
  minY: number;
  minZ: number;
  maxX: number;
  maxY: number;
  maxZ: number;
}

export const DEFAULT_BOUNDS: SceneBounds = { minX: -500, minY: -500, minZ: -500, maxX: 500, maxY: 500, maxZ: 0 };

function boundsCenter(b: SceneBounds): THREE.Vector3 {
  return new THREE.Vector3((b.minX + b.maxX) / 2, (b.minY + b.maxY) / 2, (b.minZ + b.maxZ) / 2);
}

function boundsRadius(b: SceneBounds): number {
  const dx = b.maxX - b.minX;
  const dy = b.maxY - b.minY;
  const dz = b.maxZ - b.minZ;
  return Math.max(dx, dy, dz, 10) * 1.15;
}

// Swaps between a perspective and orthographic camera, applies camera
// presets (Top/North/South/East/West/Flip-Z), and drives OrbitControls.
// Z is treated as the vertical axis throughout the viewer (camera `up` is
// (0,0,1)) since grid/surface/well data is naturally X,Y horizontal and Z
// depth/elevation.
function CameraRig({ bounds }: { bounds: SceneBounds }) {
  const { size, set, camera } = useThree();
  const controlsRef = useRef<any>(null);
  const projectionMode = useWorkspaceStore((s) => s.projectionMode);
  const cameraPreset = useWorkspaceStore((s) => s.cameraPreset);
  const setCameraPreset = useWorkspaceStore((s) => s.setCameraPreset);

  const center = useMemo(() => boundsCenter(bounds), [bounds]);
  const radius = useMemo(() => boundsRadius(bounds), [bounds]);

  useEffect(() => {
    const aspect = size.width / Math.max(1, size.height);
    let cam: THREE.PerspectiveCamera | THREE.OrthographicCamera;
    if (projectionMode === 'perspective') {
      cam = new THREE.PerspectiveCamera(50, aspect, Math.max(radius / 500, 0.05), radius * 40);
    } else {
      const viewSize = radius;
      cam = new THREE.OrthographicCamera(
        -viewSize * aspect,
        viewSize * aspect,
        viewSize,
        -viewSize,
        -radius * 40,
        radius * 40
      );
    }
    cam.up.set(0, 0, 1);
    cam.position.set(center.x + radius * 0.8, center.y - radius * 1.2, center.z + radius * 0.7);
    cam.lookAt(center);
    set({ camera: cam });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectionMode, size.width, size.height, radius, center.x, center.y, center.z]);

  useEffect(() => {
    if (!cameraPreset) return;
    const cam = camera as THREE.PerspectiveCamera | THREE.OrthographicCamera;
    const presets: Record<CameraPreset, { pos: THREE.Vector3; up: THREE.Vector3 }> = {
      top: { pos: new THREE.Vector3(center.x, center.y + 0.0001, center.z + radius * 2.2), up: new THREE.Vector3(0, 1, 0) },
      'flip-z': {
        pos: new THREE.Vector3(center.x, center.y + 0.0001, center.z - radius * 2.2),
        up: new THREE.Vector3(0, 1, 0),
      },
      north: { pos: new THREE.Vector3(center.x, center.y + radius * 2.2, center.z), up: new THREE.Vector3(0, 0, 1) },
      south: { pos: new THREE.Vector3(center.x, center.y - radius * 2.2, center.z), up: new THREE.Vector3(0, 0, 1) },
      east: { pos: new THREE.Vector3(center.x + radius * 2.2, center.y, center.z), up: new THREE.Vector3(0, 0, 1) },
      west: { pos: new THREE.Vector3(center.x - radius * 2.2, center.y, center.z), up: new THREE.Vector3(0, 0, 1) },
    };
    const p = presets[cameraPreset];
    if (p) {
      cam.up.copy(p.up);
      cam.position.copy(p.pos);
      cam.lookAt(center);
      if (controlsRef.current) {
        controlsRef.current.target.copy(center);
        controlsRef.current.update();
      }
    }
    setCameraPreset(null);
  }, [cameraPreset, camera, center, radius, setCameraPreset]);

  return (
    <OrbitControls
      ref={controlsRef}
      makeDefault
      target={[center.x, center.y, center.z]}
      enableDamping
      dampingFactor={0.08}
      minDistance={radius * 0.01}
      maxDistance={radius * 10}
    />
  );
}

const PRESET_BUTTONS: { key: CameraPreset; label: string }[] = [
  { key: 'top', label: 'Top' },
  { key: 'north', label: 'North' },
  { key: 'south', label: 'South' },
  { key: 'east', label: 'East' },
  { key: 'west', label: 'West' },
  { key: 'flip-z', label: 'Flip Z' },
];

function ViewerToolbar() {
  const setCameraPreset = useWorkspaceStore((s) => s.setCameraPreset);
  const projectionMode = useWorkspaceStore((s) => s.projectionMode);
  const setProjectionMode = useWorkspaceStore((s) => s.setProjectionMode);
  const zExaggeration = useWorkspaceStore((s) => s.zExaggeration);
  const setZExaggeration = useWorkspaceStore((s) => s.setZExaggeration);

  return (
    <div className="pointer-events-none absolute right-3 top-3 z-10 flex flex-col items-end gap-2">
      <div className="pointer-events-auto flex gap-1 rounded-lg border border-bg-border bg-bg-panel/90 p-1 backdrop-blur">
        {PRESET_BUTTONS.map((p) => (
          <button
            key={p.key}
            onClick={() => setCameraPreset(p.key)}
            className="rounded px-2 py-1 text-[11px] font-medium text-text-secondary hover:bg-bg-panel2 hover:text-text-primary"
          >
            {p.label}
          </button>
        ))}
      </div>
      <div className="pointer-events-auto flex items-center gap-2 rounded-lg border border-bg-border bg-bg-panel/90 p-1.5 backdrop-blur">
        <button
          onClick={() => setProjectionMode(projectionMode === 'perspective' ? 'orthographic' : 'perspective')}
          className="rounded border border-bg-border px-2 py-1 text-[11px] font-medium text-text-secondary hover:text-text-primary"
        >
          {projectionMode === 'perspective' ? 'Perspective' : 'Orthographic'}
        </button>
        <div className="flex items-center gap-1.5 pl-1">
          <span className="text-[10px] text-text-muted">Z×</span>
          <input
            type="range"
            min={0.1}
            max={10}
            step={0.1}
            value={zExaggeration}
            onChange={(e) => setZExaggeration(Number(e.target.value))}
            className="w-24 accent-accent-teal"
          />
          <span className="w-8 text-right text-[10px] text-text-secondary">{zExaggeration.toFixed(1)}</span>
        </div>
      </div>
    </div>
  );
}

export default function Viewer3D({
  bounds = DEFAULT_BOUNDS,
  children,
}: {
  bounds?: SceneBounds;
  children: React.ReactNode;
}) {
  const zExaggeration = useWorkspaceStore((s) => s.zExaggeration);
  const size = useMemo(() => Math.max(bounds.maxX - bounds.minX, bounds.maxY - bounds.minY, 100), [bounds]);

  return (
    <div className="relative h-full w-full">
      <Canvas
        gl={{ localClippingEnabled: true, antialias: true }}
        onCreated={({ gl }) => gl.setClearColor('#0B0F19')}
        style={{ background: '#0B0F19' }}
      >
        <CameraRig bounds={bounds} />
        <ambientLight intensity={0.75} />
        <directionalLight position={[1, -1, 2]} intensity={0.55} />
        <directionalLight position={[-1, 1, 1]} intensity={0.25} />
        <group scale={[1, 1, zExaggeration]}>{children}</group>
        <axesHelper args={[size * 0.12]} />
        <gridHelper args={[size * 2, 20, '#232E42', '#161F2E']} rotation={[Math.PI / 2, 0, 0]} />
      </Canvas>
      <ViewerToolbar />
    </div>
  );
}
