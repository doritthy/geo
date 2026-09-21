import * as THREE from 'three';
import type { ClipPlaneState } from '@/lib/store';

/**
 * Builds the array of THREE.Plane WebGL local clipping planes from the
 * store's per-axis clip state. Used by every 3D layer's material
 * (`material.clippingPlanes`) so cross-sections cut through grids, surfaces
 * and well trajectories consistently.
 */
export function buildClippingPlanes(clipPlanes: {
  x: ClipPlaneState;
  y: ClipPlaneState;
  z: ClipPlaneState;
}): THREE.Plane[] {
  const planes: THREE.Plane[] = [];
  (['x', 'y', 'z'] as const).forEach((axis) => {
    const c = clipPlanes[axis];
    if (!c.enabled) return;
    const sign = c.flipped ? 1 : -1;
    const normal = new THREE.Vector3(
      axis === 'x' ? sign : 0,
      axis === 'y' ? sign : 0,
      axis === 'z' ? sign : 0
    );
    const constant = c.flipped ? -c.value : c.value;
    planes.push(new THREE.Plane(normal, constant));
  });
  return planes;
}

/** Arbitrary vertical cut plane defined by two XY points (drawn in the viewer). */
export function buildArbitraryCutPlane(p1: [number, number], p2: [number, number], flipped: boolean): THREE.Plane {
  const dir = new THREE.Vector2(p2[0] - p1[0], p2[1] - p1[1]).normalize();
  // Perpendicular (vertical plane normal in XY), pointing to one side of the line.
  let normal2 = new THREE.Vector2(-dir.y, dir.x);
  if (flipped) normal2 = normal2.multiplyScalar(-1);
  const normal = new THREE.Vector3(normal2.x, normal2.y, 0);
  const point = new THREE.Vector3(p1[0], p1[1], 0);
  const plane = new THREE.Plane();
  plane.setFromNormalAndCoplanarPoint(normal, point);
  return plane;
}
