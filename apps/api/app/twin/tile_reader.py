"""Reads back the 3D Tiles this platform wrote (b3dm with our minimal glTF,
pnts with RTC_CENTER) from object storage, for server-side analyses:
deviation maps, ICP alignment, element coverage.

Everything is returned in the tileset frame (accumulated tile transforms
applied, glTF Y-up converted back to Z-up). Apply the asset's world matrix
(`georef.asset_world_matrix`) to get ECEF.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass

import numpy as np

from app.storage import get_bytes

_COMPONENT = {5126: np.float32, 5125: np.uint32, 5123: np.uint16, 5121: np.uint8}
_NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


@dataclass
class MeshData:
    triangles: np.ndarray  # (n, 3, 3) float64, tileset frame
    feature: np.ndarray  # (n,) int64 index into `global_ids` (-1 = none)
    global_ids: list[str]
    ifc_types: list[str]
    names: list[str]


def _walk(node: dict, parent: np.ndarray, out: list):
    m = parent
    if "transform" in node:
        m = parent @ np.array(node["transform"], dtype=np.float64).reshape(4, 4).T
    if "content" in node:
        out.append((node["content"]["uri"], m))
    for child in node.get("children", []):
        _walk(child, m, out)


def list_contents(prefix: str, entry: str = "tileset.json") -> list[tuple[str, np.ndarray]]:
    tileset = json.loads(get_bytes(f"{prefix}/{entry}"))
    root_m = np.eye(4)
    out: list = []
    _walk(tileset["root"], root_m, out)
    base = entry.rsplit("/", 1)[0] + "/" if "/" in entry else ""
    return [(base + uri, m) for uri, m in out]


def _apply(m: np.ndarray, pts: np.ndarray) -> np.ndarray:
    return pts @ m[:3, :3].T + m[:3, 3]


def _parse_glb(glb: bytes):
    magic, _, _ = struct.unpack("<4sII", glb[:12])
    if magic != b"glTF":
        raise ValueError("not a GLB")
    jlen, _ = struct.unpack("<I4s", glb[12:20])
    gltf = json.loads(glb[20 : 20 + jlen])
    off = 20 + jlen
    blen, _ = struct.unpack("<I4s", glb[off : off + 8])
    binary = glb[off + 8 : off + 8 + blen]
    return gltf, binary


def _accessor(gltf: dict, binary: bytes, idx: int) -> np.ndarray:
    acc = gltf["accessors"][idx]
    view = gltf["bufferViews"][acc["bufferView"]]
    dtype = _COMPONENT[acc["componentType"]]
    n = _NCOMP[acc["type"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    arr = np.frombuffer(binary, dtype=dtype, count=acc["count"] * n, offset=start)
    return arr.reshape(-1, n) if n > 1 else arr


def _y_up_to_z_up(p: np.ndarray) -> np.ndarray:
    return np.column_stack([p[:, 0], -p[:, 2], p[:, 1]])


def read_b3dm_mesh(prefix: str, entry: str = "tileset.json") -> MeshData:
    tris_all, feat_all = [], []
    gids: list[str] = []
    types: list[str] = []
    names: list[str] = []
    gid_index: dict[str, int] = {}
    for uri, m in list_contents(prefix, entry):
        if not uri.endswith(".b3dm"):
            continue
        data = get_bytes(f"{prefix}/{uri}")
        _, _, _, ft_json, ft_bin, bt_json, bt_bin = struct.unpack("<4sIIIIII", data[:28])
        pos = 28
        ft = json.loads(data[pos : pos + ft_json]) if ft_json else {}
        pos += ft_json + ft_bin
        bt = json.loads(data[pos : pos + bt_json]) if bt_json else {}
        pos += bt_json + bt_bin
        glb = data[pos:]
        rtc = np.array(ft.get("RTC_CENTER", [0, 0, 0]), dtype=np.float64)
        local_ids = []
        for i, g in enumerate(bt.get("GlobalId", [])):
            if g not in gid_index:
                gid_index[g] = len(gids)
                gids.append(g)
                types.append((bt.get("IfcType") or [""] * (i + 1))[i])
                names.append((bt.get("Name") or [""] * (i + 1))[i])
            local_ids.append(gid_index[g])
        local_ids_arr = np.array(local_ids, dtype=np.int64)

        gltf, binary = _parse_glb(glb)
        for mesh in gltf.get("meshes", []):
            for prim in mesh["primitives"]:
                if prim.get("mode", 4) != 4:
                    continue
                p = _y_up_to_z_up(_accessor(gltf, binary, prim["attributes"]["POSITION"]).astype(np.float64)) + rtc
                p = _apply(m, p)
                idx = (
                    _accessor(gltf, binary, prim["indices"]).astype(np.int64)
                    if "indices" in prim else np.arange(len(p))
                ).reshape(-1, 3)
                tris_all.append(p[idx])
                if "_BATCHID" in prim["attributes"] and len(local_ids_arr):
                    bids = _accessor(gltf, binary, prim["attributes"]["_BATCHID"]).astype(np.int64)
                    feat_all.append(local_ids_arr[np.clip(bids[idx[:, 0]], 0, len(local_ids_arr) - 1)])
                else:
                    feat_all.append(np.full(len(idx), -1, dtype=np.int64))
    if not tris_all:
        return MeshData(np.empty((0, 3, 3)), np.empty(0, dtype=np.int64), [], [], [])
    return MeshData(np.concatenate(tris_all), np.concatenate(feat_all), gids, types, names)


def read_pnts(prefix: str, entry: str = "tileset.json", max_points: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """All points of a pnts tileset (every level: our octree stores each point
    exactly once) -> (xyz (n,3) float64 tileset frame, rgb (n,3) uint8)."""
    xyz_all, rgb_all = [], []
    for uri, m in list_contents(prefix, entry):
        if not uri.endswith(".pnts"):
            continue
        data = get_bytes(f"{prefix}/{uri}")
        _, _, _, ft_json, ft_bin, _, _ = struct.unpack("<4sIIIIII", data[:28])
        ft = json.loads(data[28 : 28 + ft_json])
        body = data[28 + ft_json : 28 + ft_json + ft_bin]
        n = ft["POINTS_LENGTH"]
        rtc = np.array(ft.get("RTC_CENTER", [0, 0, 0]), dtype=np.float64)
        p = np.frombuffer(body, dtype=np.float32, count=n * 3, offset=ft["POSITION"]["byteOffset"]).reshape(-1, 3)
        xyz_all.append(_apply(m, p.astype(np.float64) + rtc))
        if "RGB" in ft:
            rgb_all.append(np.frombuffer(body, dtype=np.uint8, count=n * 3, offset=ft["RGB"]["byteOffset"]).reshape(-1, 3))
        else:
            rgb_all.append(np.full((n, 3), 200, dtype=np.uint8))
    if not xyz_all:
        return np.empty((0, 3)), np.empty((0, 3), dtype=np.uint8)
    xyz, rgb = np.concatenate(xyz_all), np.concatenate(rgb_all)
    if max_points and len(xyz) > max_points:
        sel = np.random.default_rng(0).choice(len(xyz), max_points, replace=False)
        xyz, rgb = xyz[sel], rgb[sel]
    return xyz, rgb
