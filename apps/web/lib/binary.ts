// Binary decode helpers matching the layouts specified in docs/API_CONTRACT.md
// ("Grids", "Wells", "Surfaces" sections). All buffers are little-endian, which
// is what Float32Array/Uint32Array use natively on all browser platforms (they
// read/write in the platform's native byte order, and every platform we target
// -- x86/ARM browsers -- is little-endian), so no DataView byte-swapping is
// required as long as the buffer is not itself a sub-view with a non-zero,
// non-4-byte-aligned offset. We defensively copy via `.slice()` when the
// incoming ArrayBuffer's byteOffset could break alignment (fetch() always
// returns a fresh, zero-offset ArrayBuffer, but we guard anyway).

export interface DecodedGridCells {
  cellCount: number;
  /** Float32Array[cellCount*3], interleaved (x,y,z) per instance */
  centers: Float32Array;
  /** Float32Array[cellCount*3], interleaved (dx,dy,dz) per instance */
  sizes: Float32Array;
  /** Uint32Array[cellCount], index into the property arrays at the same lod */
  cellIds: Uint32Array;
}

/**
 * Decode the /grids/{id}/cells binary payload.
 *
 * Layout (little-endian), all arrays length `cellCount`:
 *  - Float32Array[cellCount*3] -- instance centers (x,y,z)
 *  - Float32Array[cellCount*3] -- instance sizes (dx,dy,dz)
 *  - Uint32Array[cellCount]    -- cellId
 *
 * `cellCount` is derivable from Content-Length (or passed in explicitly from
 * the `X-Cell-Count` response header, which is the authoritative source).
 */
export function decodeGridCells(buf: ArrayBuffer, cellCountHint?: number): DecodedGridCells {
  // Each cell contributes: 3 floats (center) + 3 floats (size) + 1 uint32 (id)
  // = (3*4 + 3*4 + 4) = 28 bytes/cell.
  const bytesPerCell = 3 * 4 + 3 * 4 + 4;
  const cellCount = cellCountHint ?? Math.floor(buf.byteLength / bytesPerCell);

  const centersBytes = cellCount * 3 * 4;
  const sizesBytes = cellCount * 3 * 4;

  const centers = new Float32Array(buf.slice(0, centersBytes));
  const sizes = new Float32Array(buf.slice(centersBytes, centersBytes + sizesBytes));
  const cellIds = new Uint32Array(buf.slice(centersBytes + sizesBytes, centersBytes + sizesBytes + cellCount * 4));

  return { cellCount, centers, sizes, cellIds };
}

/**
 * Decode /grids/{id}/properties/{name} -- a flat Float32Array[cellCount], one
 * value per cell, in the same order/subsampling as /cells at that lod.
 */
export function decodeGridProperty(buf: ArrayBuffer): Float32Array {
  return new Float32Array(buf.slice(0));
}

/**
 * Decode /surfaces/{id}/heights -- Float32Array[rows*cols], row-major, NaN
 * where nodata. `rows`/`cols` come from the SurfaceDetail and are only used
 * here for validation/reshaping convenience.
 */
export function decodeSurfaceHeights(buf: ArrayBuffer, rows: number, cols: number): Float32Array {
  const heights = new Float32Array(buf.slice(0));
  const expected = rows * cols;
  if (heights.length !== expected) {
    // Don't throw -- surface may still be partially usable; just warn.
    // eslint-disable-next-line no-console
    console.warn(
      `decodeSurfaceHeights: expected ${expected} values (rows=${rows} * cols=${cols}), got ${heights.length}`
    );
  }
  return heights;
}

export interface DecodedLogData {
  /** sample count (number of depth/value pairs) */
  count: number;
  depth: Float32Array;
  value: Float32Array;
}

/**
 * Decode /wells/{id}/logs/{log_id}/data -- a flat Float32Array of interleaved
 * [depth0, value0, depth1, value1, ...], little-endian.
 * `buffer.byteLength === sample_count * 2 * 4`.
 */
export function decodeLogData(buf: ArrayBuffer, sampleCountHint?: number): DecodedLogData {
  const interleaved = new Float32Array(buf.slice(0));
  const count = sampleCountHint ?? Math.floor(interleaved.length / 2);
  const depth = new Float32Array(count);
  const value = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    depth[i] = interleaved[i * 2];
    value[i] = interleaved[i * 2 + 1];
  }
  return { count, depth, value };
}
