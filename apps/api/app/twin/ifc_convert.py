"""IFC (2x3 / 4 / 4.3) -> 3D Tiles (b3dm) + element index.

Geometry is tessellated by IfcOpenShell (multithreaded C++), each product
becomes one *feature* (batch id) so the viewer can pick, colour, hide and
filter individual elements by GlobalId / IFC class / storey via
Cesium3DTileStyle. Elements are grouped into spatially coherent tiles so the
browser can frustum-cull and stream them instead of loading one huge file.

Georeferencing, in priority order:
1. IfcMapConversion (+ IfcProjectedCRS or the CRS given at upload) -> absolute.
2. CRS given at upload and the model is in map coordinates (|x|,|y| large)
   -> absolute.
3. IfcSite RefLatitude/RefLongitude (+ TrueNorth) -> anchor.
4. Anchor at the location given at upload (or 0,0 to be placed in the UI).
"""

from __future__ import annotations

import hashlib
import json
import math
import multiprocessing
import os
from dataclasses import dataclass, field

import numpy as np

from app.progress import report
from app.twin import georef as geo
from app.twin.tiles import Primitive, TileNode, build_b3dm, build_glb, box_diagonal, oriented_box, tileset_json, union_box

MAX_TILE_VERTICES = 300_000
_SKIP_CLASSES = ("IfcOpeningElement", "IfcSpace", "IfcVirtualElement", "IfcAnnotation", "IfcGrid")

# Fallback palette (RGBA) for products without a surface style.
_TYPE_COLORS: dict[str, tuple[float, float, float, float]] = {
    "IfcWall": (0.86, 0.84, 0.80, 1.0),
    "IfcWallStandardCase": (0.86, 0.84, 0.80, 1.0),
    "IfcSlab": (0.70, 0.70, 0.72, 1.0),
    "IfcRoof": (0.62, 0.35, 0.28, 1.0),
    "IfcColumn": (0.60, 0.62, 0.66, 1.0),
    "IfcBeam": (0.58, 0.60, 0.64, 1.0),
    "IfcWindow": (0.55, 0.75, 0.90, 0.45),
    "IfcDoor": (0.62, 0.45, 0.30, 1.0),
    "IfcStair": (0.68, 0.68, 0.68, 1.0),
    "IfcRailing": (0.40, 0.40, 0.42, 1.0),
    "IfcPlate": (0.55, 0.75, 0.90, 0.45),
    "IfcCurtainWall": (0.55, 0.75, 0.90, 0.45),
    "IfcFooting": (0.55, 0.55, 0.55, 1.0),
    "IfcPile": (0.50, 0.50, 0.50, 1.0),
    "IfcPipeSegment": (0.20, 0.55, 0.85, 1.0),
    "IfcDuctSegment": (0.75, 0.75, 0.80, 1.0),
    "IfcFurnishingElement": (0.75, 0.62, 0.45, 1.0),
}
_DEFAULT_COLOR = (0.78, 0.78, 0.78, 1.0)


@dataclass
class _ElementGeom:
    index: int
    pieces: list[tuple[tuple, np.ndarray, np.ndarray]]  # (rgba, positions (n,3), indices (m,))
    centroid: np.ndarray = field(default_factory=lambda: np.zeros(3))
    vertex_count: int = 0


@dataclass
class ConversionResult:
    georef: dict
    stats: dict
    elements: list[dict]


def _style_color(style) -> tuple[float, float, float, float] | None:
    try:
        d = style.diffuse
        r, g, b = float(d.r()), float(d.g()), float(d.b())
    except Exception:  # noqa: BLE001
        return None
    try:
        t = float(style.transparency)
        t = 0.0 if math.isnan(t) else t
    except Exception:  # noqa: BLE001
        t = 0.0
    return (r, g, b, max(0.05, 1.0 - t))


def _json_safe(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items() if k != "id"}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return str(value)


