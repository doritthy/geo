"""Minimal, dependency-free OGC 3D Tiles 1.0 writers: glTF 2.0 (GLB) builder,
Batched 3D Model (b3dm) and Point Cloud (pnts) tile payloads, oriented
bounding boxes and tileset.json assembly.

Coordinate convention: every function here takes positions in the *tile
frame*, which is Z-up (3D Tiles convention). glTF content is Y-up by spec, so
`build_glb` converts (x, y, z) -> (x, z, -y); CesiumJS undoes that with its
standard Y-up -> Z-up transform when it loads the tile.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field

import numpy as np

_GLTF_FLOAT = 5126
_GLTF_UINT = 5125
_GLTF_ARRAY_BUFFER = 34962
_GLTF_ELEMENT_ARRAY_BUFFER = 34963


def _pad(data: bytes, align: int, fill: bytes = b"\x00") -> bytes:
    rem = len(data) % align
    return data if rem == 0 else data + fill * (align - rem)


def _json_bytes(obj, align: int = 8, start_offset: int = 0) -> bytes:
    """JSON encoded and space-padded so that `start_offset + len` is aligned."""
    raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    rem = (start_offset + len(raw)) % align
    return raw if rem == 0 else raw + b" " * (align - rem)


def z_up_to_y_up(positions: np.ndarray) -> np.ndarray:
    out = np.empty_like(positions)
    out[:, 0] = positions[:, 0]
    out[:, 1] = positions[:, 2]
    out[:, 2] = -positions[:, 1]
    return out


@dataclass
class Primitive:
    """One draw call: indexed triangles sharing a single material colour."""

    positions: np.ndarray  # (n, 3) float, tile frame (Z-up)
    indices: np.ndarray  # (m,) uint32
    color: tuple[float, float, float, float] = (0.8, 0.8, 0.8, 1.0)
    normals: np.ndarray | None = None  # (n, 3) float, tile frame (Z-up)
    batch_ids: np.ndarray | None = None  # (n,) feature index -> _BATCHID


def compute_flat_safe_normals(positions: np.ndarray, indices: np.ndarray) -> np.ndarray:
    """Area-weighted vertex normals; good enough for meshes that come without."""
    tris = indices.reshape(-1, 3)
    v0, v1, v2 = positions[tris[:, 0]], positions[tris[:, 1]], positions[tris[:, 2]]
    face_n = np.cross(v1 - v0, v2 - v0)
    normals = np.zeros_like(positions, dtype=np.float64)
    for k in range(3):
        np.add.at(normals, tris[:, k], face_n)
    lengths = np.linalg.norm(normals, axis=1)
    lengths[lengths == 0] = 1.0
    return (normals / lengths[:, None]).astype(np.float32)


def build_glb(primitives: list[Primitive]) -> bytes:
    """Assemble a single-mesh GLB from primitives (positions in Z-up tile frame)."""
    buffer = bytearray()
    buffer_views: list[dict] = []
    accessors: list[dict] = []
    materials: list[dict] = []
    material_index: dict[tuple, int] = {}
    gltf_primitives: list[dict] = []

    def add_view(data: bytes, target: int) -> int:
        nonlocal buffer
        offset = len(buffer)
        buffer += data
        buffer = bytearray(_pad(bytes(buffer), 4))
        buffer_views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(data), "target": target})
        return len(buffer_views) - 1

    def add_accessor(view: int, component: int, count: int, type_: str, minv=None, maxv=None) -> int:
        acc = {"bufferView": view, "componentType": component, "count": count, "type": type_}
        if minv is not None:
            acc["min"] = minv
            acc["max"] = maxv
        accessors.append(acc)
        return len(accessors) - 1

    for prim in primitives:
        if len(prim.indices) == 0 or len(prim.positions) == 0:
            continue
        pos = z_up_to_y_up(np.asarray(prim.positions, dtype=np.float64)).astype(np.float32)
        normals = prim.normals
        if normals is None:
            normals = compute_flat_safe_normals(np.asarray(prim.positions, dtype=np.float64), prim.indices)
        nrm = z_up_to_y_up(np.asarray(normals, dtype=np.float32)).astype(np.float32)
        idx = np.asarray(prim.indices, dtype=np.uint32)

        attributes = {
            "POSITION": add_accessor(
                add_view(pos.tobytes(), _GLTF_ARRAY_BUFFER), _GLTF_FLOAT, len(pos), "VEC3",
                pos.min(axis=0).tolist(), pos.max(axis=0).tolist(),
            ),
            "NORMAL": add_accessor(add_view(nrm.tobytes(), _GLTF_ARRAY_BUFFER), _GLTF_FLOAT, len(nrm), "VEC3"),
        }
        if prim.batch_ids is not None:
            bids = np.asarray(prim.batch_ids, dtype=np.float32)
            attributes["_BATCHID"] = add_accessor(
                add_view(bids.tobytes(), _GLTF_ARRAY_BUFFER), _GLTF_FLOAT, len(bids), "SCALAR",
                [float(bids.min())], [float(bids.max())],
            )
        indices_acc = add_accessor(
            add_view(idx.tobytes(), _GLTF_ELEMENT_ARRAY_BUFFER), _GLTF_UINT, len(idx), "SCALAR"
        )

        color = tuple(round(float(c), 4) for c in prim.color)
        if color not in material_index:
            mat = {
                "pbrMetallicRoughness": {"baseColorFactor": list(color), "metallicFactor": 0.0, "roughnessFactor": 0.9},
                "doubleSided": True,
            }
            if color[3] < 0.999:
                mat["alphaMode"] = "BLEND"
            materials.append(mat)
            material_index[color] = len(materials) - 1

        gltf_primitives.append(
            {"attributes": attributes, "indices": indices_acc, "material": material_index[color], "mode": 4}
        )

    gltf = {
        "asset": {"version": "2.0", "generator": "construction-twin"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": gltf_primitives}],
        "materials": materials,
        "buffers": [{"byteLength": len(buffer)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
    }
    return pack_glb(gltf, bytes(buffer))


def pack_glb(gltf: dict, binary: bytes) -> bytes:
    json_chunk = _json_bytes(gltf, align=4)
    bin_chunk = _pad(binary, 4)
    total = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    out = bytearray()
    out += struct.pack("<4sII", b"glTF", 2, total)
    out += struct.pack("<I4s", len(json_chunk), b"JSON") + json_chunk
    out += struct.pack("<I4s", len(bin_chunk), b"BIN\x00") + bin_chunk
    return bytes(out)


def build_b3dm(glb: bytes, batch_table: dict[str, list], batch_length: int) -> bytes:
    """Batched 3D Model tile: one feature per batch id, properties in JSON batch table."""
    header_len = 28
    ft_json = _json_bytes({"BATCH_LENGTH": batch_length}, start_offset=header_len)
    bt_json = _json_bytes(batch_table, start_offset=header_len + len(ft_json)) if batch_length else b""
    body = _pad(glb, 8)
    total = header_len + len(ft_json) + len(bt_json) + len(body)
    header = struct.pack("<4sIIIIII", b"b3dm", 1, total, len(ft_json), 0, len(bt_json), 0)
    return header + ft_json + bt_json + body


def build_pnts(positions: np.ndarray, colors: np.ndarray | None, rtc_center: np.ndarray) -> bytes:
    """Point Cloud tile. `positions` are absolute in the tile frame; they are
    stored float32 relative to `rtc_center` (RTC_CENTER) to keep precision."""
    header_len = 28
    rel = (np.asarray(positions, dtype=np.float64) - rtc_center).astype(np.float32)
    n = len(rel)
    binary = bytearray(rel.tobytes())
    ft: dict = {"POINTS_LENGTH": n, "RTC_CENTER": [float(c) for c in rtc_center], "POSITION": {"byteOffset": 0}}
    if colors is not None:
        ft["RGB"] = {"byteOffset": len(binary)}
        binary += np.asarray(colors, dtype=np.uint8).reshape(-1, 3).tobytes()
    ft_json = _json_bytes(ft, start_offset=header_len)
    ft_bin = _pad(bytes(binary), 8)
    total = header_len + len(ft_json) + len(ft_bin)
    header = struct.pack("<4sIIIIII", b"pnts", 1, total, len(ft_json), len(ft_bin), 0, 0)
    return header + ft_json + ft_bin


# ---------- bounding volumes / tileset.json ----------


def oriented_box(points: np.ndarray, axes: np.ndarray, pad: float = 0.0) -> tuple[np.ndarray, list[float]]:
    """Box aligned to `axes` (3x3, rows = unit axis vectors) enclosing `points`.

    Returns (center, box12) where box12 is the 3D Tiles `boundingVolume.box`
    (center followed by the three half-axis vectors) in the same frame."""
    pts = np.asarray(points, dtype=np.float64)
    proj = pts @ axes.T  # coordinates along each axis
    lo, hi = proj.min(axis=0) - pad, proj.max(axis=0) + pad
    half = np.maximum((hi - lo) / 2.0, 0.01)
    center = axes.T @ ((lo + hi) / 2.0)
    half_axes = [axes[i] * half[i] for i in range(3)]
    return center, [*center.tolist(), *half_axes[0].tolist(), *half_axes[1].tolist(), *half_axes[2].tolist()]


def box_relative_to(box12: list[float], origin: np.ndarray) -> list[float]:
    c = np.array(box12[:3]) - origin
    return [*c.tolist(), *box12[3:]]


def translation_matrix(t: np.ndarray) -> list[float]:
    """Column-major 4x4 translation, as tileset.json `transform` expects."""
    return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, float(t[0]), float(t[1]), float(t[2]), 1]


def union_box(boxes: list[list[float]], axes: np.ndarray) -> list[float]:
    corners = []
    for b in boxes:
        c = np.array(b[:3])
        h = [np.array(b[3:6]), np.array(b[6:9]), np.array(b[9:12])]
        for sx in (-1, 1):
            for sy in (-1, 1):
                for sz in (-1, 1):
                    corners.append(c + sx * h[0] + sy * h[1] + sz * h[2])
    return oriented_box(np.array(corners), axes)[1]


def box_diagonal(box12: list[float]) -> float:
    h = np.array(box12[3:]).reshape(3, 3)
    return float(2.0 * np.linalg.norm(h.sum(axis=0))) if h.any() else 1.0


@dataclass(eq=False)
class TileNode:
    box: list[float]  # absolute, tileset frame
    geometric_error: float
    content_uri: str | None = None
    origin: np.ndarray | None = None  # content RTC origin -> emitted as tile transform
    children: list["TileNode"] = field(default_factory=list)


def tileset_json(root: TileNode, root_transform: list[float] | None = None, refine: str = "ADD") -> dict:
    """Serialize a TileNode tree. Each node with an `origin` gets a translation
    transform (relative to its nearest transformed ancestor), and its box is
    expressed in that local frame, per the 3D Tiles transform rules.

    `refine`: ADD when children add detail to the parent (point octree, BIM
    partitions without parent content); REPLACE when a parent is a coarser
    stand-in for its children (mesh LOD)."""

    def emit(node: TileNode, parent_origin: np.ndarray) -> dict:
        origin = node.origin if node.origin is not None else parent_origin
        out: dict = {
            "boundingVolume": {"box": box_relative_to(node.box, origin)},
            "geometricError": float(node.geometric_error),
            "refine": refine,
        }
        if node.origin is not None and not np.allclose(origin, parent_origin):
            out["transform"] = translation_matrix(origin - parent_origin)
        if node.content_uri:
            out["content"] = {"uri": node.content_uri}
        if node.children:
            out["children"] = [emit(c, origin) for c in node.children]
        return out

    root_json = emit(root, np.zeros(3))
    if root_transform is not None:
        root_json["transform"] = root_transform
    return {
        "asset": {"version": "1.0", "generator": "construction-twin"},
        "geometricError": float(root.geometric_error),
        "root": root_json,
    }
