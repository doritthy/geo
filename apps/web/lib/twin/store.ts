import { create } from 'zustand';
import type { Annotation, BimElementSummary, CompareResult, Issue, SceneAsset } from './types';

export type ToolMode =
  | 'select'
  | 'point'
  | 'distance'
  | 'area'
  | 'height'
  | 'angle'
  | 'volume'
  | 'annotate'
  | 'issue'
  | 'profile';

export type SidePanel = 'layers' | 'search' | 'annotations' | 'issues' | 'schedule' | 'documents' | 'compare' | 'analysis' | 'autodesk' | 'settings';

export interface Selection {
  kind: 'element' | 'feature' | 'annotation' | 'issue';
  issueId?: string;
  assetId?: string;
  globalId?: string;
  title?: string;
  properties?: Record<string, unknown>;
  annotationId?: string;
}

export interface MeasurementResult {
  tool: ToolMode;
  lines: { label: string; value: string }[];
}

export interface ClipState {
  horizontal: boolean;
  height: number; // absolute ellipsoidal height of the cut plane, m
  vertical: boolean;
  heading: number; // degrees, direction of the vertical plane normal
  offset: number; // metres from the scene centre along the normal
}

interface TwinState {
  assets: SceneAsset[];
  setAssets: (a: SceneAsset[]) => void;

  visible: Record<string, boolean>;
  toggleVisible: (assetId: string, value?: boolean) => void;
  opacity: Record<string, number>;
  setOpacity: (assetId: string, value: number) => void;
  hiddenTypes: Record<string, string[]>; // assetId -> hidden IFC classes
  toggleType: (assetId: string, ifcType: string) => void;
  pointSize: number;
  setPointSize: (v: number) => void;

  mapLayerVisible: Record<string, boolean>;
  toggleMapLayer: (id: string) => void;

  tool: ToolMode;
  setTool: (t: ToolMode) => void;
  measurement: MeasurementResult | null;
  setMeasurement: (m: MeasurementResult | null) => void;
  clearMeasurementsTick: number;
  clearMeasurements: () => void;

  selection: Selection | null;
  setSelection: (s: Selection | null) => void;

  annotations: Annotation[];
  setAnnotations: (a: Annotation[]) => void;
  pendingAnnotation: { longitude: number; latitude: number; height: number; assetId?: string; globalId?: string } | null;
  setPendingAnnotation: (p: TwinState['pendingAnnotation']) => void;

  panel: SidePanel;
  setPanel: (p: SidePanel) => void;
  panelOpen: boolean;
  setPanelOpen: (o: boolean) => void;

  compare: (CompareResult & { baseName: string; otherName: string }) | null;
  setCompare: (c: TwinState['compare']) => void;

  timelineEnabled: boolean;
  timelineDate: string | null;
  setTimeline: (enabled: boolean, date?: string | null) => void;

  planView: boolean;
  setPlanView: (v: boolean) => void;
  globeTranslucent: boolean;
  setGlobeTranslucent: (v: boolean) => void;

  clip: ClipState;
  setClip: (patch: Partial<ClipState>) => void;

  flyTo: {
    assetId?: string;
    globalId?: string;
    bbox?: { min: number[]; max: number[] };
    annotationId?: string;
    issueId?: string;
    point?: { longitude: number; latitude: number; height: number };
    nonce: number;
  } | null;
  requestFlyTo: (target: Omit<NonNullable<TwinState['flyTo']>, 'nonce'>) => void;

  highlight: BimElementSummary[] | null;
  setHighlight: (h: BimElementSummary[] | null) => void;

  issues: Issue[];
  setIssues: (i: Issue[]) => void;
  /** Point picked with the 'issue' tool, consumed by the issues panel. */
  pendingIssuePoint: { longitude: number; latitude: number; height: number; assetId?: string; globalId?: string } | null;
  setPendingIssuePoint: (p: TwinState['pendingIssuePoint']) => void;
  openIssueId: string | null;
  setOpenIssueId: (id: string | null) => void;

  profileLine: { a: [number, number]; b: [number, number] } | null;
  setProfileLine: (p: TwinState['profileLine']) => void;

  /** Per-element colours (CSS) for one BIM asset, e.g. deviation classes. */
  elementColors: { assetId: string; colors: Record<string, string> } | null;
  setElementColors: (c: TwinState['elementColors']) => void;

