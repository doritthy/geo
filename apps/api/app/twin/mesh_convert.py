"""Reality-capture / generic meshes -> 3D Tiles.

* OBJ (+MTL/textures in a ZIP), PLY, STL, GLB/glTF -> b3dm tiles.
  Textures and vertex colours are preserved (trimesh round-trip). Small
  meshes become one tile; large ones a horizontal quadtree: leaves carry
  full detail and texture (cropped to the leaf's UV region), inner nodes a
  decimated, vertex-coloured version for distant views.
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

from app.progress import report
from app.twin import georef as geo
from app.twin.tiles import TileNode, box_diagonal, build_b3dm, oriented_box, tileset_json

MESH_EXTENSIONS = (".obj", ".ply", ".stl", ".glb", ".gltf", ".off")

SINGLE_TILE_FACES = 300_000  # below this one tile is simpler and loads fine
LEAF_FACES = 150_000
PARENT_FACES = 60_000
MAX_DEPTH = 6
MAX_TEXTURE = 4096


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
        for m in meshes:
            _white_texture_factor(m)
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

        tri_count = sum(len(m.faces) for m, _ in tile_meshes)
        if tri_count <= SINGLE_TILE_FACES:
            out_meshes = []
            for m, v in tile_meshes:
                m.vertices = _to_gltf(v - origin)
                out_meshes.append(m)
            glb = trimesh.Scene(out_meshes).export(file_type="glb")
            uri = "tiles/0.b3dm"
            with open(os.path.join(out_dir, uri), "wb") as fh:
                fh.write(build_b3dm(glb, {}, 0))
            leaf = TileNode(box=box, geometric_error=0.0, content_uri=uri, origin=origin)
            root = TileNode(box=box, geometric_error=max(500.0, box_diagonal(box) * 10), children=[leaf])
            tile_count, textured = 1, any(getattr(m.visual, "kind", None) == "texture" for m in out_meshes)
        else:
            for m, v in tile_meshes:
                m.vertices = v
            lod_root, tile_count = _build_lod([m for m, _ in tile_meshes], axes, out_dir)
            root = TileNode(box=lod_root.box, geometric_error=lod_root.geometric_error * 4, children=[lod_root])
            textured = any(getattr(m.visual, "kind", None) == "texture" for m, _ in tile_meshes)
        with open(os.path.join(out_dir, "tileset.json"), "w") as fh:
            json.dump(tileset_json(root, refine="REPLACE"), fh)

        stats = {
            "triangle_count": int(tri_count),
            "mesh_count": len(tile_meshes),
            "textured": textured,
            "up_axis": up_axis,
            "bounds_source": {"min": smin.tolist(), "max": smax.tolist()},
            "tile_count": tile_count,
        }
        if crs is not None:
            stats["center"] = geo.llh_summary(np.array(box[:3]))
        return ConversionResult(georef=georef, stats=stats)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _to_gltf(rel: np.ndarray) -> np.ndarray:
    """Z-up tile frame -> glTF Y-up."""
    return np.column_stack([rel[:, 0], rel[:, 2], -rel[:, 1]])


def _white_texture_factor(m) -> None:
    """Photogrammetry textures carry baked lighting; a grey diffuse factor
    (trimesh's default, common in MTL exports) only darkens them."""
    if getattr(m.visual, "kind", None) != "texture":
        return
    mat = m.visual.material
    if getattr(mat, "baseColorTexture", None) is not None:
        mat.baseColorFactor = np.array([255, 255, 255, 255], dtype=np.uint8)
    elif getattr(mat, "image", None) is not None:
        mat.diffuse = np.array([255, 255, 255, 255], dtype=np.uint8)


def _vertex_colors(m) -> np.ndarray:
    """RGBA uint8 per vertex: texture sampled at the UVs, or existing colours."""
    try:
        if getattr(m.visual, "kind", None) == "texture":
            return np.asarray(m.visual.to_color().vertex_colors, dtype=np.uint8)
        if getattr(m.visual, "kind", None) in ("vertex", "face"):
            return np.asarray(m.visual.vertex_colors, dtype=np.uint8)
    except Exception:  # noqa: BLE001 -- a missing texture image must not stop the conversion
        pass
    return np.full((len(m.vertices), 4), (180, 180, 180, 255), dtype=np.uint8)


def _crop_texture(sub) -> None:
    """Crop the texture of a leaf submesh to its UV bounding box and cap the
    size, so tiles do not each carry the whole atlas."""
    from PIL import Image

    vis = sub.visual
    if getattr(vis, "kind", None) != "texture" or vis.uv is None or len(vis.uv) == 0:
        return
    mat = vis.material
    attr = "image" if getattr(mat, "image", None) is not None else "baseColorTexture"
    img = getattr(mat, attr, None)
    if img is None:
        return
    uv = np.asarray(vis.uv, dtype=np.float64)
    lo, hi = uv.min(axis=0), uv.max(axis=0)
    if lo.min() < -1e-6 or hi.max() > 1 + 1e-6:  # tiling UVs: leave as is
        return
    w, h = img.size
    x0, x1 = int(np.floor(lo[0] * w)), int(np.ceil(hi[0] * w))
    y0, y1 = int(np.floor((1 - hi[1]) * h)), int(np.ceil((1 - lo[1]) * h))
    x0, y0, x1, y1 = max(0, x0 - 2), max(0, y0 - 2), min(w, x1 + 2), min(h, y1 + 2)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return
    crop = img.crop((x0, y0, x1, y1))
    scale = min(1.0, MAX_TEXTURE / max(crop.size))
    if scale < 1.0:
        crop = crop.resize((max(1, int(crop.size[0] * scale)), max(1, int(crop.size[1] * scale))), Image.Resampling.LANCZOS)
    new_uv = np.column_stack([(uv[:, 0] * w - x0) / (x1 - x0), 1 - ((1 - uv[:, 1]) * h - y0) / (y1 - y0)])
    mat = mat.copy()
    setattr(mat, attr, crop)
    import trimesh

    sub.visual = trimesh.visual.TextureVisuals(uv=new_uv, material=mat)


def _build_lod(meshes: list, axes: np.ndarray, out_dir: str) -> tuple[TileNode, int]:
    """Horizontal quadtree over face centroids (faces are not cut)."""
    import trimesh
    from scipy.spatial import cKDTree

    import fast_simplification

    center = np.vstack([m.vertices for m in meshes]).mean(axis=0)
    cents = [((np.asarray(m.triangles_center) - center) @ axes.T)[:, :2] for m in meshes]
    colors = [_vertex_colors(m) for m in meshes]
    allc = np.vstack(cents)
    total_faces = len(allc)
    counter = {"n": 0, "faces_done": 0}

    def write(glb: bytes, origin: np.ndarray) -> str:
        uri = f"tiles/{counter['n']}.b3dm"
        counter["n"] += 1
        with open(os.path.join(out_dir, uri), "wb") as fh:
            fh.write(build_b3dm(glb, {}, 0))
        return uri

    def node(sel: list[np.ndarray], bmin: np.ndarray, bmax: np.ndarray, depth: int) -> TileNode | None:
        n = sum(len(s_) for s_ in sel)
        if n == 0:
            return None
        pts = np.vstack([meshes[i].vertices[meshes[i].faces[s_].reshape(-1)] for i, s_ in enumerate(sel) if len(s_)])
        origin, box = oriented_box(pts, axes, pad=0.05)
        if n <= LEAF_FACES or depth >= MAX_DEPTH:
            parts = []
            for i, s_ in enumerate(sel):
                if not len(s_):
                    continue
                sub = meshes[i].submesh([s_], append=True)
                _crop_texture(sub)
                sub.vertices = _to_gltf(np.asarray(sub.vertices) - origin)
                parts.append(sub)
            counter["faces_done"] += n
            report("Тайлы меша", counter["faces_done"] / total_faces)
            return TileNode(box=box, geometric_error=0.0, content_uri=write(trimesh.Scene(parts).export(file_type="glb"), origin), origin=origin)

        mid = (bmin + bmax) / 2
        children = []
        for qx in (0, 1):
            for qy in (0, 1):
                cmin = np.where([qx, qy], mid, bmin)
                cmax = np.where([qx, qy], bmax, mid)
                csel = []
                for i, s_ in enumerate(sel):
                    c = cents[i][s_]
                    inx = (c[:, 0] >= mid[0]) if qx else (c[:, 0] < mid[0])
                    iny = (c[:, 1] >= mid[1]) if qy else (c[:, 1] < mid[1])
                    csel.append(s_[inx & iny])
                child = node(csel, cmin, cmax, depth + 1)
                if child is not None:
                    children.append(child)

        # Decimated, vertex-coloured stand-in for everything below this node.
        vs, fs, cs, off = [], [], [], 0
        for i, s_ in enumerate(sel):
            if not len(s_):
                continue
            f = meshes[i].faces[s_]
            used, inv = np.unique(f.reshape(-1), return_inverse=True)
            vs.append(np.asarray(meshes[i].vertices)[used])
            cs.append(colors[i][used])
            fs.append(inv.reshape(-1, 3) + off)
            off += len(used)
        v, f, col = np.vstack(vs), np.vstack(fs), np.vstack(cs)
        reduction = max(0.0, 1.0 - PARENT_FACES / len(f))
        sv, sf = fast_simplification.simplify(v - origin, f, target_reduction=reduction) if reduction > 0 else (v - origin, f)
        _, nearest = cKDTree(v - origin).query(sv)
        simplified = trimesh.Trimesh(vertices=_to_gltf(sv), faces=sf, vertex_colors=col[nearest], process=False)
        area = max((bmax[0] - bmin[0]) * (bmax[1] - bmin[1]), 1e-6)
        geometric_error = 2.0 * float(np.sqrt(2.0 * area / max(len(sf), 1)))
        uri = write(simplified.export(file_type="glb"), origin)
        return TileNode(box=box, geometric_error=geometric_error, content_uri=uri, origin=origin, children=children)

    root = node([np.arange(len(c)) for c in cents], allc.min(axis=0), allc.max(axis=0) + 1e-6, 0)
    return root, counter["n"]
