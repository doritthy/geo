'use client';

// The digital-twin 3D/2D viewport: CesiumJS globe + every scene asset as a
// streamed 3D Tiles tileset (BIM / point clouds / reality meshes), GIS map
// layers, annotations, measurement tools, picking, clipping and plan view.
//
// Loaded client-only (next/dynamic, ssr:false) because Cesium needs `window`.

import { useEffect, useRef, useState } from 'react';
import {
  BoundingSphere,
  CallbackProperty,
  Cartesian2,
  Cartesian3,
  Cartographic,
  Cesium3DTileFeature,
  Cesium3DTileStyle,
  Cesium3DTileset,
  ClippingPlane,
  ClassificationType,
  ClippingPlaneCollection,
  Color,
  ColorMaterialProperty,
  ConstantProperty,
  createWorldTerrainAsync,
  CustomDataSource,
  CustomHeightmapTerrainProvider,
  defined,
  EllipsoidTerrainProvider,
  Entity,
  GeoJsonDataSource,
  HeightReference,
  HeadingPitchRange,

  ImageryLayer,
  Ion,
  LabelStyle,
  Math as CesiumMath,
  Matrix3,
  Matrix4,
  NearFarScalar,
  OpenStreetMapImageryProvider,
  PolygonHierarchy,
  Rectangle,
  Resource,
  ScreenSpaceEventHandler,
  ScreenSpaceEventType,
  SingleTileImageryProvider,
  Transforms,
  VerticalOrigin,
  Viewer,
  type Cesium3DTileContent,
} from 'cesium';
import { useTwinStore, type ToolMode } from '@/lib/twin/store';
import { absoluteUrl, authHeaders, twinApi } from '@/lib/twin/api';
import type { SceneAsset } from '@/lib/twin/types';
import type { MapLayerSummary } from '@/lib/types';
import type { ProjectCrs } from '@/lib/twin/crs';
import {
  angleAt,
  fmtArea,
  fmtLength,
  fmtVolume,
  heightOf,
  polygonArea,
  polylineLength,
  toLonLatH,
  volumeAgainstBase,
  volumeSampleGrid,
} from '@/lib/twin/measure';
import { tr } from '@/lib/i18n';

// Workers/assets are copied to public/cesium by scripts/copy-cesium.js.
// Cesium resolves the base URL lazily, so setting it before the Viewer is
// created is enough.
(window as unknown as { CESIUM_BASE_URL: string }).CESIUM_BASE_URL = '/cesium/';

const ION_TOKEN = process.env.NEXT_PUBLIC_CESIUM_ION_TOKEN;

interface TilesetEntry {
  asset: SceneAsset;
  tileset: Cesium3DTileset;
  contents: Set<Cesium3DTileContent>;
}

const COMPARE_COLORS = {
  added: Color.fromCssColorString('#22C55E'),
  removed: Color.fromCssColorString('#EF4444').withAlpha(0.55),
  modified_geometry: Color.fromCssColorString('#F97316'),
  modified_properties: Color.fromCssColorString('#EAB308'),
  unchanged: Color.fromCssColorString('#CBD5E1').withAlpha(0.25),
};
const SELECT_COLOR = Color.fromCssColorString('#22D3EE');
const HIGHLIGHT_COLOR = Color.fromCssColorString('#A78BFA');
const MEASURE_COLOR = Color.fromCssColorString('#FACC15');

/** modelMatrix for a tileset: anchor placement for local models, optional
 * ENU fine-alignment offset for CRS-placed (absolute) ones. */
function modelMatrixFor(asset: SceneAsset, tileset?: Cesium3DTileset): Matrix4 {
  // Mirrors apps/api/app/twin/georef.py::asset_world_matrix:
  // alignment (ICP) · (anchor placement | ENU fine offset).
  const g = asset.georef;
  let base = Matrix4.IDENTITY.clone();
  if (g.mode === 'anchor') {
    const origin = Cartesian3.fromDegrees(g.longitude, g.latitude, g.height);
    const enu = Transforms.eastNorthUpToFixedFrame(origin);
    const rot = Matrix4.fromRotationTranslation(Matrix3.fromRotationZ(-CesiumMath.toRadians(g.heading || 0)));
    const scale = Matrix4.fromUniformScale(g.scale || 1);
    base = Matrix4.multiply(Matrix4.multiply(enu, rot, new Matrix4()), scale, new Matrix4());
  } else if (g.offset_enu && (asset.stats.center || tileset)) {
    const c = asset.stats.center;
    const ref = c ? Cartesian3.fromDegrees(c.longitude, c.latitude, c.height) : tileset!.root.boundingSphere.center;
    const enu = Transforms.eastNorthUpToFixedFrame(ref);
    const [e, n, u] = g.offset_enu;
    base = Matrix4.fromTranslation(Matrix4.multiplyByPointAsVector(enu, new Cartesian3(e, n, u), new Cartesian3()));
  }
  if (g.alignment && g.alignment.length === 16) {
    base = Matrix4.multiply(Matrix4.fromColumnMajorArray(g.alignment), base, new Matrix4());
  }
  return base;
}