  /** Bumped when documents/annotations change so detail views refetch. */
  dataTick: number;
  bumpData: () => void;
}

export const useTwinStore = create<TwinState>((set) => ({
  assets: [],
  setAssets: (assets) =>
    set((s) => {
      // New layers start visible, except superseded versions of a model
      // (they would z-fight with the latest one).
      const latest = new Map<string, number>();
      for (const a of assets) latest.set(a.version_group, Math.max(latest.get(a.version_group) ?? 0, a.version));
      const visible = { ...s.visible };
      for (const a of assets) {
        if (a.id in visible) continue;
        // Analysis results (deviation maps) are opened from the analysis panel.
        visible[a.id] = a.version === latest.get(a.version_group) && !a.stats.analysis_id;
      }
      return { assets, visible };
    }),

  visible: {},
  toggleVisible: (id, value) => set((s) => ({ visible: { ...s.visible, [id]: value ?? !s.visible[id] } })),
  opacity: {},
  setOpacity: (id, value) => set((s) => ({ opacity: { ...s.opacity, [id]: value } })),
  hiddenTypes: {},
  toggleType: (id, t) =>
    set((s) => {
      const cur = s.hiddenTypes[id] ?? [];
      const next = cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t];
      return { hiddenTypes: { ...s.hiddenTypes, [id]: next } };
    }),
  pointSize: 3,
  setPointSize: (pointSize) => set({ pointSize }),

  mapLayerVisible: {},
  toggleMapLayer: (id) => set((s) => ({ mapLayerVisible: { ...s.mapLayerVisible, [id]: !(s.mapLayerVisible[id] ?? true) } })),

  tool: 'select',
  setTool: (tool) => set({ tool, measurement: null }),
  measurement: null,
  setMeasurement: (measurement) => set({ measurement }),
  clearMeasurementsTick: 0,
  clearMeasurements: () => set((s) => ({ clearMeasurementsTick: s.clearMeasurementsTick + 1, measurement: null })),

  selection: null,
  setSelection: (selection) => set({ selection }),

  annotations: [],
  setAnnotations: (annotations) => set({ annotations }),
  pendingAnnotation: null,
  setPendingAnnotation: (pendingAnnotation) =>
    set(pendingAnnotation ? { pendingAnnotation, panel: 'annotations', panelOpen: true } : { pendingAnnotation }),

  panel: 'layers',
  setPanel: (panel) => set({ panel, panelOpen: true }),
  panelOpen: true,
  setPanelOpen: (panelOpen) => set({ panelOpen }),

  compare: null,
  setCompare: (compare) => set({ compare }),

  timelineEnabled: false,
  timelineDate: null,
  setTimeline: (timelineEnabled, date) =>
    set((s) => ({ timelineEnabled, timelineDate: date === undefined ? s.timelineDate : date })),

  planView: false,
  setPlanView: (planView) => set({ planView }),
  globeTranslucent: false,
  setGlobeTranslucent: (globeTranslucent) => set({ globeTranslucent }),

  clip: { horizontal: false, height: 0, vertical: false, heading: 0, offset: 0 },
  setClip: (patch) => set((s) => ({ clip: { ...s.clip, ...patch } })),

  flyTo: null,
  requestFlyTo: (target) => set({ flyTo: { ...target, nonce: Date.now() + Math.random() } }),

  highlight: null,
  setHighlight: (highlight) => set({ highlight }),

  issues: [],
  setIssues: (issues) => set({ issues }),
  pendingIssuePoint: null,
  setPendingIssuePoint: (pendingIssuePoint) =>
    set(pendingIssuePoint ? { pendingIssuePoint, panel: 'issues', panelOpen: true, tool: 'select' } : { pendingIssuePoint }),
  openIssueId: null,
  setOpenIssueId: (openIssueId) => set(openIssueId ? { openIssueId, panel: 'issues', panelOpen: true } : { openIssueId }),

  profileLine: null,
  setProfileLine: (profileLine) => set({ profileLine }),

  elementColors: null,
  setElementColors: (elementColors) => set({ elementColors }),

  dataTick: 0,
  bumpData: () => set((s) => ({ dataTick: s.dataTick + 1 })),
}));
