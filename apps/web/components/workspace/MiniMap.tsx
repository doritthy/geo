'use client';

import { useMemo } from 'react';
import { MapContainer, TileLayer, LayersControl, CircleMarker, Tooltip } from 'react-leaflet';
import type { WellSummary } from '@/lib/types';

/**
 * Compact 2D structural-map / satellite thumbnail widget for LeftPanel.
 * Reuses the same base-layer switcher (OSM / Esri World Imagery) as the
 * full GIS mode, at a small fixed size, showing well surface locations.
 * See Map2D.tsx for the same lat/lon-vs-project-CRS caveat.
 */
export default function MiniMap({ wells }: { wells: WellSummary[] }) {
  const points = useMemo(
    () =>
      wells.filter((w) => Math.abs(w.surface_x) <= 180 && Math.abs(w.surface_y) <= 90).map((w) => ({ w, lat: w.surface_y, lng: w.surface_x })),
    [wells]
  );
  const center: [number, number] = points.length > 0 ? [points[0].lat, points[0].lng] : [0, 0];

  return (
    <MapContainer
      center={center}
      zoom={points.length > 0 ? 8 : 1}
      zoomControl={false}
      dragging
      className="h-full w-full"
      style={{ background: '#0B0F19' }}
    >
      <LayersControl position="topright">
        <LayersControl.BaseLayer checked name="Map">
          <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        </LayersControl.BaseLayer>
        <LayersControl.BaseLayer name="Satellite">
          <TileLayer url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}" />
        </LayersControl.BaseLayer>
      </LayersControl>
      {points.map(({ w, lat, lng }) => (
        <CircleMarker key={w.id} center={[lat, lng]} radius={4} pathOptions={{ color: '#2DD4BF' }}>
          <Tooltip>{w.name}</Tooltip>
        </CircleMarker>
      ))}
    </MapContainer>
  );
}