def _element_metadata(model, product) -> dict:
    import ifcopenshell.util.element as ue

    storey = None
    try:
        container = ue.get_container(product)
        if container is not None:
            storey = container.Name
    except Exception:  # noqa: BLE001
        pass
    try:
        psets = _json_safe(ue.get_psets(product))
    except Exception:  # noqa: BLE001
        psets = {}
    type_name = None
    try:
        t = ue.get_type(product)
        type_name = t.Name if t is not None else None
    except Exception:  # noqa: BLE001
        pass
    return {
        "global_id": product.GlobalId,
        "ifc_type": product.is_a(),
        "name": getattr(product, "Name", None),
        "storey": storey,
        "properties": {
            "Описание": getattr(product, "Description", None),
            "Тип": type_name,
            "ObjectType": getattr(product, "ObjectType", None),
            "Tag": getattr(product, "Tag", None),
            "psets": psets,
        },
    }


def _map_conversion(model) -> tuple[dict | None, str | None]:
    """Returns (map conversion params, CRS name from IfcProjectedCRS)."""
    try:
        conversions = model.by_type("IfcMapConversion")
    except RuntimeError:  # IFC2x3 has no such entity
        return None, None
    if not conversions:
        return None, None
    mc = conversions[0]
    a = float(mc.XAxisAbscissa) if mc.XAxisAbscissa is not None else 1.0
    b = float(mc.XAxisOrdinate) if mc.XAxisOrdinate is not None else 0.0
    norm = math.hypot(a, b) or 1.0
    params = {
        "eastings": float(mc.Eastings or 0.0),
        "northings": float(mc.Northings or 0.0),
        "orthogonal_height": float(mc.OrthogonalHeight or 0.0),
        "cos": a / norm,
        "sin": b / norm,
        "scale": float(mc.Scale) if getattr(mc, "Scale", None) else 1.0,
    }
    crs_name = None
    target = getattr(mc, "TargetCRS", None)
    if target is not None and getattr(target, "Name", None):
        crs_name = target.Name
    return params, crs_name


def _apply_map_conversion(p: np.ndarray, mc: dict) -> np.ndarray:
    s, c, sn = mc["scale"], mc["cos"], mc["sin"]
    e = mc["eastings"] + s * (c * p[:, 0] - sn * p[:, 1])
    n = mc["northings"] + s * (sn * p[:, 0] + c * p[:, 1])
    h = mc["orthogonal_height"] + p[:, 2]
    return np.column_stack([e, n, h])


def _site_anchor(model) -> dict | None:
    sites = model.by_type("IfcSite")
    if not sites:
        return None
    site = sites[0]
    lat = geo.dms_to_degrees(getattr(site, "RefLatitude", None))
    lon = geo.dms_to_degrees(getattr(site, "RefLongitude", None))
    if lat is None or lon is None or (abs(lat) < 1e-9 and abs(lon) < 1e-9):
        return None
    heading = 0.0
    try:
        for ctx in model.by_type("IfcGeometricRepresentationContext"):
            tn = getattr(ctx, "TrueNorth", None)
            if tn is not None and tn.DirectionRatios:
                tx, ty = float(tn.DirectionRatios[0]), float(tn.DirectionRatios[1])
                # Model +Y is rotated `heading` clockwise from true north.
                heading = math.degrees(math.atan2(-tx, ty))
                break
    except Exception:  # noqa: BLE001
        pass
    return {
        "longitude": lon,
        "latitude": lat,
        "height": float(getattr(site, "RefElevation", None) or 0.0),
        "heading": heading,
        "scale": 1.0,
    }


