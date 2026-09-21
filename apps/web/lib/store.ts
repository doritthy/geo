import { create } from 'zustand';
import type { ColormapName } from './colormaps';
import type { GridSampleResult } from './types';

export type ViewMode = '3d' | '2d' | 'map';
export type CameraPreset = 'top' | 'north' | 'south' | 'east' | 'west' | 'flip-z';
export type ProjectionMode = 'perspective' | 'orthographic';

export interface LayerVisibility {
  wells: boolean;
  grids: boolean;
  surfaces: boolean;
  mapLayers: boolean;
}

export interface PointInspection {
  x: number;
  y: number;
  z: number;
  tvd?: number;
  gridId?: string;
  gridName?: string;
  propertyName?: string;
  sample?: GridSampleResult;
  wellId?: string;
  wellName?: string;
  extraValues?: Record<string, number | null>;
}

export interface ClipPlaneState {
  enabled: boolean;
  axis: 'x' | 'y' | 'z';
  value: number; // world-space plane constant along the axis
  flipped: boolean;
}

interface WorkspaceState {
  activeProjectId: string | null;
  setActiveProjectId: (id: string | null) => void;

  viewMode: ViewMode;
  setViewMode: (m: ViewMode) => void;

  layerVisibility: LayerVisibility;
  toggleLayer: (layer: keyof LayerVisibility) => void;

  activeGridId: string | null;
  setActiveGridId: (id: string | null) => void;
  activeProperty: string | null;
  setActiveProperty: (name: string | null) => void;

  colormap: ColormapName;
  setColormap: (c: ColormapName) => void;

  valueRange: { min: number; max: number } | null;
  setValueRange: (r: { min: number; max: number } | null) => void;
  threshold: { min: number; max: number } | null;
  setThreshold: (r: { min: number; max: number } | null) => void;

  zExaggeration: number;
  setZExaggeration: (z: number) => void;

  lod: number;
  setLod: (lod: number) => void;

  cameraPreset: CameraPreset | null;
  setCameraPreset: (p: CameraPreset | null) => void;
  projectionMode: ProjectionMode;
  setProjectionMode: (p: ProjectionMode) => void;

  clipPlanes: { x: ClipPlaneState; y: ClipPlaneState; z: ClipPlaneState };
  setClipPlane: (axis: 'x' | 'y' | 'z', patch: Partial<ClipPlaneState>) => void;

  selectedWellId: string | null;
  setSelectedWellId: (id: string | null) => void;

  pointInspection: PointInspection | null;
  setPointInspection: (p: PointInspection | null) => void;

  ingestDialogOpen: boolean;
  setIngestDialogOpen: (open: boolean) => void;
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  activeProjectId: null,
  setActiveProjectId: (id) => set({ activeProjectId: id }),

  viewMode: '3d',
  setViewMode: (m) => set({ viewMode: m }),

  layerVisibility: { wells: true, grids: true, surfaces: true, mapLayers: true },
  toggleLayer: (layer) =>
    set((s) => ({ layerVisibility: { ...s.layerVisibility, [layer]: !s.layerVisibility[layer] } })),

  activeGridId: null,
  setActiveGridId: (id) => set({ activeGridId: id, activeProperty: null, valueRange: null, threshold: null }),
  activeProperty: null,
  setActiveProperty: (name) => set({ activeProperty: name }),

  colormap: 'viridis',
  setColormap: (c) => set({ colormap: c }),

  valueRange: null,
  setValueRange: (r) => set({ valueRange: r }),
  threshold: null,
  setThreshold: (r) => set({ threshold: r }),

  zExaggeration: 1,
  setZExaggeration: (z) => set({ zExaggeration: z }),

  lod: 0,
  setLod: (lod) => set({ lod }),

  cameraPreset: null,
  setCameraPreset: (p) => set({ cameraPreset: p }),
  projectionMode: 'perspective',
  setProjectionMode: (p) => set({ projectionMode: p }),

  clipPlanes: {
    x: { enabled: false, axis: 'x', value: 0, flipped: false },
    y: { enabled: false, axis: 'y', value: 0, flipped: false },
    z: { enabled: false, axis: 'z', value: 0, flipped: false },
  },
  setClipPlane: (axis, patch) =>
    set((s) => ({ clipPlanes: { ...s.clipPlanes, [axis]: { ...s.clipPlanes[axis], ...patch } } })),

  selectedWellId: null,
  setSelectedWellId: (id) => set({ selectedWellId: id }),

  pointInspection: null,
  setPointInspection: (p) => set({ pointInspection: p }),

  ingestDialogOpen: false,
  setIngestDialogOpen: (open) => set({ ingestDialogOpen: open }),
}));
