'use client';

import { useEffect, useMemo, useState } from 'react';
import { MapContainer, TileLayer, LayersControl, Marker, Popup, GeoJSON, ImageOverlay, useMapEvents } from 'react-leaflet';
import L from 'leaflet';
import { api } from '@/lib/api';
import { useWorkspaceStore } from '@/lib/store';
import type { WellSummary, MapLayerSummary, MapLayerDetail, Project } from '@/lib/types';

// Leaflet's default marker icons reference image files that Next.js's bundler
// doesn't resolve automatically; rebuild the default icon from CDN URLs.
const DEFAULT_ICON = L.icon({
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
});

const WELL_ICON_COLORS: Record<string, string> = {
  producer: '#2DD4BF',
  injector: '#3B82F6',
  observation: '#F5A524',
  exploration: '#A78BFA',
};

function wellDivIcon(wellType: string): L.DivIcon {
  const color = WELL_ICON_COLORS[wellType] ?? '#94A3B8';
  return L.divIcon({
    className: '',
    html: `<div style="width:14px;height:14px;border-radius:50%;background:${color};border:2px solid #0B0F19;box-shadow:0 0 0 1px ${color}"></div>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  });
}

function MouseCoordinates({ crsEpsg }: { crsEpsg: number }) {
  const [pos, setPos] = useState<{ lat: number; lng: number } | null>(null);
  useMapEvents({
    mousemove(e) {
      setPos({ lat: e.latlng.lat, lng: e.latlng.lng });
    },
  });
  if (!pos) return null;
  return (
    <div className="pointer-events-none absolute bottom-3 left-3 z-[1000] rounded-md border border-bg-border bg-bg-panel/90 px-2.5 py-1 text-[11px] text-text-secondary backdrop-blur">
      lat {pos.lat.toFixed(5)}, lon {pos.lng.toFixed(5)} <span className="text-text-muted">· project CRS EPSG:{crsEpsg}</span>
    </div>
  );
}

function VectorLayer({ layerId }: { layerId: string }) {
  const [detail, setDetail] = useState<MapLayerDetail | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .getMapLayer(layerId)
      .then((d) => !cancelled && setDetail(d))
      .catch((err) => console.error('Failed to load map layer', err));
    return () => {
      cancelled = true;
    };
  }, [layerId]);

  if (!detail || detail.layer_kind !== 'vector') return null;
  return <GeoJSON data={detail.geojson} style={{ color: '#2DD4BF', weight: 2, fillOpacity: 0.12 }} />;
}

function RasterLayer({ layerId, bounds }: { layerId: string; bounds: L.LatLngBoundsExpression | null }) {
  const [detail, setDetail] = useState<MapLayerDetail | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .getMapLayer(layerId)
      .then((d) => !cancelled && setDetail(d))
      .catch((err) => console.error('Failed to load map layer', err));
    return () => {
      cancelled = true;
    };
  }, [layerId]);

  if (!detail || detail.layer_kind !== 'raster' || !bounds) return null;
  return <ImageOverlay url={detail.image_url} bounds={bounds} opacity={0.75} />;
}

function geojsonToLeafletBounds(geo: unknown): L.LatLngBoundsExpression | null {
  try {
    const gj = geo as GeoJSON.GeoJSON;
    const layer = L.geoJSON(gj as any);
    const b = layer.getBounds();
    if (!b.isValid()) return null;
    return b;
  } catch {
    return null;
  }
}

export default function Map2D({
  project,
  wells,
  mapLayers,
}: {
  project: Project;
  wells: WellSummary[];
  mapLayers: MapLayerSummary[];
}) {
  const layerVisibility = useWorkspaceStore((s) => s.layerVisibility);
  const setSelectedWellId = useWorkspaceStore((s) => s.setSelectedWellId);
  const setPointInspection = useWorkspaceStore((s) => s.setPointInspection);

  const center = useMemo<[number, number]>(() => {
    if (wells.length === 0) return [0, 0];
    // Wells are stored in project CRS (e.g. UTM), not lat/lon -- without a
    // projection library on the client we can't reproject generically, but
    // most project CRS's are close enough in magnitude that we fall back to
    // a neutral default and let vector/raster overlays (already reprojected
    // to WGS84 server-side) anchor the map. We center on (0,0) unless the
    // coordinates already look like lat/lon (small magnitude).
    const w = wells[0];
    if (Math.abs(w.surface_x) <= 180 && Math.abs(w.surface_y) <= 90) {
      return [w.surface_y, w.surface_x];
    }
    return [0, 0];
  }, [wells]);

  return (
    <div className="relative h-full w-full">
      <MapContainer center={center} zoom={wells.length > 0 ? 10 : 2} className="h-full w-full" style={{ background: '#0B0F19' }}>
        <LayersControl position="topright">
          <LayersControl.BaseLayer checked name="OpenStreetMap">
            <TileLayer
              attribution="&copy; OpenStreetMap contributors"
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
          </LayersControl.BaseLayer>
          <LayersControl.BaseLayer name="Esri World Imagery">
            <TileLayer
              attribution="Tiles &copy; Esri"
              url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
            />
          </LayersControl.BaseLayer>
        </LayersControl>

        {layerVisibility.mapLayers &&
          mapLayers.map((l) =>
            l.layer_kind === 'vector' ? (
              <VectorLayer key={l.id} layerId={l.id} />
            ) : (
              <RasterLayer key={l.id} layerId={l.id} bounds={geojsonToLeafletBounds(l.bounds_geojson)} />
            )
          )}

        {layerVisibility.wells &&
          wells.map((w) => {
            const latlng: [number, number] =
              Math.abs(w.surface_x) <= 180 && Math.abs(w.surface_y) <= 90
                ? [w.surface_y, w.surface_x]
                : [center[0], center[1]];
            return (
              <Marker
                key={w.id}
                position={latlng}
                icon={wellDivIcon(w.well_type) ?? DEFAULT_ICON}
                eventHandlers={{
                  click: () => {
                    setSelectedWellId(w.id);
                    setPointInspection({ x: w.surface_x, y: w.surface_y, z: 0, wellId: w.id, wellName: w.name });
                  },
                }}
              >
                <Popup>
                  <div className="text-sm">
                    <div className="font-semibold">{w.name}</div>
                    <div className="text-text-secondary">{w.well_type}</div>
                    {w.total_depth != null && <div>TD: {w.total_depth.toFixed(1)} m</div>}
                  </div>
                </Popup>
              </Marker>
            );
          })}

        <MouseCoordinates crsEpsg={project.default_crs_epsg} />
      </MapContainer>
    </div>
  );
}
