'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import { useWorkspaceStore } from '@/lib/store';
import { api } from '@/lib/api';
import { decodeSurfaceHeights } from '@/lib/binary';
import type { SurfaceDetail } from '@/lib/types';
import { buildClippingPlanes } from './clipPlanes';

/**
 * Displaced PlaneGeometry: one vertex per raster cell of the surface,
 * row-major per docs/API_CONTRACT.md ("Surfaces" section). Built as a
 * hand-rolled BufferGeometry (rather than THREE.PlaneGeometry) so vertices
 * land exactly at `origin + (col*cell_size_x, row*cell_size_y)` in world
 * space, with cells reported as `NaN` (nodata) simply omitted from the
 * triangle index (leaving a hole) rather than rendered at z=0.
 */
export default function SurfaceMesh({
  surfaceId,
  surfaceDetail,
  visible,
  color = '#C9A24B',
}: {
  surfaceId: string;
  surfaceDetail: SurfaceDetail;
  visible: boolean;
  color?: string;
}) {
  const [heights, setHeights] = useState<Float32Array | null>(null);
  const clipPlanes = useWorkspaceStore((s) => s.clipPlanes);
  const meshRef = useRef<THREE.Mesh>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getSurfaceHeights(surfaceId)
      .then((buf) => {
        if (cancelled) return;
        setHeights(decodeSurfaceHeights(buf, surfaceDetail.rows, surfaceDetail.cols));
      })
      .catch((err) => {
        // eslint-disable-next-line no-console
        console.error('Failed to load surface heights', err);
      });
    return () => {
      cancelled = true;
    };
  }, [surfaceId, surfaceDetail.rows, surfaceDetail.cols]);

  const geometry = useMemo(() => {
    if (!heights) return null;
    const { rows, cols, origin_x, origin_y, cell_size_x, cell_size_y } = surfaceDetail;
    const positions = new Float32Array(rows * cols * 3);
    const validMask = new Uint8Array(rows * cols);

    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const idx = r * cols + c;
        const z = heights[idx];
        const valid = !Number.isNaN(z);
        validMask[idx] = valid ? 1 : 0;
        positions[idx * 3] = origin_x + c * cell_size_x;
        positions[idx * 3 + 1] = origin_y + r * cell_size_y;
        positions[idx * 3 + 2] = valid ? z : 0;
      }
    }

    const indices: number[] = [];
    for (let r = 0; r < rows - 1; r++) {
      for (let c = 0; c < cols - 1; c++) {
        const a = r * cols + c;
        const b = r * cols + c + 1;
        const cIdx = (r + 1) * cols + c;
        const d = (r + 1) * cols + c + 1;
        if (validMask[a] && validMask[b] && validMask[cIdx]) indices.push(a, b, cIdx);
        if (validMask[b] && validMask[d] && validMask[cIdx]) indices.push(b, d, cIdx);
      }
    }

    const geom = new THREE.BufferGeometry();
    geom.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geom.setIndex(indices);
    geom.computeVertexNormals();
    return geom;
  }, [heights, surfaceDetail]);

  const clippingPlanes = useMemo(() => buildClippingPlanes(clipPlanes), [clipPlanes]);

  const material = useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        color,
        side: THREE.DoubleSide,
        metalness: 0.05,
        roughness: 0.85,
        transparent: true,
        opacity: 0.92,
      }),
    [color]
  );

  useEffect(() => {
    material.clippingPlanes = clippingPlanes;
    material.needsUpdate = true;
  }, [clippingPlanes, material]);

  useEffect(() => () => material.dispose(), [material]);
  useEffect(() => () => geometry?.dispose(), [geometry]);

  if (!geometry) return null;

  return <mesh ref={meshRef} geometry={geometry} material={material} visible={visible} />;
}