def _iterate_geometry(model) -> tuple[list[_ElementGeom], list[dict]]:
    import ifcopenshell.geom

    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    settings.set("weld-vertices", False)
    settings.set("apply-default-materials", False)

    exclude = []
    for cls in _SKIP_CLASSES:
        try:
            exclude.extend(model.by_type(cls))
        except RuntimeError:
            pass

    iterator = ifcopenshell.geom.iterator(
        settings, model, max(1, multiprocessing.cpu_count()), exclude=exclude or None
    )
    geoms: list[_ElementGeom] = []
    metas: list[dict] = []
    if not iterator.initialize():
        return geoms, metas

    while True:
        shape = iterator.get()
        g = shape.geometry
        verts = np.asarray(g.verts, dtype=np.float64).reshape(-1, 3)
        faces = np.asarray(g.faces, dtype=np.uint32).reshape(-1, 3)
        if len(verts) and len(faces):
            product = model.by_id(shape.id)
            styles = [_style_color(m) for m in g.materials]
            fallback = _TYPE_COLORS.get(shape.type, _DEFAULT_COLOR)
            mat_ids = np.asarray(g.material_ids, dtype=np.int64)
            if len(mat_ids) != len(faces):
                mat_ids = np.full(len(faces), -1)
            pieces = []
            for mid in np.unique(mat_ids):
                sel = faces[mat_ids == mid]
                color = styles[mid] if 0 <= mid < len(styles) and styles[mid] else fallback
                used, inverse = np.unique(sel.reshape(-1), return_inverse=True)
                pieces.append((color, verts[used], inverse.astype(np.uint32)))
            elem = _ElementGeom(index=len(geoms), pieces=pieces)
            elem.vertex_count = int(sum(len(p[1]) for p in pieces))
            geoms.append(elem)
            meta = _element_metadata(model, product)
            meta["geometry_hash"] = hashlib.sha1(np.round(verts, 3).tobytes()).hexdigest()
            meta["properties_hash"] = hashlib.sha1(
                json.dumps(meta["properties"], sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
            metas.append(meta)
        report("Геометрия IFC", iterator.progress() / 100.0)
        if not iterator.next():
            break
    return geoms, metas


def _partition(elems: list[_ElementGeom]) -> list[list[_ElementGeom]]:
    """Recursive median split on the longest axis of element centroids."""
    total = sum(e.vertex_count for e in elems)
    if total <= MAX_TILE_VERTICES or len(elems) <= 1:
        return [elems]
    cents = np.array([e.centroid for e in elems])
    axis = int(np.argmax(cents.max(axis=0) - cents.min(axis=0)))
    order = np.argsort(cents[:, axis], kind="stable")
    mid = len(order) // 2
    left = [elems[i] for i in order[:mid]]
    right = [elems[i] for i in order[mid:]]
    return _partition(left) + _partition(right)


def convert_ifc(path: str, out_dir: str, options: dict) -> ConversionResult:
    import ifcopenshell

    model = ifcopenshell.open(path)
    height_offset = float(options.get("height_offset") or 0.0)
    user_crs = geo.resolve_crs(options.get("crs"))
    mode_hint = options.get("georef_mode") or "auto"

    geoms, metas = _iterate_geometry(model)
    if not geoms:
        raise ValueError("В IFC-файле не найдено элементов с геометрией")

    mc, mc_crs_name = _map_conversion(model)
    mc_crs = None
    if mc is not None:
        try:
            mc_crs = user_crs or geo.resolve_crs(mc_crs_name)
        except geo.GeorefError:
            mc_crs = user_crs

    all_min = np.min([p[1].min(axis=0) for e in geoms for p in e.pieces], axis=0)
    all_max = np.max([p[1].max(axis=0) for e in geoms for p in e.pieces], axis=0)
    looks_projected = max(abs(all_min[0]), abs(all_max[0]), abs(all_min[1]), abs(all_max[1])) > 10_000

    # --- choose georeferencing ---
    to_tile = None  # callable (n,3) model coords -> tile frame
    georef: dict
    if mode_hint != "anchor" and mc is not None and mc_crs is not None:
        crs = mc_crs
        georef = {"mode": "absolute", "crs": crs.to_string(), "source": "IfcMapConversion", "height_offset": height_offset}
        to_tile = lambda p: geo.crs_to_ecef(_apply_map_conversion(p, mc), crs, height_offset)  # noqa: E731
    elif mode_hint != "anchor" and user_crs is not None and (looks_projected or mode_hint == "absolute"):
        crs = user_crs
        georef = {"mode": "absolute", "crs": crs.to_string(), "source": "model_coordinates", "height_offset": height_offset}
        to_tile = lambda p: geo.crs_to_ecef(p, crs, height_offset)  # noqa: E731
    else:
        anchor = None
        if options.get("longitude") is not None and options.get("latitude") is not None:
            anchor = {
                "longitude": float(options["longitude"]),
                "latitude": float(options["latitude"]),
                "height": float(options.get("height") or 0.0),
                "heading": float(options.get("heading") or 0.0),
                "scale": 1.0,
            }
        anchor = anchor or _site_anchor(model)
        source = "upload" if options.get("longitude") is not None else ("IfcSite" if anchor else "unplaced")
        anchor = anchor or {"longitude": 0.0, "latitude": 0.0, "height": 0.0, "heading": 0.0, "scale": 1.0}
        georef = {"mode": "anchor", "source": source, **anchor}
        to_tile = lambda p: p  # noqa: E731

    # --- transform to tile frame, compute centroids ---
    for e in geoms:
        e.pieces = [(c, to_tile(pos), idx) for c, pos, idx in e.pieces]
        allp = np.vstack([p[1] for p in e.pieces])
        e.centroid = allp.mean(axis=0)
        metas[e.index]["bbox"] = {
            "min": [round(float(v), 3) for v in allp.min(axis=0)],
            "max": [round(float(v), 3) for v in allp.max(axis=0)],
        }

    if georef["mode"] == "absolute":
        center = np.mean([e.centroid for e in geoms], axis=0)
        llh = geo.ecef_to_llh(center)[0]
        axes = geo.enu_axes(llh[0], llh[1])
    else:
        axes = np.eye(3)

    # --- tiles ---
    os.makedirs(os.path.join(out_dir, "tiles"), exist_ok=True)
    chunks = _partition(geoms)
    children: list[TileNode] = []
    for ti, chunk in enumerate(chunks):
        report("Запись тайлов", ti / max(len(chunks), 1))
        pts = np.vstack([p[1] for e in chunk for p in e.pieces])
        origin, box = oriented_box(pts, axes, pad=0.05)
        by_color: dict[tuple, list] = {}
        for batch_id, e in enumerate(chunk):
            for color, pos, idx in e.pieces:
                by_color.setdefault(color, []).append((batch_id, pos, idx))
        prims = []
        for color, parts in by_color.items():
            positions, indices, batch_ids, base = [], [], [], 0
            for batch_id, pos, idx in parts:
                positions.append(pos - origin)
                indices.append(idx + base)
                batch_ids.append(np.full(len(pos), batch_id, dtype=np.float32))
                base += len(pos)
            prims.append(
                Primitive(
                    positions=np.vstack(positions),
                    indices=np.concatenate(indices).astype(np.uint32),
                    color=color,
                    batch_ids=np.concatenate(batch_ids),
                )
            )
        batch_table = {
            "GlobalId": [metas[e.index]["global_id"] for e in chunk],
            "IfcType": [metas[e.index]["ifc_type"] for e in chunk],
            "Name": [metas[e.index]["name"] or "" for e in chunk],
            "Storey": [metas[e.index]["storey"] or "" for e in chunk],
        }
        uri = f"tiles/{ti}.b3dm"
        with open(os.path.join(out_dir, uri), "wb") as fh:
            fh.write(build_b3dm(build_glb(prims), batch_table, len(chunk)))
        children.append(TileNode(box=box, geometric_error=0.0, content_uri=uri, origin=origin))

    root_box = union_box([c.box for c in children], axes)
    root = TileNode(box=root_box, geometric_error=max(1000.0, box_diagonal(root_box) * 10), children=children)
    with open(os.path.join(out_dir, "tileset.json"), "w") as fh:
        json.dump(tileset_json(root), fh)

    types: dict[str, int] = {}
    storeys: dict[str, int] = {}
    for m in metas:
        types[m["ifc_type"]] = types.get(m["ifc_type"], 0) + 1
        if m["storey"]:
            storeys[m["storey"]] = storeys.get(m["storey"], 0) + 1

    stats = {
        "element_count": len(metas),
        "tile_count": len(children),
        "triangle_count": int(sum(len(p[2]) // 3 for e in geoms for p in e.pieces)),
        "ifc_schema": model.schema,
        "ifc_types": dict(sorted(types.items(), key=lambda kv: -kv[1])),
        "storeys": storeys,
        "bounds_model": {"min": all_min.tolist(), "max": all_max.tolist()},
    }
    if georef["mode"] == "absolute":
        stats["center"] = geo.llh_summary(np.array(root_box[:3]))
    return ConversionResult(georef=georef, stats=stats, elements=metas)
