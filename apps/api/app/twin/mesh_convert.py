"""Reality-capture / generic meshes -> 3D Tiles.

* OBJ (+MTL/textures in a ZIP), PLY, STL, GLB/glTF -> one textured b3dm tile.
  Textures and vertex colours are preserved (trimesh round-trip).
* A ZIP that already contains a 3D Tiles tileset (Pix4D / Agisoft Metashape /
  Bentley ContextCapture "Cesium 3D Tiles" export) is ingested as-is -- the
  recommended path for large photogrammetry, since those tools already build
  proper LOD pyramids.
"""

from __future__ import annotations

import json
import os
import shutil
import zipfile
from dataclasses import dataclass

import numpy as np

from app.twin import georef as geo
from app.twin.tiles import TileNode, box_diagonal, build_b3dm, oriented_box, tileset_json

MESH_EXTENSIONS = (".obj", ".ply", ".stl", ".glb", ".gltf", ".off")


@dataclass
class ConversionResult:
    georef: dict
    stats: dict


def _safe_extract(zf: zipfile.ZipFile, dest: str) -> None:
    root = os.path.realpath(dest)
    for member in zf.infolist():
        target = os.path.realpath(os.path.join(dest, member.filename))
        if not target.startswith(root + os.sep) and target != root:
            raise ValueError(f"Недопустимый путь в архиве: {member.filename}")
    zf.extractall(dest)


def find_tileset(directory: str) -> str | None:
    best = None
    for dirpath, _, files in os.walk(directory):
        if "tileset.json" in files:
            candidate = os.path.join(dirpath, "tileset.json")
            if best is None or candidate.count(os.sep) < best.count(os.sep):
                best = candidate
    return best


def zip_kind(path: str) -> str:
    """'tileset' | 'mesh' | 'unknown' for an uploaded archive."""
    with zipfile.ZipFile(path) as zf:
        names = [n.lower() for n in zf.namelist()]
    if any(n.endswith("tileset.json") for n in names):
        return "tileset"
    if any(n.endswith(MESH_EXTENSIONS) for n in names):
        return "mesh"
    return "unknown"


def import_tileset_zip(path: str, out_dir: str) -> ConversionResult:
    os.makedirs(out_dir, exist_ok=True)
    with zipfile.ZipFile(path) as zf:
        _safe_extract(zf, out_dir)
    tileset = find_tileset(out_dir)
    if tileset is None:
        raise ValueError("В архиве нет tileset.json")
    rel = os.path.relpath(tileset, out_dir).replace(os.sep, "/")
    with open(tileset) as fh:
        meta = json.load(fh)
    stats = {"entry": rel, "imported_tileset": True, "tileset_version": meta.get("asset", {}).get("version")}
    return ConversionResult(georef={"mode": "absolute", "source": "tileset"}, stats=stats)


def _load_meshes(path: str, workdir: str):
    import trimesh

    main = path
    if path.lower().endswith(".zip"):
        extract = os.path.join(workdir, "src")
        os.makedirs(extract, exist_ok=True)
        with zipfile.ZipFile(path) as zf:
            _safe_extract(zf, extract)
        candidates = []
        for dirpath, _, files in os.walk(extract):
            for f in files:
                if f.lower().endswith(MESH_EXTENSIONS):
                    candidates.append(os.path.join(dirpath, f))
        if not candidates:
            raise ValueError("В архиве нет файла модели (OBJ/PLY/GLB/glTF/STL)")
        candidates.sort(key=lambda p: -os.path.getsize(p))
        main = candidates[0]
    loaded = trimesh.load(main, force="scene")
    meshes = [m for m in loaded.dump(concatenate=False) if isinstance(m, trimesh.Trimesh) and len(m.faces)]
    if not meshes:
        raise ValueError("Модель не содержит треугольников")
    return meshes, os.path.splitext(main)[1].lower()


def convert_mesh(path: str, out_dir: str, options: dict) -> ConversionResult:
    import trimesh

    os.makedirs(os.path.join(out_dir, "tiles"), exist_ok=True)
    workdir = os.path.join(out_dir, "_work")
    try:
        meshes, ext = _load_meshes(path, workdir)
        up_axis = options.get("up_axis") or ("y" if ext in (".glb", ".gltf") else "z")
        height_offset = float(options.get("height_offset") or 0.0)
        crs = None if options.get("georef_mode") == "anchor" else geo.resolve_crs(options.get("crs"))

        # Source -> Z-up source frame
        def to_z_up(v: np.ndarray) -> np.ndarray:
            if up_axis == "y":
                return np.column_stack([v[:, 0], -v[:, 2], v[:, 1]])
            return v

        all_src = np.vstack([to_z_up(np.asarray(m.vertices, dtype=np.float64)) for m in meshes])
        smin, smax = all_src.min(axis=0), all_src.max(axis=0)

        if crs is not None:
            center = geo.crs_to_ecef(((smin + smax) / 2.0)[None, :], crs, height_offset)[0]
            llh = geo.ecef_to_llh(center)[0]
            axes = geo.enu_axes(llh[0], llh[1])
            georef = {"mode": "absolute", "crs": crs.to_string(), "height_offset": height_offset}

            def to_tile(v):
                return geo.crs_to_ecef(v, crs, height_offset)
        else:
            local_origin = (smin + smax) / 2.0
            local_origin[2] = smin[2]
            if np.abs(local_origin).max() < 1000:  # already a local model -> keep its origin
                local_origin = np.zeros(3)
            axes = np.eye(3)
            georef = {
                "mode": "anchor",
                "source": "upload" if options.get("longitude") is not None else "unplaced",
                "longitude": float(options.get("longitude") or 0.0),
                "latitude": float(options.get("latitude") or 0.0),
                "height": float(options.get("height") or 0.0),
                "heading": float(options.get("heading") or 0.0),
                "scale": float(options.get("scale") or 1.0),
                "local_origin": local_origin.tolist(),
            }

            def to_tile(v):
                return v - local_origin

        tile_meshes = []
        tile_points = []
        for m in meshes:
            v = to_tile(to_z_up(np.asarray(m.vertices, dtype=np.float64)))
            tile_points.append(v)
            tile_meshes.append((m, v))
        pts = np.vstack(tile_points)
        origin, box = oriented_box(pts, axes, pad=0.05)

        out_meshes = []
        tri_count = 0
        for m, v in tile_meshes:
            rel = v - origin
            # Z-up tile frame -> glTF Y-up
            m.vertices = np.column_stack([rel[:, 0], rel[:, 2], -rel[:, 1]])
            out_meshes.append(m)
            tri_count += len(m.faces)
        glb = trimesh.Scene(out_meshes).export(file_type="glb")

        uri = "tiles/0.b3dm"
        with open(os.path.join(out_dir, uri), "wb") as fh:
            fh.write(build_b3dm(glb, {}, 0))
        leaf = TileNode(box=box, geometric_error=0.0, content_uri=uri, origin=origin)
        root = TileNode(box=box, geometric_error=max(500.0, box_diagonal(box) * 10), children=[leaf])
        with open(os.path.join(out_dir, "tileset.json"), "w") as fh:
            json.dump(tileset_json(root), fh)

        stats = {
            "triangle_count": int(tri_count),
            "mesh_count": len(out_meshes),
            "textured": any(getattr(m.visual, "kind", None) == "texture" for m in out_meshes),
            "up_axis": up_axis,
            "bounds_source": {"min": smin.tolist(), "max": smax.tolist()},
            "tile_count": 1,
        }
        if crs is not None:
            stats["center"] = geo.llh_summary(np.array(box[:3]))
        return ConversionResult(georef=georef, stats=stats)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
