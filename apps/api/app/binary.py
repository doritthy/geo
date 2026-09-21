"""Pack/unpack helpers for the exact little-endian binary buffer layouts
described in docs/API_CONTRACT.md. All arrays are little-endian float32
(`<f4`) or uint32 (`<u4`), produced via numpy so the byte layout is exact
and portable regardless of host endianness.
"""

import numpy as np

F32 = "<f4"
U32 = "<u4"
I32 = "<i4"


def pack_well_log(depths: np.ndarray, values: np.ndarray) -> bytes:
    """Flat Float32Array of interleaved [depth0, value0, depth1, value1, ...]."""
    depths = np.asarray(depths, dtype=F32)
    values = np.asarray(values, dtype=F32)
    interleaved = np.empty(depths.size + values.size, dtype=F32)
    interleaved[0::2] = depths
    interleaved[1::2] = values
    return interleaved.tobytes()


def unpack_well_log(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    arr = np.frombuffer(data, dtype=F32)
    return arr[0::2].copy(), arr[1::2].copy()


def pack_grid_cells(centers: np.ndarray, sizes: np.ndarray, cell_ids: np.ndarray) -> bytes:
    """centers, sizes: (cellCount, 3) float arrays. cell_ids: (cellCount,) int array.

    Layout: Float32Array[cellCount*3] centers, Float32Array[cellCount*3] sizes,
    Uint32Array[cellCount] cellId.
    """
    centers = np.ascontiguousarray(centers, dtype=F32)
    sizes = np.ascontiguousarray(sizes, dtype=F32)
    cell_ids = np.ascontiguousarray(cell_ids, dtype=U32)
    return centers.tobytes() + sizes.tobytes() + cell_ids.tobytes()


def pack_float32_array(values: np.ndarray) -> bytes:
    return np.ascontiguousarray(values, dtype=F32).tobytes()


def unpack_float32_array(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype=F32).copy()


def pack_ijk(ijk: np.ndarray) -> bytes:
    """(cellCount, 3) int array of (i, j, k) natural-order indices per active
    cell. Internal-only: not part of the public API contract, used solely by
    the /sample endpoint to reconstruct the structured lattice server-side."""
    return np.ascontiguousarray(ijk, dtype=I32).tobytes()


def unpack_ijk(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype=I32).copy().reshape(-1, 3)
