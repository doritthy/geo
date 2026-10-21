// Geodesy / measurement helpers on top of Cesium math. All inputs are ECEF
// Cartesian3 positions picked from the scene (tiles or terrain).

import {
  Cartesian3,
  Cartographic,
  Ellipsoid,
  Math as CesiumMath,
  Matrix4,
  Transforms,
} from 'cesium';

export function heightOf(p: Cartesian3): number {
  return Cartographic.fromCartesian(p).height;
}

export function toLonLatH(p: Cartesian3): { lon: number; lat: number; h: number } {
  const c = Cartographic.fromCartesian(p);
  return { lon: CesiumMath.toDegrees(c.longitude), lat: CesiumMath.toDegrees(c.latitude), h: c.height };
}

/** Positions expressed in a local east/north/up frame at `origin` (metres). */
export function toEnu(points: Cartesian3[], origin: Cartesian3 = points[0]): Cartesian3[] {
  const toLocal = Matrix4.inverseTransformation(Transforms.eastNorthUpToFixedFrame(origin), new Matrix4());
  return points.map((p) => Matrix4.multiplyByPoint(toLocal, p, new Cartesian3()));
}

export function polylineLength(points: Cartesian3[]): { length3d: number; horizontal: number; dh: number } {
  let length3d = 0;
  let horizontal = 0;
  const enu = toEnu(points);
  for (let i = 1; i < points.length; i++) {
    length3d += Cartesian3.distance(points[i - 1], points[i]);
    horizontal += Math.hypot(enu[i].x - enu[i - 1].x, enu[i].y - enu[i - 1].y);
  }
  const dh = points.length > 1 ? heightOf(points[points.length - 1]) - heightOf(points[0]) : 0;
  return { length3d, horizontal, dh };
}

/** Horizontal (plan) area via shoelace in ENU, 3D surface area via Newell, perimeter. */
export function polygonArea(points: Cartesian3[]): { horizontal: number; surface: number; perimeter: number } {
  if (points.length < 3) return { horizontal: 0, surface: 0, perimeter: 0 };
  const enu = toEnu(points);
  let a = 0;
  let nx = 0;
  let ny = 0;
  let nz = 0;
  let perimeter = 0;
  for (let i = 0; i < enu.length; i++) {
    const p = enu[i];
    const q = enu[(i + 1) % enu.length];
    a += p.x * q.y - q.x * p.y;
    nx += (p.y - q.y) * (p.z + q.z);
    ny += (p.z - q.z) * (p.x + q.x);
    nz += (p.x - q.x) * (p.y + q.y);
    perimeter += Cartesian3.distance(points[i], points[(i + 1) % points.length]);
  }
  return { horizontal: Math.abs(a) / 2, surface: Math.hypot(nx, ny, nz) / 2, perimeter };
}

/** Angle at vertex b (degrees) between rays b->a and b->c. */
export function angleAt(a: Cartesian3, b: Cartesian3, c: Cartesian3): number {
  const u = Cartesian3.subtract(a, b, new Cartesian3());
  const v = Cartesian3.subtract(c, b, new Cartesian3());
  return CesiumMath.toDegrees(Cartesian3.angleBetween(u, v));
}

function pointInPolygon(x: number, y: number, poly: { x: number; y: number }[]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const xi = poly[i].x;
    const yi = poly[i].y;
    const xj = poly[j].x;
    const yj = poly[j].y;
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** Sample grid points inside the polygon (ENU at the first vertex). Returns
 * cartographics to sample plus the cell area each sample represents. */
export function volumeSampleGrid(points: Cartesian3[], target = 1600): { samples: Cartographic[]; cellArea: number } {
  const origin = points[0];
  const enu = toEnu(points, origin);
  const xs = enu.map((p) => p.x);
  const ys = enu.map((p) => p.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const area = polygonArea(points).horizontal;
  const step = Math.max(Math.sqrt(area / target), 0.05);
  const toWorld = Transforms.eastNorthUpToFixedFrame(origin);
  const samples: Cartographic[] = [];
  for (let x = minX + step / 2; x < maxX; x += step) {
    for (let y = minY + step / 2; y < maxY; y += step) {
      if (!pointInPolygon(x, y, enu)) continue;
      const world = Matrix4.multiplyByPoint(toWorld, new Cartesian3(x, y, 0), new Cartesian3());
      samples.push(Cartographic.fromCartesian(world, Ellipsoid.WGS84));
    }
  }
  return { samples, cellArea: step * step };
}

/** Cut/fill volumes of sampled heights against a horizontal base plane. */
export function volumeAgainstBase(heights: (number | undefined)[], cellArea: number, base: number) {
  let above = 0;
  let below = 0;
  let valid = 0;
  for (const h of heights) {
    if (h === undefined || !Number.isFinite(h)) continue;
    valid++;
    const d = h - base;
    if (d > 0) above += d * cellArea;
    else below += -d * cellArea;
  }
  return { above, below, valid };
}

export function fmtLength(m: number): string {
  if (Math.abs(m) >= 1000) return `${(m / 1000).toFixed(3)} км`;
  return `${m.toFixed(Math.abs(m) < 10 ? 3 : 2)} м`;
}

export function fmtArea(m2: number): string {
  if (m2 >= 10000) return `${m2.toFixed(1)} м² (${(m2 / 10000).toFixed(3)} га)`;
  return `${m2.toFixed(2)} м²`;
}

export function fmtVolume(m3: number): string {
  return `${m3.toFixed(m3 < 100 ? 2 : 1)} м³`;
}