function makePin(color: string): HTMLCanvasElement {
  const c = document.createElement('canvas');
  c.width = 28;
  c.height = 40;
  const ctx = c.getContext('2d')!;
  ctx.fillStyle = color;
  ctx.strokeStyle = '#0B0F19';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(14, 14, 11, Math.PI, 0);
  ctx.quadraticCurveTo(25, 26, 14, 38);
  ctx.quadraticCurveTo(3, 26, 3, 14);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = '#0B0F19';
  ctx.beginPath();
  ctx.arc(14, 14, 4, 0, Math.PI * 2);
  ctx.fill();
  return c;
}

/** Without a real terrain service the globe would sit at ellipsoid height 0
 * while models/scans sit at their true elevation (hundreds of metres in KZ).
 * A flat terrain at the project's ground level keeps the base map, draped
 * GIS layers and models together. */
function flatTerrain(height: number) {
  return new CustomHeightmapTerrainProvider({
    width: 16,
    height: 16,
    callback: () => new Float32Array(16 * 16).fill(height),
  });
}

export default function CesiumViewer({
  mapLayers,
  crs,
  groundHeight,
  onCursor,
}: {
  mapLayers: MapLayerSummary[];
  crs: ProjectCrs;
  groundHeight: number | null;
  onCursor?: (text: string | null) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<Viewer | null>(null);
  const tilesetsRef = useRef<Map<string, TilesetEntry>>(new Map());
  const measureRef = useRef<CustomDataSource | null>(null);
  const notesRef = useRef<CustomDataSource | null>(null);
  const issuesRef = useRef<CustomDataSource | null>(null);
  const mapSourcesRef = useRef<Map<string, GeoJsonDataSource | ImageryLayer>>(new Map());
  const crsRef = useRef(crs);
  crsRef.current = crs;
  const [ready, setReady] = useState(false);
  // Bumped whenever a tileset finishes loading so visibility / style /
  // clipping effects re-apply to it.
  const [tilesetTick, setTilesetTick] = useState(0);
  const firstFlyDone = useRef(false);

  const assets = useTwinStore((s) => s.assets);
  const visible = useTwinStore((s) => s.visible);
  const opacity = useTwinStore((s) => s.opacity);
  const hiddenTypes = useTwinStore((s) => s.hiddenTypes);
  const pointSize = useTwinStore((s) => s.pointSize);
  const selection = useTwinStore((s) => s.selection);
  const compare = useTwinStore((s) => s.compare);
  const highlight = useTwinStore((s) => s.highlight);
  const elementColors = useTwinStore((s) => s.elementColors);
  const tool = useTwinStore((s) => s.tool);
  const annotations = useTwinStore((s) => s.annotations);
  const issues = useTwinStore((s) => s.issues);
  const timelineEnabled = useTwinStore((s) => s.timelineEnabled);
  const timelineDate = useTwinStore((s) => s.timelineDate);
  const planView = useTwinStore((s) => s.planView);
  const globeTranslucent = useTwinStore((s) => s.globeTranslucent);
  const clip = useTwinStore((s) => s.clip);
  const flyTo = useTwinStore((s) => s.flyTo);
  const clearTick = useTwinStore((s) => s.clearMeasurementsTick);
  const mapLayerVisible = useTwinStore((s) => s.mapLayerVisible);

  // Latest styling inputs for tile-load callbacks (which outlive renders).
  const styleState = useRef({ opacity, hiddenTypes, selection, compare, highlight, elementColors });
  styleState.current = { opacity, hiddenTypes, selection, compare, highlight, elementColors };

  // ---------- init ----------
  useEffect(() => {
    if (!containerRef.current) return;
    if (ION_TOKEN) Ion.defaultAccessToken = ION_TOKEN;
    const viewer = new Viewer(containerRef.current, {
      baseLayer: new ImageryLayer(new OpenStreetMapImageryProvider({ url: 'https://tile.openstreetmap.org/', maximumLevel: 19 })),
      terrainProvider: new EllipsoidTerrainProvider(),
      baseLayerPicker: false,
      geocoder: false,
      homeButton: false,
      sceneModePicker: false,
      navigationHelpButton: false,
      animation: false,
      timeline: false,
      fullscreenButton: false,
      infoBox: false,
      selectionIndicator: false,
      requestRenderMode: false,
    });
    if (ION_TOKEN) {
      createWorldTerrainAsync().then((t) => !viewer.isDestroyed() && (viewer.terrainProvider = t)).catch(() => {});
    }
    viewer.scene.globe.depthTestAgainstTerrain = true;
    viewer.scene.pickTranslucentDepth = true;
    viewer.scene.postProcessStages.fxaa.enabled = true;
    (viewer.cesiumWidget.creditContainer as HTMLElement).style.display = 'none';
    viewer.camera.setView({ destination: Cartesian3.fromDegrees(71.43, 51.13, 25000) }); // Астана

    const measure = new CustomDataSource('measure');
    const notes = new CustomDataSource('notes');
    const issueSource = new CustomDataSource('issues');
    viewer.dataSources.add(measure);
    viewer.dataSources.add(notes);
    viewer.dataSources.add(issueSource);
    issuesRef.current = issueSource;
    measureRef.current = measure;
    notesRef.current = notes;
    viewerRef.current = viewer;
    if (process.env.NODE_ENV !== 'production') {
      (window as unknown as { __twin: unknown }).__twin = { viewer, tilesets: tilesetsRef.current };
    }
    setReady(true);

    return () => {
      tilesetsRef.current.clear();
      mapSourcesRef.current.clear();
      viewer.destroy();
      viewerRef.current = null;
    };
  }, []);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || ION_TOKEN) return;
    viewer.terrainProvider = groundHeight === null ? new EllipsoidTerrainProvider() : flatTerrain(groundHeight);
  }, [groundHeight, ready]);

  // ---------- feature styling (BIM) ----------
  function styleContent(entry: TilesetEntry, content: Cesium3DTileContent) {
    const { opacity: op, hiddenTypes: hidden, selection: sel, compare: cmp, highlight: hl, elementColors: ec } = styleState.current;
    const colorMap = ec && ec.assetId === entry.asset.id ? ec.colors : null;
    const alpha = op[entry.asset.id] ?? 1;
    const hiddenSet = new Set(hidden[entry.asset.id] ?? []);
    let cmpMap: Map<string, Color> | null = null;
    let isBase = false;
    if (cmp && (cmp.base_asset_id === entry.asset.id || cmp.other_asset_id === entry.asset.id)) {
      isBase = cmp.base_asset_id === entry.asset.id;
      cmpMap = new Map();
      if (isBase) for (const e of cmp.removed) cmpMap.set(e.global_id, COMPARE_COLORS.removed);
      else {
        for (const e of cmp.added) cmpMap.set(e.global_id, COMPARE_COLORS.added);
        for (const e of cmp.modified_geometry) cmpMap.set(e.global_id, COMPARE_COLORS.modified_geometry);
        for (const e of cmp.modified_properties) cmpMap.set(e.global_id, COMPARE_COLORS.modified_properties);
      }
    }
    const hlSet = hl ? new Set(hl.map((h) => h.global_id)) : null;
    const selected = sel?.kind === 'element' && sel.assetId === entry.asset.id ? sel.globalId : undefined;

    for (let i = 0; i < content.featuresLength; i++) {
      const f = content.getFeature(i);
      const gid = f.getProperty('GlobalId') as string | undefined;
      const type = f.getProperty('IfcType') as string | undefined;
      f.show = !(type && hiddenSet.has(type));
      if (gid && gid === selected) f.color = SELECT_COLOR;
      else if (cmpMap) {
        const c = gid ? cmpMap.get(gid) : undefined;
        if (c) f.color = c;
        else if (isBase) f.show = false;
        else f.color = COMPARE_COLORS.unchanged;
      } else if (colorMap) {
        const css = gid ? colorMap[gid] : undefined;
        f.color = css ? Color.fromCssColorString(css) : COMPARE_COLORS.unchanged;
      } else if (hlSet && gid && hlSet.has(gid)) f.color = HIGHLIGHT_COLOR;
      else f.color = Color.WHITE.withAlpha(alpha);
    }
  }

  function restyleAll() {
    for (const entry of tilesetsRef.current.values()) {
      if (entry.asset.kind === 'bim') entry.contents.forEach((c) => styleContent(entry, c));
    }
  }

  useEffect(restyleAll, [opacity, hiddenTypes, selection, compare, highlight, elementColors, tilesetTick]);

  // Non-BIM opacity / point size via declarative styles.
  useEffect(() => {
    for (const entry of tilesetsRef.current.values()) {
      const a = opacity[entry.asset.id] ?? 1;
      if (entry.asset.kind === 'point_cloud') {
        entry.tileset.style = new Cesium3DTileStyle({
          color: `rgba(\${COLOR}.r * 255, \${COLOR}.g * 255, \${COLOR}.b * 255, ${a})`,
          pointSize: `${pointSize}`,
        });
      } else if (entry.asset.kind === 'mesh') {
        entry.tileset.style = a < 1 ? new Cesium3DTileStyle({ color: `color('white', ${a})` }) : undefined;
      }
    }
  }, [opacity, pointSize, assets, ready, tilesetTick]);

  // ---------- tilesets lifecycle ----------
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !ready) return;
    const current = tilesetsRef.current;
    const ids = new Set(assets.map((a) => a.id));

    for (const [id, entry] of current) {
      if (!ids.has(id)) {
        viewer.scene.primitives.remove(entry.tileset);
        current.delete(id);
      }
    }

    let cancelled = false;
    for (const asset of assets) {
      const existing = current.get(asset.id);
      if (existing) {
        existing.asset = asset;
        existing.tileset.modelMatrix = modelMatrixFor(asset, existing.tileset);
        continue;
      }
      const resource = new Resource({ url: absoluteUrl(asset.tileset_url), headers: authHeaders() });
      Cesium3DTileset.fromUrl(resource, {
        maximumScreenSpaceError: asset.kind === 'point_cloud' ? 4 : 16,
        modelMatrix: modelMatrixFor(asset),
      })
        .then((tileset) => {
          if (cancelled || viewer.isDestroyed() || current.has(asset.id)) {
            tileset.destroy();
            return;
          }
          if (asset.kind === 'point_cloud') {
            tileset.pointCloudShading.attenuation = true;
            tileset.pointCloudShading.eyeDomeLighting = true;
            tileset.pointCloudShading.maximumAttenuation = 6;
          }
          const entry: TilesetEntry = { asset, tileset, contents: new Set() };
          tileset.tileLoad.addEventListener((tile: { content: Cesium3DTileContent }) => {
            entry.contents.add(tile.content);
            if (entry.asset.kind === 'bim') styleContent(entry, tile.content);
          });
          tileset.tileUnload.addEventListener((tile: { content: Cesium3DTileContent }) => {
            entry.contents.delete(tile.content);
          });
          tileset.modelMatrix = modelMatrixFor(asset, tileset);
          viewer.scene.primitives.add(tileset);
          current.set(asset.id, entry);
          setTilesetTick((t) => t + 1);
          if (!firstFlyDone.current) {
            firstFlyDone.current = true;
            viewer.flyTo(tileset, { duration: 1.5, offset: new HeadingPitchRange(0.6, -0.5, 0) });
          }
        })
        .catch((err) => console.error('Tileset load failed', asset.name, err));
    }
    return () => {
      cancelled = true;
    };
  }, [assets, ready]);

  // ---------- visibility (layers + timeline) ----------
  useEffect(() => {
    for (const entry of tilesetsRef.current.values()) {
      let show = visible[entry.asset.id] ?? true;
      if (show && timelineEnabled && timelineDate && entry.asset.kind !== 'bim' && entry.asset.captured_at) {
        show = entry.asset.captured_at === timelineDate;
      }
      if (compare && (entry.asset.id === compare.base_asset_id || entry.asset.id === compare.other_asset_id)) {
        show = true;
      }
      entry.tileset.show = show;
    }
  }, [visible, timelineEnabled, timelineDate, assets, compare, ready, tilesetTick]);

  // ---------- clipping ----------
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    const entries = [...tilesetsRef.current.values()].filter((e) => e.tileset.show);
    if (entries.length === 0) return;
    const sphere = BoundingSphere.fromBoundingSpheres(entries.map((e) => e.tileset.boundingSphere));
    const centerCarto = Cartographic.fromCartesian(sphere.center);
    const enu = Transforms.eastNorthUpToFixedFrame(sphere.center);
    const up = Matrix4.multiplyByPointAsVector(enu, Cartesian3.UNIT_Z, new Cartesian3());
    const heading = CesiumMath.toRadians(clip.heading);
    const horizDir = Matrix4.multiplyByPointAsVector(
      enu,
      new Cartesian3(Math.sin(heading), Math.cos(heading), 0),
      new Cartesian3()
    );

    const worldPlanes: { normal: Cartesian3; point: Cartesian3 }[] = [];
    if (clip.horizontal) {
      const p = Cartesian3.fromRadians(centerCarto.longitude, centerCarto.latitude, clip.height);
      worldPlanes.push({ normal: Cartesian3.negate(up, new Cartesian3()), point: p });
    }
    if (clip.vertical) {
      const p = Cartesian3.add(
        sphere.center,
        Cartesian3.multiplyByScalar(horizDir, clip.offset, new Cartesian3()),
        new Cartesian3()
      );
      worldPlanes.push({ normal: Cartesian3.negate(horizDir, new Cartesian3()), point: p });
    }

    for (const entry of tilesetsRef.current.values()) {
      if (worldPlanes.length === 0) {
        if (entry.tileset.clippingPlanes) entry.tileset.clippingPlanes.enabled = false;
        continue;
      }
      // Planes are expressed in the tileset's clipping origin frame.
      // `clippingPlanesOriginMatrix` is public at runtime but not in Cesium's .d.ts.
      const origin = (entry.tileset as unknown as { clippingPlanesOriginMatrix: Matrix4 }).clippingPlanesOriginMatrix;
      const inv = Matrix4.inverse(origin, new Matrix4());
      const planes = worldPlanes.map(({ normal, point }) => {
        const n = Cartesian3.normalize(Matrix4.multiplyByPointAsVector(inv, normal, new Cartesian3()), new Cartesian3());
        const p = Matrix4.multiplyByPoint(inv, point, new Cartesian3());
        return new ClippingPlane(n, -Cartesian3.dot(n, p));
      });
      entry.tileset.clippingPlanes = new ClippingPlaneCollection({
        planes,
        edgeWidth: 1.5,
        edgeColor: Color.fromCssColorString('#F97316'),
        unionClippingRegions: true,
      });
    }
  }, [clip, assets, visible, tilesetTick]);

  // ---------- plan view / globe ----------
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    const ctrl = viewer.scene.screenSpaceCameraController;
    if (planView) {
      const center = viewer.scene.pickPosition(
        new Cartesian2(viewer.canvas.clientWidth / 2, viewer.canvas.clientHeight / 2)
      );
      const carto = center ? Cartographic.fromCartesian(center) : viewer.camera.positionCartographic;
      const range = Math.max(viewer.camera.positionCartographic.height - (carto?.height ?? 0), 50);
      viewer.camera.switchToOrthographicFrustum();
      viewer.camera.setView({
        destination: Cartesian3.fromRadians(carto.longitude, carto.latitude, (carto.height || 0) + range),
        orientation: { heading: 0, pitch: -CesiumMath.PI_OVER_TWO, roll: 0 },
      });
      ctrl.enableTilt = false;
    } else {
      viewer.camera.switchToPerspectiveFrustum();
      ctrl.enableTilt = true;
    }
  }, [planView]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    const globe = viewer.scene.globe;
    globe.translucency.enabled = globeTranslucent;
    globe.translucency.frontFaceAlpha = 0.35;
    globe.translucency.backFaceAlpha = 0.35;
    viewer.scene.screenSpaceCameraController.enableCollisionDetection = !globeTranslucent;
  }, [globeTranslucent]);

  // ---------- GIS map layers ----------
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !ready) return;
    const store = mapSourcesRef.current;
    const ids = new Set(mapLayers.map((l) => l.id));
    for (const [id, src] of store) {
      if (!ids.has(id)) {
        if (src instanceof GeoJsonDataSource) viewer.dataSources.remove(src, true);
        else viewer.imageryLayers.remove(src, true);
        store.delete(id);
      }
    }
    for (const layer of mapLayers) {
      if (store.has(layer.id)) continue;
      twinApi.getMapLayer(layer.id).then(async (detail) => {
        if (viewer.isDestroyed() || store.has(layer.id)) return;
        if (detail.layer_kind === 'vector') {
          const ds = await GeoJsonDataSource.load(detail.geojson, {
            clampToGround: true,
            stroke: Color.fromCssColorString('#38BDF8'),
            fill: Color.fromCssColorString('#38BDF8').withAlpha(0.25),
            strokeWidth: 2,
            markerColor: Color.fromCssColorString('#38BDF8'),
          });
          ds.name = `map:${layer.id}`;
          // Drape on the ground only, never over BIM / scan tilesets.
          for (const ent of ds.entities.values) {
            if (ent.polygon) {
              ent.polygon.classificationType = new ConstantProperty(ClassificationType.TERRAIN);
              ent.polygon.outline = new ConstantProperty(false);
            }
            if (ent.polyline) ent.polyline.classificationType = new ConstantProperty(ClassificationType.TERRAIN);
          }
          store.set(layer.id, ds);
          viewer.dataSources.add(ds);
          ds.show = useTwinStore.getState().mapLayerVisible[layer.id] ?? true;
        } else {
          const coords = (detail.bounds_geojson as { coordinates: number[][][] }).coordinates[0];
          const lons = coords.map((c) => c[0]);
          const lats = coords.map((c) => c[1]);
          const url = await twinApi.mapLayerImage(layer.id);
          const provider = await SingleTileImageryProvider.fromUrl(url, {
            rectangle: Rectangle.fromDegrees(Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)),
          });
          const il = viewer.imageryLayers.addImageryProvider(provider);
          il.alpha = 0.85;
          il.show = useTwinStore.getState().mapLayerVisible[layer.id] ?? true;
          store.set(layer.id, il);
        }
      }).catch((err) => console.error('Map layer failed', layer.name, err));
    }
  }, [mapLayers, ready]);

  useEffect(() => {
    for (const [id, src] of mapSourcesRef.current) src.show = mapLayerVisible[id] ?? true;
  }, [mapLayerVisible]);

  // ---------- annotations ----------
  useEffect(() => {
    const notes = notesRef.current;
    if (!notes) return;
    notes.entities.removeAll();
    for (const a of annotations) {
      notes.entities.add(
        new Entity({
          id: `note:${a.id}`,
          position: Cartesian3.fromDegrees(a.longitude, a.latitude, a.height),
          billboard: {
            image: makePin(a.color),
            verticalOrigin: VerticalOrigin.BOTTOM,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
            scaleByDistance: new NearFarScalar(50, 1.0, 5000, 0.5),
          },
          label: {
            text: a.title,
            font: '13px sans-serif',
            fillColor: Color.WHITE,
            outlineColor: Color.fromCssColorString('#0B0F19'),
            outlineWidth: 3,
            style: LabelStyle.FILL_AND_OUTLINE,
            pixelOffset: new Cartesian2(0, -46),
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
            distanceDisplayCondition: undefined,
            translucencyByDistance: new NearFarScalar(200, 1.0, 3000, 0.0),
          },
        })
      );
    }
  }, [annotations]);

  // ---------- issues (предписания) ----------
  useEffect(() => {
    const src = issuesRef.current;
    if (!src) return;
    src.entities.removeAll();
    const statusColor: Record<string, string> = { open: '#EF4444', in_progress: '#F59E0B', review: '#3B82F6', closed: '#22C55E' };
    for (const i of issues) {
      if (i.longitude === null || i.latitude === null) continue;
      src.entities.add(
        new Entity({
          id: `issue:${i.id}`,
          position: Cartesian3.fromDegrees(i.longitude, i.latitude, i.height ?? 0),
          billboard: {
            image: makePin(statusColor[i.status] ?? '#EF4444'),
            verticalOrigin: VerticalOrigin.BOTTOM,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
            scaleByDistance: new NearFarScalar(50, 1.0, 5000, 0.5),
            heightReference: i.height === null ? HeightReference.CLAMP_TO_GROUND : HeightReference.NONE,
          },
          label: {
            text: `№${i.number}`,
            font: 'bold 12px sans-serif',
            fillColor: Color.WHITE,
            outlineColor: Color.fromCssColorString('#0B0F19'),
            outlineWidth: 3,
            style: LabelStyle.FILL_AND_OUTLINE,
            pixelOffset: new Cartesian2(0, -44),
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
            heightReference: i.height === null ? HeightReference.CLAMP_TO_GROUND : HeightReference.NONE,
          },
        })
      );
    }
  }, [issues]);

  // ---------- fly to ----------
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !flyTo) return;
    if (flyTo.point) {
      const p = Cartesian3.fromDegrees(flyTo.point.longitude, flyTo.point.latitude, flyTo.point.height);
      viewer.camera.flyToBoundingSphere(new BoundingSphere(p, 3), {
        duration: 1.2,
        offset: new HeadingPitchRange(0.5, -0.5, 25),
      });
      return;
    }
    if (flyTo.issueId) {
      const ent = issuesRef.current?.entities.getById(`issue:${flyTo.issueId}`);
      if (ent) viewer.flyTo(ent, { duration: 1.2, offset: new HeadingPitchRange(0, -0.6, 40) });
      return;
    }
    if (flyTo.annotationId) {
      const ent = notesRef.current?.entities.getById(`note:${flyTo.annotationId}`);
      if (ent) viewer.flyTo(ent, { duration: 1.2, offset: new HeadingPitchRange(0, -0.6, 40) });
      return;
    }
    const entry = flyTo.assetId ? tilesetsRef.current.get(flyTo.assetId) : undefined;
    if (!entry) return;
    if (flyTo.bbox) {
      const m = entry.asset.georef.mode === 'anchor' ? entry.tileset.modelMatrix : Matrix4.IDENTITY;
      const lo = Matrix4.multiplyByPoint(m, Cartesian3.fromArray(flyTo.bbox.min), new Cartesian3());
      const hi = Matrix4.multiplyByPoint(m, Cartesian3.fromArray(flyTo.bbox.max), new Cartesian3());
      const sphere = BoundingSphere.fromCornerPoints(lo, hi);
      sphere.radius = Math.max(sphere.radius, 2);
      viewer.camera.flyToBoundingSphere(sphere, {
        duration: 1.2,
        offset: new HeadingPitchRange(0.5, -0.45, Math.max(sphere.radius * 4, 30)),
      });
    } else {
      viewer.flyTo(entry.tileset, { duration: 1.2, offset: new HeadingPitchRange(0.6, -0.5, 0) });
    }
  }, [flyTo]);

  // ---------- tools: picking & measurement ----------
  const toolState = useRef<{ points: Cartesian3[]; floating: Cartesian3 | null; done: boolean }>({
    points: [],
    floating: null,
    done: false,
  });

  useEffect(() => {
    measureRef.current?.entities.removeAll();
    toolState.current = { points: [], floating: null, done: false };
  }, [clearTick, tool]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !ready) return;
    const handler = new ScreenSpaceEventHandler(viewer.scene.canvas);
    const store = useTwinStore.getState;
    const ts = toolState.current;
    const measure = measureRef.current!;

    function pick(pos: Cartesian2): Cartesian3 | undefined {
      if (viewer!.scene.pickPositionSupported) {
        const p = viewer!.scene.pickPosition(pos);
        if (defined(p)) return p;
      }
      return viewer!.camera.pickEllipsoid(pos) ?? undefined;
    }

    function addPoint(p: Cartesian3) {
      measure.entities.add({
        position: p,
        point: { pixelSize: 8, color: MEASURE_COLOR, outlineColor: Color.BLACK, outlineWidth: 1, disableDepthTestDistance: Number.POSITIVE_INFINITY },
      });
    }

    function label(p: Cartesian3, text: string) {
      measure.entities.add({
        position: p,
        label: {
          text,
          font: '13px sans-serif',
          showBackground: true,
          backgroundColor: Color.fromCssColorString('#0B0F19').withAlpha(0.8),
          fillColor: Color.WHITE,
          pixelOffset: new Cartesian2(0, -18),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
      });
    }

    function livePositions(closed = false): CallbackProperty {
      return new CallbackProperty(() => {
        const pts = ts.floating && !ts.done ? [...ts.points, ts.floating] : [...ts.points];
        return closed && pts.length > 2 ? [...pts, pts[0]] : pts;
      }, false);
    }

    function startShape(currentTool: ToolMode) {
      const closed = currentTool === 'area' || currentTool === 'volume';
      measure.entities.add({
        polyline: {
          positions: livePositions(closed),
          width: 2.5,
          material: new ColorMaterialProperty(MEASURE_COLOR),
          depthFailMaterial: new ColorMaterialProperty(MEASURE_COLOR.withAlpha(0.4)),
        },
      });
      if (closed) {
        measure.entities.add({
          polygon: {
            hierarchy: new CallbackProperty(() => {
              const pts = ts.floating && !ts.done ? [...ts.points, ts.floating] : ts.points;
              return new PolygonHierarchy(pts);
            }, false),
            perPositionHeight: true,
            material: MEASURE_COLOR.withAlpha(0.2),
          },
        });
      }
    }

    function report(currentTool: ToolMode, pts: Cartesian3[], final: boolean) {
      const set = store().setMeasurement;
      if (currentTool === 'distance' && pts.length >= 2) {
        const r = polylineLength(pts);
        set({
          tool: currentTool,
          lines: [
            { label: tr('Длина (3D)'), value: fmtLength(r.length3d) },
            { label: tr('Горизонтальное проложение'), value: fmtLength(r.horizontal) },
            { label: tr('Перепад высот'), value: fmtLength(r.dh) },
            { label: tr('Точек'), value: String(pts.length) },
          ],
        });
        if (final) label(pts[pts.length - 1], fmtLength(r.length3d));
      } else if ((currentTool === 'area' || currentTool === 'volume') && pts.length >= 3) {
        const r = polygonArea(pts);
        set({
          tool: currentTool,
          lines: [
            { label: tr('Площадь (в плане)'), value: fmtArea(r.horizontal) },
            { label: tr('Площадь поверхности'), value: fmtArea(r.surface) },
            { label: tr('Периметр'), value: fmtLength(r.perimeter) },
          ],
        });
        if (final && currentTool === 'area') label(pts[0], fmtArea(r.horizontal));
      } else if (currentTool === 'height' && pts.length === 2) {
        const r = polylineLength(pts);
        const slope = r.horizontal > 0 ? (r.dh / r.horizontal) * 100 : 0;
        set({
          tool: currentTool,
          lines: [
            { label: tr('Перепад высот Δh'), value: fmtLength(r.dh) },
            { label: tr('Отметка 1'), value: `${heightOf(pts[0]).toFixed(3)} м` },
            { label: tr('Отметка 2'), value: `${heightOf(pts[1]).toFixed(3)} м` },
            { label: tr('Горизонтальное расстояние'), value: fmtLength(r.horizontal) },
            { label: tr('Уклон'), value: `${slope.toFixed(2)} %` },
          ],
        });
        if (final) label(pts[1], `Δh ${r.dh.toFixed(3)} м`);
      } else if (currentTool === 'profile' && pts.length === 2) {
        const r = polylineLength(pts);
        set({ tool: currentTool, lines: [{ label: tr('Длина разреза'), value: fmtLength(r.horizontal) }] });
        if (final) {
          const a = toLonLatH(pts[0]);
          const b = toLonLatH(pts[1]);
          store().setProfileLine({ a: [a.lon, a.lat], b: [b.lon, b.lat] });
          label(pts[1], tr('Разрез'));
        }
      } else if (currentTool === 'angle' && pts.length === 3) {
        const a = angleAt(pts[0], pts[1], pts[2]);
        set({ tool: currentTool, lines: [{ label: tr('Угол'), value: `${a.toFixed(2)}°` }] });
        if (final) label(pts[1], `${a.toFixed(2)}°`);
      }
    }

    async function computeVolume(pts: Cartesian3[]) {
      const set = store().setMeasurement;
      const { samples, cellArea } = volumeSampleGrid(pts);
      const base = pts.reduce((s, p) => s + heightOf(p), 0) / pts.length;
      set({ tool: 'volume', lines: [{ label: tr('Объём'), value: `расчёт по ${samples.length} точкам…` }] });
      try {
        const sampled = await viewer!.scene.sampleHeightMostDetailed(samples);
        const r = volumeAgainstBase(sampled.map((c) => c?.height), cellArea, base);
        const area = polygonArea(pts);
        set({
          tool: 'volume',
          lines: [
            { label: tr('Объём выше базы (насыпь)'), value: fmtVolume(r.above) },
            { label: tr('Объём ниже базы (выемка)'), value: fmtVolume(r.below) },
            { label: tr('Отметка базы (средняя по контуру)'), value: `${base.toFixed(3)} м` },
            { label: tr('Площадь (в плане)'), value: fmtArea(area.horizontal) },
            { label: tr('Точек выборки'), value: `${r.valid} / ${samples.length}` },
          ],
        });
        label(pts[0], `${fmtVolume(r.above)} / −${fmtVolume(r.below)}`);
      } catch {
        set({ tool: 'volume', lines: [{ label: tr('Объём'), value: tr('не удалось получить высоты сцены') }] });
      }
    }

    function finish() {
      const currentTool = store().tool;
      if (ts.done || ts.points.length === 0) return;
      ts.done = true;
      ts.floating = null;
      report(currentTool, ts.points, true);
      if (currentTool === 'volume' && ts.points.length >= 3) computeVolume([...ts.points]);
    }

    handler.setInputAction((e: { position: Cartesian2 }) => {
      const currentTool = store().tool;

      if (currentTool === 'select' || currentTool === 'annotate' || currentTool === 'issue') {
        const picked = viewer.scene.pick(e.position);
        const position = pick(e.position);
        let assetId: string | undefined;
        let globalId: string | undefined;
        if (picked instanceof Cesium3DTileFeature) {
          for (const [id, entry] of tilesetsRef.current) if (entry.tileset === picked.tileset) assetId = id;
          globalId = picked.getProperty('GlobalId') as string | undefined;
        }
        if (currentTool === 'annotate' || currentTool === 'issue') {
          if (!position) return;
          const llh = toLonLatH(position);
          const point = { longitude: llh.lon, latitude: llh.lat, height: llh.h, assetId, globalId };
          if (currentTool === 'issue') store().setPendingIssuePoint(point);
          else store().setPendingAnnotation(point);
          return;
        }
        if (globalId && assetId) {
          store().setSelection({ kind: 'element', assetId, globalId, title: picked.getProperty('Name') as string });
        } else if (picked?.id instanceof Entity && String(picked.id.id).startsWith('issue:')) {
          store().setOpenIssueId(String(picked.id.id).slice(6));
        } else if (picked?.id instanceof Entity && String(picked.id.id).startsWith('note:')) {
          store().setSelection({ kind: 'annotation', annotationId: String(picked.id.id).slice(5) });
        } else if (picked?.id instanceof Entity && picked.id.properties) {
          const props: Record<string, unknown> = {};
          for (const name of picked.id.properties.propertyNames) props[name] = picked.id.properties[name]?.getValue();
          store().setSelection({ kind: 'feature', title: picked.id.name ?? tr('Объект ГИС'), properties: props });
        } else {
          store().setSelection(null);
        }
        return;
      }

      const p = pick(e.position);
      if (!p) return;

      if (currentTool === 'point') {
        measure.entities.removeAll();
        addPoint(p);
        const llh = toLonLatH(p);
        const lines = [
          { label: tr('Широта'), value: `${llh.lat.toFixed(7)}°` },
          { label: tr('Долгота'), value: `${llh.lon.toFixed(7)}°` },
          { label: tr('Высота (эллипсоид)'), value: `${llh.h.toFixed(3)} м` },
        ];
        const fwd = crsRef.current.forward;
        if (fwd) {
          const [x, y] = fwd(llh.lon, llh.lat);
          lines.push({ label: `X / Восток (${crsRef.current.label})`, value: x.toFixed(3) });
          lines.push({ label: `Y / Север (${crsRef.current.label})`, value: y.toFixed(3) });
        }
        store().setMeasurement({ tool: 'point', lines });
        label(p, `H ${llh.h.toFixed(2)} м`);
        return;
      }

      if (ts.done) {
        measure.entities.removeAll();
        ts.points = [];
        ts.done = false;
      }
      if (ts.points.length === 0) startShape(currentTool);
      ts.points.push(p);
      addPoint(p);
      report(currentTool, ts.points, false);
      const maxPoints = currentTool === 'height' || currentTool === 'profile' ? 2 : currentTool === 'angle' ? 3 : Infinity;
      if (ts.points.length >= maxPoints) finish();
    }, ScreenSpaceEventType.LEFT_CLICK);

    handler.setInputAction(finish, ScreenSpaceEventType.RIGHT_CLICK);
    handler.setInputAction(finish, ScreenSpaceEventType.LEFT_DOUBLE_CLICK);

    let lastMove = 0;
    handler.setInputAction((e: { endPosition: Cartesian2 }) => {
      const now = performance.now();
      if (now - lastMove < 50) return;
      lastMove = now;
      const p = pick(e.endPosition);
      if (ts.points.length > 0 && !ts.done && p) ts.floating = p;
      if (onCursor) {
        if (!p) return onCursor(null);
        const llh = toLonLatH(p);
        let text = `${llh.lat.toFixed(6)}°, ${llh.lon.toFixed(6)}°  H ${llh.h.toFixed(2)} м`;
        const fwd = crsRef.current.forward;
        if (fwd) {
          const [x, y] = fwd(llh.lon, llh.lat);
          text += `  ·  ${crsRef.current.label}: ${x.toFixed(2)}, ${y.toFixed(2)}`;
        }
        onCursor(text);
      }
    }, ScreenSpaceEventType.MOUSE_MOVE);

    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === 'Escape') {
        measure.entities.removeAll();
        ts.points = [];
        ts.floating = null;
        ts.done = false;
        store().setMeasurement(null);
      } else if (ev.key === 'Enter') finish();
    };
    window.addEventListener('keydown', onKey);

    // Double-click would otherwise zoom to an entity.
    viewer.cesiumWidget.screenSpaceEventHandler.removeInputAction(ScreenSpaceEventType.LEFT_DOUBLE_CLICK);

    return () => {
      handler.destroy();
      window.removeEventListener('keydown', onKey);
    };
  }, [ready, onCursor]);

  // Cursor feedback per tool
  useEffect(() => {
    if (containerRef.current) containerRef.current.style.cursor = tool === 'select' ? 'default' : 'crosshair';
  }, [tool]);

  return <div ref={containerRef} className="twin-cesium h-full w-full" />;
}


