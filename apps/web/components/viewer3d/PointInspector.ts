// Raycaster / point-inspection logic for the 3D viewer.
//
// GridInstancedMesh wires its `onClick` handler to `handleGridClick`, which:
//  1. Resolves the R3F `instanceId` from the click event to the grid's stable
//     `cellId` (from the decoded /cells buffer).
//  2. Immediately pushes a local, synchronous point-inspection result into
//     the store (from the already-downloaded per-cell property value), so
//     RightPanel has something to show without waiting on a round-trip.
//  3. Calls `POST /grids/{id}/sample` for the exact trilinearly-interpolated
//     value at the picked world point, and updates the store again when it
//     resolves.
//
// Note on coordinate spaces: `Viewer3D` applies Z-exaggeration as a
// `scale.z` on a wrapping group. Raycast intersection points from R3F are in
// world space *after* that scale is applied, so we divide the picked Z back
// down before sending it to the API (which expects true data-space
// coordinates), and before displaying it.

import type { ThreeEvent } from '@react-three/fiber';
import { api } from '@/lib/api';
import { useWorkspaceStore } from '@/lib/store';

interface HandleGridClickArgs {
  event: ThreeEvent<MouseEvent>;
  gridId: string;
  gridName: string;
  cellIds: Uint32Array;
  activeProperty: string | null;
  propertyValues: Float32Array | null;
  zExaggeration: number;
}

export function handleGridClick({
  event,
  gridId,
  gridName,
  cellIds,
  activeProperty,
  propertyValues,
  zExaggeration,
}: HandleGridClickArgs): void {
  event.stopPropagation();
  const instanceId = event.instanceId;
  if (instanceId === undefined || instanceId === null) return;

  const cellId = cellIds[instanceId];
  const localValue = propertyValues ? propertyValues[instanceId] : null;

  const wp = event.point;
  const dataX = wp.x;
  const dataY = wp.y;
  const dataZ = zExaggeration !== 0 ? wp.z / zExaggeration : wp.z;

  const { setPointInspection } = useWorkspaceStore.getState();

  setPointInspection({
    x: dataX,
    y: dataY,
    z: dataZ,
    gridId,
    gridName,
    propertyName: activeProperty ?? undefined,
    extraValues:
      activeProperty && localValue !== null && !Number.isNaN(localValue)
        ? { [`${activeProperty} (cell #${cellId})`]: localValue }
        : undefined,
  });

  if (!activeProperty) return;

  api
    .sampleGrid(gridId, { x: dataX, y: dataY, z: dataZ, property: activeProperty })
    .then((sample) => {
      const current = useWorkspaceStore.getState().pointInspection;
      // Only apply if the user hasn't clicked elsewhere in the meantime.
      if (!current || current.gridId !== gridId) return;
      useWorkspaceStore.getState().setPointInspection({
        ...current,
        sample,
      });
    })
    .catch((err) => {
      // eslint-disable-next-line no-console
      console.warn('grid sample failed', err);
    });
}

interface HandleWellClickArgs {
  wellId: string;
  wellName: string;
  /** Data-space coordinates of the picked trajectory point (already un-exaggerated). */
  x: number;
  y: number;
  z: number;
  tvd?: number;
}

export function handleWellClick({ wellId, wellName, x, y, z, tvd }: HandleWellClickArgs): void {
  const { setPointInspection, setSelectedWellId } = useWorkspaceStore.getState();
  setSelectedWellId(wellId);
  setPointInspection({
    x,
    y,
    z,
    tvd,
    wellId,
    wellName,
  });
}
