// Colormap lookup functions: value in [0,1] -> [r,g,b] in [0,1].
// Implemented as small analytic approximations (no external LUT images needed).

export type RGB = [number, number, number];
export type ColormapFn = (t: number) => RGB;

function clamp01(t: number): number {
  return Math.min(1, Math.max(0, t));
}

// Classic "Jet" colormap approximation.
export function jet(t: number): RGB {
  t = clamp01(t);
  const r = clamp01(1.5 - Math.abs(4 * t - 3));
  const g = clamp01(1.5 - Math.abs(4 * t - 2));
  const b = clamp01(1.5 - Math.abs(4 * t - 1));
  return [r, g, b];
}

// Viridis approximation via piecewise-linear control points (perceptually uniform-ish).
const VIRIDIS_STOPS: RGB[] = [
  [0.267, 0.005, 0.329],
  [0.283, 0.141, 0.458],
  [0.254, 0.265, 0.53],
  [0.207, 0.372, 0.553],
  [0.164, 0.471, 0.558],
  [0.128, 0.567, 0.551],
  [0.135, 0.659, 0.518],
  [0.267, 0.749, 0.441],
  [0.478, 0.821, 0.318],
  [0.741, 0.873, 0.15],
  [0.993, 0.906, 0.144],
];

function sampleStops(stops: RGB[], t: number): RGB {
  t = clamp01(t);
  const n = stops.length - 1;
  const scaled = t * n;
  const i0 = Math.floor(scaled);
  const i1 = Math.min(n, i0 + 1);
  const f = scaled - i0;
  const a = stops[i0];
  const b = stops[i1];
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}

export function viridis(t: number): RGB {
  return sampleStops(VIRIDIS_STOPS, t);
}

// Rainbow (HSV hue sweep, violet->red).
export function rainbow(t: number): RGB {
  t = clamp01(t);
  const h = (1 - t) * 270; // 270 (violet) -> 0 (red)
  return hsvToRgb(h, 1, 1);
}

// Spectral (diverging, colorblind-friendlier than red/green) approximation.
const SPECTRAL_STOPS: RGB[] = [
  [0.62, 0.004, 0.259],
  [0.835, 0.243, 0.31],
  [0.957, 0.427, 0.263],
  [0.992, 0.682, 0.38],
  [0.998, 0.878, 0.545],
  [1.0, 1.0, 0.749],
  [0.902, 0.961, 0.596],
  [0.671, 0.867, 0.643],
  [0.4, 0.761, 0.647],
  [0.196, 0.533, 0.741],
  [0.369, 0.31, 0.635],
];

export function spectral(t: number): RGB {
  return sampleStops(SPECTRAL_STOPS, t);
}

function hsvToRgb(h: number, s: number, v: number): RGB {
  const c = v * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = v - c;
  let r = 0,
    g = 0,
    b = 0;
  if (h < 60) [r, g, b] = [c, x, 0];
  else if (h < 120) [r, g, b] = [x, c, 0];
  else if (h < 180) [r, g, b] = [0, c, x];
  else if (h < 240) [r, g, b] = [0, x, c];
  else if (h < 300) [r, g, b] = [x, 0, c];
  else [r, g, b] = [c, 0, x];
  return [r + m, g + m, b + m];
}

export type ColormapName = 'jet' | 'viridis' | 'rainbow' | 'spectral';

export const COLORMAPS: Record<ColormapName, ColormapFn> = {
  jet,
  viridis,
  rainbow,
  spectral,
};

export const COLORMAP_NAMES: ColormapName[] = ['jet', 'viridis', 'rainbow', 'spectral'];

/** Build a normalized-value -> RGB function given a data min/max range. */
export function makeColorScale(cmap: ColormapName, min: number, max: number): (value: number) => RGB {
  const fn = COLORMAPS[cmap];
  const range = max - min;
  return (value: number) => {
    const t = range === 0 ? 0.5 : (value - min) / range;
    return fn(clamp01(t));
  };
}

/** Render a colormap as a CSS linear-gradient string for legend UI. */
export function colormapToCssGradient(cmap: ColormapName, steps = 12): string {
  const fn = COLORMAPS[cmap];
  const stops: string[] = [];
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    const [r, g, b] = fn(t);
    stops.push(`rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)}) ${Math.round(t * 100)}%`);
  }
  return `linear-gradient(to right, ${stops.join(', ')})`;
}
