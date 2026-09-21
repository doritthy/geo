'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import { useWorkspaceStore } from '@/lib/store';
import { api } from '@/lib/api';
import { decodeGridCells, decodeGridProperty, type DecodedGridCells } from '@/lib/binary';
import { makeColorScale } from '@/lib/colormaps';
import { buildClippingPlanes } from './clipPlanes';
import { handleGridClick } from './PointInspector';
import type { GridDetail } from '@/lib/types';

function computeMinMax(values: Float32Array): { min: number; max: number } {
  let min = Infinity;
  let max = -Infinity;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (Number.isNaN(v)) continue;
    if (v < min) min = v;
    if (v > max) max = v;
  }
  if (!isFinite(min) || !isFinite(max)) return { min: 0, max: 1 };
  return { min, max };
}

export default function GridInstancedMesh({
  gridId,
  gridDetail,
  visible,
}: {
  gridId: string;
  gridDetail: GridDetail;
  visible: boolean;
}) {
  const activeGridId = useWorkspaceStore((s) => s.activeGridId);
  const activeProperty = useWorkspaceStore((s) => s.activeProperty);
  const colormap = useWorkspaceStore((s) => s.colormap);
  const valueRange = useWorkspaceStore((s) => s.valueRange);
  const setValueRange = useWorkspaceStore((s) => s.setValueRange);
  const threshold = useWorkspaceStore((s) => s.threshold);
  const lod = useWorkspaceStore((s) => s.lod);
  const clipPlanes = useWorkspaceStore((s) => s.clipPlanes);
  const zExaggeration = useWorkspaceStore((s) => s.zExaggeration);

  const isActiveGrid = activeGridId === gridId;
  const effectiveProperty = isActiveGrid ? activeProperty : null;

  const [cells, setCells] = useState<DecodedGridCells | null>(null);
  const [propValues, setPropValues] = useState<Float32Array | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const meshRef = useRef<THREE.InstancedMesh>(null);

  useEffect(() => {
    let cancelled = false;
    setCells(null);
    api
      .getGridCells(gridId, lod)
      .then(({ buffer, cellCount }) => {
        if (cancelled) return;
        setCells(decodeGridCells(buffer, cellCount));
        setLoadError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(err instanceof Error ? err.message : 'Failed to load grid cells');
      });
    return () => {
      cancelled = true;
    };
  }, [gridId, lod]);

  useEffect(() => {
    if (!effectiveProperty) {
      setPropValues(null);
      return;
    }
    let cancelled = false;
    api
      .getGridProperty(gridId, effectiveProperty, lod)
      .then((buf) => {
        if (cancelled) return;
        const values = decodeGridProperty(buf);
        setPropValues(values);
        const summary = gridDetail.properties.find((p) => p.name === effectiveProperty);
        setValueRange(summary ? { min: summary.min_value, max: summary.max_value } : computeMinMax(values));
      })
      .catch((err) => {
        // eslint-disable-next-line no-console
        console.error('Failed to load grid property', err);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gridId, effectiveProperty, lod]);

  const colorScale = useMemo(() => {
    if (!valueRange) return null;
    return makeColorScale(colormap, valueRange.min, valueRange.max);
  }, [colormap, valueRange]);

  const clippingPlanes = useMemo(() => buildClippingPlanes(clipPlanes), [clipPlanes]);

  const material = useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        vertexColors: true,
        metalness: 0.05,
        roughness: 0.9,
      }),
    []
  );

  useEffect(() => {
    material.clippingPlanes = clippingPlanes;
    material.needsUpdate = true;
  }, [clippingPlanes, material]);

  useEffect(() => () => material.dispose(), [material]);

  useEffect(() => {
    const mesh = meshRef.current;
    if (!mesh || !cells) return;
    const { cellCount, centers, sizes } = cells;
    const dummy = new THREE.Object3D();
    const color = new THREE.Color();
    const activeThreshold = isActiveGrid ? threshold : null;

    for (let i = 0; i < cellCount; i++) {
      const cx = centers[i * 3];
      const cy = centers[i * 3 + 1];
      const cz = centers[i * 3 + 2];
      const sx = sizes[i * 3] || 1;
      const sy = sizes[i * 3 + 1] || 1;
      const sz = sizes[i * 3 + 2] || 1;

      let hidden = false;
      if (activeThreshold && propValues) {
        const v = propValues[i];
        if (Number.isNaN(v) || v < activeThreshold.min || v > activeThreshold.max) hidden = true;
      }

      dummy.position.set(cx, cy, cz);
      dummy.scale.set(hidden ? 0 : sx, hidden ? 0 : sy, hidden ? 0 : sz);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);

      if (propValues && colorScale && isActiveGrid) {
        const [r, g, b] = colorScale(propValues[i]);
        color.setRGB(r, g, b);
      } else {
        color.set('#2b6ea8');
      }
      mesh.setColorAt(i, color);
    }
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  }, [cells, propValues, colorScale, threshold, isActiveGrid]);

  if (loadError) return null;
  if (!cells || cells.cellCount === 0) return null;

  return (
    <instancedMesh
      key={`${gridId}-${lod}-${cells.cellCount}`}
      ref={meshRef}
      args={[undefined as unknown as THREE.BufferGeometry, undefined as unknown as THREE.Material, cells.cellCount]}
      visible={visible}
      onClick={(e) => {
        if (!visible) return;
        handleGridClick({
          event: e,
          gridId,
          gridName: gridDetail.name,
          cellIds: cells.cellIds,
          activeProperty: effectiveProperty,
          propertyValues: propValues,
          zExaggeration,
        });
      }}
    >
      <boxGeometry args={[1, 1, 1]} />
      <primitive object={material} attach="material" />
    </instancedMesh>
  );
}
