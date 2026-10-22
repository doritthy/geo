"""Point clouds (LAS / LAZ / E57 / XYZ-text) -> streamed 3D Tiles (pnts octree).

Out-of-core-ish level-of-detail build, in the spirit of Potree:

* The bounding cube is split into an octree. Level L uses a sampling grid
  with spacing ``cube / (BASE_GRID * 2**L)``: a point is kept at the
  shallowest level whose grid cell is still empty, so every level is a
  roughly uniform subsample and coarse levels stay small.
* Points that never find a free cell land in the deepest level.
* Points are processed in chunks and spilled to per-node files on disk, so
  memory does not grow with the cloud size (beyond the occupancy sets).
* Each octree node becomes one pnts tile; tiles refine with ``ADD`` so the
  browser streams only what the current view needs.

With a CRS the points are transformed exactly to ECEF (absolute mode),
otherwise they keep their local coordinates around an anchor.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np

from app.twin import georef as geo
from app.twin.tiles import TileNode, build_pnts, box_diagonal, oriented_box, tileset_json

BASE_GRID = 128
TARGET_LEAF_POINTS = 60_000
MAX_LEVEL = 10
CHUNK = 2_000_000

_REC = np.dtype([("x", "<f8"), ("y", "<f8"), ("z", "<f8"), ("r", "u1"), ("g", "u1"), ("b", "u1")])

# ASPRS LAS classification colours (used when the cloud has no RGB).
_CLASS_COLORS = {
    1: (170, 170, 170), 2: (166, 124, 82), 3: (120, 190, 90), 4: (70, 160, 60), 5: (30, 120, 40),
    6: (230, 110, 80), 7: (255, 0, 255), 9: (60, 120, 220), 17: (200, 200, 60),
}


@dataclass
class _Source:
    count: int
    mins: np.ndarray
    maxs: np.ndarray
    crs_wkt: str | None
    has_rgb: bool
    chunks: callable  # () -> Iterator[np.ndarray of _REC]


def _rgb_from_las(points, has_rgb: bool, n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if has_rgb:
        r, g, b = (np.asarray(points[c]) for c in ("red", "green", "blue"))
        if max(int(r.max(initial=0)), int(g.max(initial=0)), int(b.max(initial=0))) > 255:
            r, g, b = r >> 8, g >> 8, b >> 8
        return r.astype(np.uint8), g.astype(np.uint8), b.astype(np.uint8)
    try:
        cls = np.asarray(points["classification"]).astype(np.int64)
    except Exception:  # noqa: BLE001
        cls = np.zeros(n, dtype=np.int64)
    try:
        inten = np.asarray(points["intensity"]).astype(np.float64)
        hi = np.percentile(inten, 98) if len(inten) else 1.0
        shade = np.clip(inten / (hi or 1.0), 0.25, 1.0)
    except Exception:  # noqa: BLE001
        shade = np.ones(n)
    lut = np.tile(np.array([200, 200, 200], dtype=np.float64), (256, 1))
    for k, c in _CLASS_COLORS.items():
        lut[k] = c
    rgb = lut[np.clip(cls, 0, 255)] * shade[:, None]
    rgb = rgb.astype(np.uint8)
    return rgb[:, 0], rgb[:, 1], rgb[:, 2]


def _open_las(path: str) -> _Source:
    import laspy

    with laspy.open(path) as reader:
        header = reader.header
        count = int(header.point_count)
        mins, maxs = np.array(header.mins, dtype=np.float64), np.array(header.maxs, dtype=np.float64)
        dims = set(header.point_format.dimension_names)
        has_rgb = {"red", "green", "blue"} <= dims
        crs_wkt = None
        try:
            crs = header.parse_crs()
            crs_wkt = crs.to_wkt() if crs is not None else None
        except Exception:  # noqa: BLE001
            pass

    def chunks() -> Iterator[np.ndarray]:
        with laspy.open(path) as rd:
            for pts in rd.chunk_iterator(CHUNK):
                n = len(pts)
                rec = np.empty(n, dtype=_REC)
                rec["x"], rec["y"], rec["z"] = np.asarray(pts.x), np.asarray(pts.y), np.asarray(pts.z)
                rec["r"], rec["g"], rec["b"] = _rgb_from_las(pts, has_rgb, n)
                yield rec

    return _Source(count, mins, maxs, crs_wkt, has_rgb, chunks)


def _open_e57(path: str) -> _Source:
    import pye57

    e57 = pye57.E57(path)
    scans = []
    for i in range(e57.scan_count):
        data = e57.read_scan(i, colors=True, ignore_missing_fields=True, transform=True)
        n = len(data["cartesianX"])
        rec = np.empty(n, dtype=_REC)
        rec["x"], rec["y"], rec["z"] = data["cartesianX"], data["cartesianY"], data["cartesianZ"]
        if "colorRed" in data:
            rec["r"], rec["g"], rec["b"] = data["colorRed"], data["colorGreen"], data["colorBlue"]
        else:
            rec["r"] = rec["g"] = rec["b"] = 200
        scans.append(rec)
    allrec = np.concatenate(scans) if scans else np.empty(0, dtype=_REC)
    if len(allrec) == 0:
        raise ValueError("E57: нет точек")
    xyz = np.column_stack([allrec["x"], allrec["y"], allrec["z"]])

    def chunks() -> Iterator[np.ndarray]:
        for s in range(0, len(allrec), CHUNK):
            yield allrec[s : s + CHUNK]

    return _Source(len(allrec), xyz.min(axis=0), xyz.max(axis=0), None, True, chunks)


def _open_text(path: str) -> _Source:
    """XYZ / PTS / CSV text: x y z [r g b] per line (header lines skipped)."""
    arr = np.genfromtxt(path, comments="#", delimiter=None, invalid_raise=False, usecols=None)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    arr = arr[np.isfinite(arr[:, :3]).all(axis=1)]
    if len(arr) == 0 or arr.shape[1] < 3:
        raise ValueError("Текстовое облако точек: ожидаются колонки x y z [r g b]")
    rec = np.empty(len(arr), dtype=_REC)
    rec["x"], rec["y"], rec["z"] = arr[:, 0], arr[:, 1], arr[:, 2]
    has_rgb = arr.shape[1] >= 6
    if has_rgb:
        cols = arr[:, -3:] if arr.shape[1] in (6, 7) else arr[:, 3:6]
        if cols.max() <= 1.0:
            cols = cols * 255
        rec["r"], rec["g"], rec["b"] = (np.clip(cols[:, k], 0, 255) for k in range(3))
    else:
        rec["r"] = rec["g"] = rec["b"] = 200

    def chunks() -> Iterator[np.ndarray]:
        for s in range(0, len(rec), CHUNK):
            yield rec[s : s + CHUNK]

    xyz = np.column_stack([rec["x"], rec["y"], rec["z"]])
    return _Source(len(rec), xyz.min(axis=0), xyz.max(axis=0), None, has_rgb, chunks)


def open_point_cloud(path: str, source_format: str) -> _Source:
    if source_format in ("las", "laz"):
        return _open_las(path)
    if source_format == "e57":
        return _open_e57(path)
    return _open_text(path)


@dataclass
class ConversionResult:
    georef: dict
    stats: dict


def array_source(xyz_ecef: np.ndarray, rgb: np.ndarray) -> _Source:
    """In-memory ECEF points (analysis results, e.g. deviation maps)."""
    rec = np.empty(len(xyz_ecef), dtype=_REC)
    rec["x"], rec["y"], rec["z"] = xyz_ecef[:, 0], xyz_ecef[:, 1], xyz_ecef[:, 2]
    rec["r"], rec["g"], rec["b"] = rgb[:, 0], rgb[:, 1], rgb[:, 2]

    def chunks() -> Iterator[np.ndarray]:
        for s in range(0, len(rec), CHUNK):
            yield rec[s : s + CHUNK]

    from pyproj import CRS

    return _Source(len(rec), xyz_ecef.min(axis=0), xyz_ecef.max(axis=0), CRS.from_epsg(4978).to_wkt(), True, chunks)


def convert_point_cloud(path: str | None, source_format: str, out_dir: str, options: dict,
                        source: _Source | None = None) -> ConversionResult:
    src = source or open_point_cloud(path, source_format)
    if src.count == 0:
        raise ValueError("Облако точек пустое")

    height_offset = float(options.get("height_offset") or 0.0)
    crs = geo.resolve_crs(options.get("crs"))
    if crs is None and src.crs_wkt:
        crs = geo.resolve_crs(src.crs_wkt)
    if options.get("georef_mode") == "anchor":
        crs = None

    cube = float(max(src.maxs - src.mins)) or 1.0
    cube_min = src.mins.copy()
    depth = 0
    if src.count > TARGET_LEAF_POINTS:
        # Surface-like data: points per node shrink ~4x per level.
        depth = min(MAX_LEVEL, math.ceil(math.log(src.count / TARGET_LEAF_POINTS, 4)))

    os.makedirs(out_dir, exist_ok=True)
    work = tempfile.mkdtemp(prefix="pc-", dir=os.path.dirname(os.path.abspath(out_dir)))
    occupied: list[np.ndarray] = [np.empty(0, dtype=np.int64) for _ in range(depth)]
    node_counts: dict[tuple[int, int, int, int], int] = {}
    try:
        for rec in src.chunks():
            xyz = np.column_stack([rec["x"], rec["y"], rec["z"]])
            norm = np.clip((xyz - cube_min) / cube, 0.0, 1.0 - 1e-12)
            level = np.full(len(rec), depth, dtype=np.int64)
            remaining = np.arange(len(rec))
            for lvl in range(depth):
                if len(remaining) == 0:
                    break
                g = BASE_GRID * (2**lvl)
                cells = (norm[remaining] * g).astype(np.int64)
                keys = cells[:, 0] + cells[:, 1] * g + cells[:, 2] * g * g
                uniq, first = np.unique(keys, return_index=True)
                fresh = ~np.isin(uniq, occupied[lvl], assume_unique=True)
                take = first[fresh]
                level[remaining[take]] = lvl
                occupied[lvl] = np.union1d(occupied[lvl], uniq[fresh])
                mask = np.ones(len(remaining), dtype=bool)
                mask[take] = False
                remaining = remaining[mask]

            for lvl in np.unique(level):
                sel = np.nonzero(level == lvl)[0]
                n_side = 2**int(lvl)
                node_idx = (norm[sel] * n_side).astype(np.int64)
                keys = node_idx[:, 0] + node_idx[:, 1] * n_side + node_idx[:, 2] * n_side * n_side
                order = np.argsort(keys, kind="stable")
                sel, keys, node_idx = sel[order], keys[order], node_idx[order]
                bounds = np.flatnonzero(np.diff(keys)) + 1
                for part in np.split(np.arange(len(sel)), bounds):
                    if len(part) == 0:
                        continue
                    ix, iy, iz = (int(v) for v in node_idx[part[0]])
                    key = (int(lvl), ix, iy, iz)
                    with open(os.path.join(work, "%d-%d-%d-%d.bin" % key), "ab") as fh:
                        fh.write(rec[sel[part]].tobytes())
                    node_counts[key] = node_counts.get(key, 0) + len(part)

        return _write_tiles(work, out_dir, node_counts, src, crs, height_offset, cube, cube_min, options)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _write_tiles(work, out_dir, node_counts, src, crs, height_offset, cube, cube_min, options) -> ConversionResult:
    os.makedirs(os.path.join(out_dir, "tiles"), exist_ok=True)

    if crs is not None:
        center_src = (src.mins + src.maxs) / 2.0
        center_ecef = geo.crs_to_ecef(center_src[None, :], crs, height_offset)[0]
        llh = geo.ecef_to_llh(center_ecef)[0]
        axes = geo.enu_axes(llh[0], llh[1])
        georef = {"mode": "absolute", "crs": crs.to_string(), "height_offset": height_offset}

        def to_tile(xyz):
            return geo.crs_to_ecef(xyz, crs, height_offset)
    else:
        origin = (src.mins + src.maxs) / 2.0
        origin[2] = src.mins[2]
        axes = np.eye(3)
        georef = {
            "mode": "anchor",
            "source": "upload" if options.get("longitude") is not None else "unplaced",
            "longitude": float(options.get("longitude") or 0.0),
            "latitude": float(options.get("latitude") or 0.0),
            "height": float(options.get("height") or 0.0),
            "heading": float(options.get("heading") or 0.0),
            "scale": 1.0,
            "local_origin": origin.tolist(),
        }

        def to_tile(xyz):
            return xyz - origin

    nodes: dict[tuple, TileNode] = {}
    for key, count in sorted(node_counts.items()):
        lvl = key[0]
        rec = np.fromfile(os.path.join(work, "%d-%d-%d-%d.bin" % key), dtype=_REC)
        xyz = to_tile(np.column_stack([rec["x"], rec["y"], rec["z"]]))
        colors = np.column_stack([rec["r"], rec["g"], rec["b"]])
        center, box = oriented_box(xyz, axes, pad=0.01)
        uri = "tiles/%d-%d-%d-%d.pnts" % key
        with open(os.path.join(out_dir, uri), "wb") as fh:
            fh.write(build_pnts(xyz, colors, center))
        spacing = cube / (BASE_GRID * 2**lvl)
        # Positions are stored relative to RTC_CENTER inside the pnts payload, so
        # the tile itself carries no transform (that would apply the offset twice).
        nodes[key] = TileNode(box=box, geometric_error=spacing * 2.0, content_uri=uri)

    # Link children to parents; a missing ancestor gets an empty placeholder.
    def parent_key(k):
        return (k[0] - 1, k[1] // 2, k[2] // 2, k[3] // 2)

    for key in sorted(list(nodes.keys()), key=lambda k: -k[0]):
        k = key
        while k[0] > 0:
            pk = parent_key(k)
            if pk not in nodes:
                spacing = cube / (BASE_GRID * 2 ** pk[0])
                nodes[pk] = TileNode(box=nodes[k].box, geometric_error=spacing * 2.0)
            if not any(c is nodes[k] for c in nodes[pk].children):
                nodes[pk].children.append(nodes[k])
            k = pk

    # Parent boxes must enclose children (placeholder parents especially).
    def fix_boxes(node: TileNode) -> list[float]:
        if node.children:
            from app.twin.tiles import union_box

            boxes = [fix_boxes(c) for c in node.children] + ([node.box] if node.content_uri else [])
            node.box = union_box(boxes, axes)
        return node.box

    root = nodes[(0, 0, 0, 0)]
    fix_boxes(root)
    for node in nodes.values():
        if not node.children:
            node.geometric_error = 0.0
    with open(os.path.join(out_dir, "tileset.json"), "w") as fh:
        json.dump(tileset_json(root), fh)

    stats = {
        "point_count": int(sum(node_counts.values())),
        "tile_count": len(node_counts),
        "levels": int(max(k[0] for k in node_counts) + 1),
        "has_rgb": bool(src.has_rgb),
        "bounds_source": {"min": src.mins.tolist(), "max": src.maxs.tolist()},
        "diagonal": box_diagonal(root.box),
    }
    if crs is not None:
        stats["center"] = geo.llh_summary(np.array(root.box[:3]))
    return ConversionResult(georef=georef, stats=stats)
